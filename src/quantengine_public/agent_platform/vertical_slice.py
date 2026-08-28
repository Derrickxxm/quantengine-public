"""One deterministic, network-free Native-Agent delivery vertical slice.

The SDK runs each bounded specialist turn.  This module only joins those turns
to the existing identity contracts and SQLite control state; it is not a
second Agent/orchestration framework.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .context import build_context_snapshot, validate_context
from .contracts import (
    ArtifactRef,
    ContextSnapshot,
    GraphIdentity,
    HandoffReceipt,
    RunRequest,
    RunResult,
    SourceIdentity,
    TaskSnapshot,
    content_digest,
    validate_handoff_receipt,
    validate_run_binding,
)
from .control_state import ControlStateError, ControlStateStore, TaskState, Transition
from quantengine_public.delivery.identity import (
    artifact_ref as delivery_artifact_ref,
    seal_artifact,
    verify_artifact,
    verify_artifact_chain,
)
from .runtime import AgentsSdkRuntime
from .tool_policy import ToolPolicy


ROLE_SKILLS = {
    "Architecture": "skill://public-architecture-agent@1",
    "Test": "skill://public-test-agent@1",
    "Development": "skill://public-development-agent@1",
    "Ops": "skill://public-ops-agent@1",
    "Quality": "skill://public-quality-shield@1",
}

_ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}
_PRODUCERS = {
    "public_delivery.architecture_packet": "public_architecture_agent",
    "public_delivery.validation_plan": "public_test_agent",
    "public_delivery.patch_manifest": "public_development_agent",
    "public_delivery.test_result": "public_test_agent",
    "public_delivery.ops_plan": "public_ops_agent",
    "public_delivery.runtime_evidence": "quantengine_public",
    "public_delivery.quality_verdict": "public_quality_shield",
}


def _canonical_type(value: str) -> str:
    return value if value.startswith("public_delivery.") else f"public_delivery.{value}"


class VerticalSliceError(RuntimeError):
    """Base error for a blocked vertical slice."""


class ReleaseTopologyError(VerticalSliceError):
    """Raised when release evidence does not form the exact required graph."""


@dataclass(frozen=True, slots=True)
class SliceArtifact:
    """Thin view over the repository-owned delivery artifact contract."""

    raw: Mapping[str, Any]

    def __post_init__(self) -> None:
        errors = verify_artifact(dict(self.raw))
        if errors:
            raise ReleaseTopologyError("invalid_artifact:" + ",".join(errors))
        payload = self.raw.get("payload")
        if not isinstance(payload, Mapping) or any(not isinstance(payload.get(key), str) or not payload.get(key) for key in ("task_id", "source_identity", "context_digest", "graph_identity")):
            raise ReleaseTopologyError("artifact_identity_binding_missing")

    @property
    def task_id(self) -> str:
        return self.raw["payload"]["task_id"]

    @property
    def source_identity(self) -> str:
        return self.raw["payload"]["source_identity"]

    @property
    def context_digest(self) -> str:
        return self.raw["payload"]["context_digest"]

    @property
    def graph_identity(self) -> str | None:
        return self.raw["payload"].get("graph_identity")

    @property
    def objective_contract_digest(self) -> str | None:
        return self.raw["payload"].get("objective_contract_digest")

    @property
    def artifact_type(self) -> str:
        return self.raw["artifact_type"]

    @property
    def producer(self) -> str:
        return self.raw["producer"]

    @property
    def status(self) -> str:
        return self.raw["status"]

    @property
    def upstream(self) -> tuple[ArtifactRef, ...]:
        return tuple(ArtifactRef(**ref) for ref in self.raw["upstream"])

    @property
    def payload(self) -> Mapping[str, Any]:
        return self.raw["payload"]

    @property
    def authority(self) -> Mapping[str, bool]:
        return self.raw["authority"]

    @property
    def artifact_digest(self) -> str:
        return self.raw["artifact_digest"]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)

    def ref(self) -> ArtifactRef:
        ref = delivery_artifact_ref(dict(self.raw))
        return ArtifactRef(ref["artifact_type"], ref["artifact_digest"])

    @classmethod
    def create(cls, *, task_id: str, source_identity: str, context_digest: str, graph_identity: str, artifact_type: str, producer: str, status: str, upstream: Iterable[ArtifactRef] = (), payload: Mapping[str, Any] | None = None, objective_contract_digest: str | None = None) -> "SliceArtifact":
        identity_payload = {
            "task_id": task_id,
            "source_identity": source_identity,
            "context_digest": context_digest,
            "graph_identity": graph_identity,
        }
        if objective_contract_digest is not None:
            identity_payload["objective_contract_digest"] = objective_contract_digest
        artifact = seal_artifact(
            artifact_type=_canonical_type(artifact_type),
            producer=producer,
            status=status,
            upstream=[ArtifactRef(_canonical_type(ref.artifact_type), ref.artifact_digest).to_dict() for ref in upstream],
            payload={**dict(payload or {}), **identity_payload},
            authority=dict(_ZERO_AUTHORITY),
        )
        return cls(artifact)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SliceArtifact":
        return cls(dict(value))


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    task: TaskSnapshot
    source: SourceIdentity
    graph: GraphIdentity
    state: TaskState
    evidence: tuple[SliceArtifact, ...]
    handoffs: tuple[HandoffReceipt, ...]
    runs: tuple[RunResult, ...]
    release: Mapping[str, Any] | None = None


def _as_artifact(value: SliceArtifact | Mapping[str, Any]) -> SliceArtifact:
    return value if isinstance(value, SliceArtifact) else SliceArtifact.from_dict(value)


def derive_release(
    *,
    task_id: str,
    source_identity: str,
    evidence: Sequence[SliceArtifact | Mapping[str, Any]],
    quality_producer: str = "public_quality_shield",
    graph_identity: str | None = None,
    objective_contract_digest: str | None = None,
) -> dict[str, Any]:
    """Derive a zero-runtime-authority release verdict from exact evidence.

    Every edge is resolved by both type and digest.  The controller has no
    model/tool side effects and never grants deployment, Paper, or Real access.
    """
    items = tuple(_as_artifact(item) for item in evidence)
    by_digest: dict[str, SliceArtifact] = {}
    chain = [item.to_dict() for item in items]
    chain_errors = verify_artifact_chain(chain)
    if chain_errors:
        raise ReleaseTopologyError("invalid_evidence_chain:" + ",".join(chain_errors))
    for item in items:
        if item.task_id != task_id or item.source_identity != source_identity:
            raise ReleaseTopologyError("release_identity_mismatch")
        if objective_contract_digest is not None and item.objective_contract_digest != objective_contract_digest:
            raise ReleaseTopologyError("release_objective_contract_mismatch")
        if item.artifact_digest in by_digest:
            raise ReleaseTopologyError("duplicate_artifact_digest")
        by_digest[item.artifact_digest] = item
        if item.artifact_type == "public_delivery.release_verdict":
            raise ReleaseTopologyError("release_input_must_not_include_release_verdict")
        if item.authority != _ZERO_AUTHORITY:
            raise ReleaseTopologyError("upstream_authority_injection")

    def exact(artifact_type: str, producer: str | None = None) -> SliceArtifact:
        found = [item for item in items if item.artifact_type == artifact_type and (producer is None or item.producer == producer)]
        if len(found) != 1:
            raise ReleaseTopologyError(f"requires_exactly_one:{artifact_type}")
        return found[0]

    runtime = exact("public_delivery.runtime_evidence", "quantengine_public")
    quality = exact("public_delivery.quality_verdict", quality_producer)
    expected_types = set(_PRODUCERS)
    if {item.artifact_type for item in items} != expected_types:
        raise ReleaseTopologyError("incomplete_or_unknown_evidence_topology")
    graph_ids = {item.graph_identity for item in items if item.graph_identity is not None}
    if len(graph_ids) != 1 or any(item.graph_identity is None for item in items):
        raise ReleaseTopologyError("graph_identity_mismatch")
    if graph_identity is not None and graph_ids != {graph_identity}:
        raise ReleaseTopologyError("graph_identity_mismatch")
    required_statuses = {
        "public_delivery.test_result": "PASS",
        "public_delivery.ops_plan": "READY",
        "public_delivery.runtime_evidence": "PASS",
    }
    if quality.status != "PASS":
        raise ReleaseTopologyError("quality_not_pass")
    if runtime.status != "PASS":
        raise ReleaseTopologyError("runtime_not_pass")
    if len(quality.upstream) != 1 or quality.upstream[0] != runtime.ref():
        raise ReleaseTopologyError("quality_runtime_topology_mismatch")

    for artifact_type, required_status in required_statuses.items():
        upstream = exact(artifact_type)
        if upstream.status != required_status:
            raise ReleaseTopologyError(f"upstream_not_pass:{artifact_type}")

    # The quality contract intentionally has one runtime edge; test/Ops are
    # bound through the runtime artifact's exact upstream set.
    runtime_types = {ref.artifact_type for ref in runtime.upstream}
    if runtime_types != {"public_delivery.test_result", "public_delivery.ops_plan"} or len(runtime.upstream) != 2:
        raise ReleaseTopologyError("runtime_requires_test_and_ops")
    for ref in runtime.upstream:
        if ref.artifact_digest not in by_digest:
            raise ReleaseTopologyError("runtime_unknown_upstream")
        upstream = by_digest[ref.artifact_digest]
        if (
            upstream.artifact_type != ref.artifact_type
            or upstream.status != required_statuses[ref.artifact_type]
        ):
            raise ReleaseTopologyError("runtime_upstream_mismatch")

    release_payload = {
        "task_id": task_id,
        "source_identity": source_identity,
        "context_digest": quality.context_digest,
        "graph_identity": quality.graph_identity,
        "decision": "exact-topology",
    }
    if objective_contract_digest is not None:
        release_payload["objective_contract_digest"] = objective_contract_digest
    return seal_artifact(
        artifact_type="public_delivery.release_verdict",
        producer="public_release_controller",
        status="PASS",
        upstream=[quality.ref().to_dict(), runtime.ref().to_dict()],
        payload=release_payload,
        authority=dict(_ZERO_AUTHORITY),
    )


class VerticalSliceRunner:
    """Run and resume the approved six-role vertical slice."""

    def __init__(self, db_path: str | Path, *, task: TaskSnapshot, source: SourceIdentity, graph: GraphIdentity) -> None:
        if task.source_reference != source.identity_digest or graph.source_commit != source.commit:
            raise VerticalSliceError("initial_identity_mismatch")
        self.task, self.source, self.graph = task, source, graph
        self._control = ControlStateStore(db_path)
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS vertical_evidence (digest TEXT PRIMARY KEY, artifact_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vertical_handoffs (digest TEXT PRIMARY KEY, receipt_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vertical_runs (run_id TEXT PRIMARY KEY, result_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vertical_releases (digest TEXT PRIMARY KEY, artifact_json TEXT NOT NULL);
        """)
        self._db.commit()
        try:
            existing = self._control.get_task(task.task_id)
        except ControlStateError:
            self._control.create_task(task, source, owner="Owner")
        else:
            if existing.source_identity != source.identity_digest:
                raise VerticalSliceError("stored_source_identity_mismatch")
            row = self._db.execute("SELECT snapshot_json FROM tasks WHERE task_id = ?", (task.task_id,)).fetchone()
            if row is None or TaskSnapshot.from_dict(json.loads(row[0])).snapshot_digest != task.snapshot_digest:
                raise VerticalSliceError("stored_task_snapshot_mismatch")
            if any(item.graph_identity not in (None, graph.identity_digest) for item in self._evidence()):
                raise VerticalSliceError("stored_graph_identity_mismatch")

    def close(self) -> None:
        self._db.close()
        self._control.close()

    def _state(self) -> TaskState:
        return self._control.get_task(self.task.task_id)

    def _evidence(self) -> list[SliceArtifact]:
        rows = self._db.execute("SELECT artifact_json FROM vertical_evidence ORDER BY rowid").fetchall()
        return [SliceArtifact.from_dict(json.loads(row[0])) for row in rows]

    def _handoffs(self) -> list[HandoffReceipt]:
        rows = self._db.execute("SELECT receipt_json FROM vertical_handoffs ORDER BY rowid").fetchall()
        return [HandoffReceipt.from_dict(json.loads(row[0])) for row in rows]

    def _runs(self) -> list[RunResult]:
        rows = self._db.execute("SELECT result_json FROM vertical_runs ORDER BY rowid").fetchall()
        values = []
        for row in rows:
            data = json.loads(row[0])
            values.append(RunResult(**{key: data[key] for key in ("run_id", "status", "stop_reason", "result_digest", "tool_call_refs", "requested_next_action", "role", "objective_contract_digest") if key in data}))
        return values

    def _save_artifact(self, artifact: SliceArtifact) -> None:
        errors = verify_artifact(artifact.to_dict())
        if errors:
            raise ReleaseTopologyError("artifact_not_admitted:" + ",".join(errors))
        prior = self._evidence()
        chain_errors = verify_artifact_chain([item.to_dict() for item in (*prior, artifact)])
        if chain_errors:
            raise ReleaseTopologyError("artifact_chain_not_admitted:" + ",".join(chain_errors))
        self._control.admit_artifact(artifact.to_dict())
        self._db.execute("INSERT OR IGNORE INTO vertical_evidence VALUES (?, ?)", (artifact.artifact_digest, json.dumps(artifact.to_dict(), sort_keys=True)))
        self._db.commit()

    def _save_handoff(self, receipt: HandoffReceipt) -> None:
        self._control.record_handoff(receipt, graph_identity=self.graph.identity_digest)
        self._db.execute("INSERT OR IGNORE INTO vertical_handoffs VALUES (?, ?)", (receipt.receipt_digest, json.dumps(receipt.to_dict(), sort_keys=True)))
        self._db.commit()
        self._control.accept_handoff(receipt, graph_identity=self.graph.identity_digest)

    def _save_run(self, result: RunResult, *, context_digest: str) -> None:
        state = self._state()
        self._control.record_run(
            result.run_id,
            task_id=self.task.task_id,
            task_version=state.version,
            source_identity=self.source.identity_digest,
            context_digest=context_digest,
            status=result.status,
            result_digest=result.result_digest,
            role=result.role,
            objective_contract_digest=result.objective_contract_digest,
        )
        self._db.execute("INSERT OR IGNORE INTO vertical_runs VALUES (?, ?)", (result.run_id, json.dumps(result.to_dict(), sort_keys=True)))
        self._db.commit()

    def _save_release(self, release: Mapping[str, Any]) -> None:
        errors = verify_artifact(dict(release))
        if errors:
            raise ReleaseTopologyError("release_not_admitted:" + ",".join(errors))
        self._control.admit_artifact(dict(release))
        self._db.execute("INSERT OR IGNORE INTO vertical_releases VALUES (?, ?)", (release["artifact_digest"], json.dumps(dict(release), sort_keys=True)))
        self._db.commit()

    def _release(self) -> Mapping[str, Any] | None:
        row = self._db.execute("SELECT artifact_json FROM vertical_releases ORDER BY rowid DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def _context(self, role: str, upstream: Iterable[ArtifactRef]) -> ContextSnapshot:
        context = build_context_snapshot(
            task=self.task,
            source=self.source,
            graph=self.graph,
            role=role,
            skill_identity=ROLE_SKILLS[role],
            tool_policy_identity=ToolPolicy.for_role(role).policy_digest,
            upstream_artifact_refs=tuple(upstream),
            selected_context_refs=(("task", self.task.task_id, "accepted"), ("graph", self.graph.revision, "source-bound")),
        )
        validate_context(
            context,
            self.source,
            self.graph,
            task=self.task,
            expected_role=role,
            expected_skill_identity=ROLE_SKILLS[role],
            expected_tool_policy_identity=ToolPolicy.for_role(role).policy_digest,
        )
        return context

    async def _agent_run(self, *, role: str, context: ContextSnapshot, stage: str) -> RunResult:
        """Execute one real SDK Agent turn with an in-process ScriptedModel."""
        try:
            from agents import Agent
            from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise VerticalSliceError("openai-agents==0.22.0_required") from exc
        runtime = AgentsSdkRuntime()
        run_id = f"{self.task.task_id.lower()}-{stage.lower().replace('_', '-')}-{self._state().version + 1}"
        if role == "Architecture":
            child_model = ScriptedModel([[assistant_message("test-plan-seed")]])
            child = Agent(name="test-planner", instructions="Return a bounded validation seed.", model=child_model)
            child_tool = child.as_tool(tool_name="validation_seed", tool_description="request a validation seed")

            def request_child(call: Any) -> list[Any]:
                return [function_call("validation_seed", {"input": "authority topology"}, call_id="validation-seed-1")]

            model = ScriptedModel([ModelStep.respond(request_child), [assistant_message(f"{role}:{stage}:accepted")]])
            agent = runtime.agent(role.lower(), f"Execute the bounded {role} stage and return a concise result.", model=model, tools=[child_tool])
        else:
            model = ScriptedModel([[assistant_message(f"{role}:{stage}:accepted")]])
            agent = runtime.agent(role.lower(), f"Execute the bounded {role} stage and return a concise result.", model=model)
        request = RunRequest(
            run_id=run_id,
            task_id=self.task.task_id,
            expected_task_version=self._state().version,
            role=role,
            collaboration_mode="independent_review" if role == "Quality" else ("agent_as_tool" if role == "Architecture" else "handoff"),
            context_digest=context.context_digest,
            skill_identity=context.skill_identity,
            allowed_tool_policy=context.tool_policy_identity,
            required_output_type="text",
            upstream_artifact_refs=context.upstream_artifact_refs,
            timeout_policy="bounded-local-scripted",
            idempotency_key=run_id,
            objective_contract_digest=self.task.objective_contract_digest,
        )
        validate_run_binding(request, task=self.task, context=context)
        result = await runtime.run(agent, json.dumps(request.to_dict(), sort_keys=True), run_config={"tracing_disabled": True})
        model.assert_complete()
        if role == "Architecture":
            child_model.assert_complete()
        final = getattr(result, "final_output", "")
        sealed = RunResult(
            run_id=request.run_id,
            status="PASS",
            stop_reason="completed",
            result_digest=content_digest({"output": str(final), "context": context.context_digest}),
            tool_call_refs=(),
            requested_next_action=None,
            role=role,
            objective_contract_digest=self.task.objective_contract_digest,
        )
        validate_run_binding(request, task=self.task, context=context, result=sealed)
        self._save_run(sealed, context_digest=context.context_digest)
        return sealed

    def _artifact(self, *, context: ContextSnapshot, artifact_type: str, status: str = "PASS", upstream: Iterable[ArtifactRef] = (), payload: Mapping[str, Any] | None = None) -> SliceArtifact:
        artifact_type = _canonical_type(artifact_type)
        artifact = SliceArtifact.create(
            task_id=self.task.task_id,
            source_identity=self.source.identity_digest,
            context_digest=context.context_digest,
            graph_identity=self.graph.identity_digest,
            artifact_type=artifact_type,
            producer=_PRODUCERS[artifact_type],
            status=status,
            upstream=tuple(upstream),
            payload={"stage": artifact_type, **dict(payload or {})},
            objective_contract_digest=self.task.objective_contract_digest,
        )
        self._save_artifact(artifact)
        return artifact

    def _handoff(self, *, from_owner: str, to_role: str, task_version: int, context: ContextSnapshot, refs: Iterable[ArtifactRef], prior_state: TaskState) -> None:
        refs = tuple(refs)
        if prior_state.owner != from_owner or task_version != prior_state.version + 1:
            raise VerticalSliceError("handoff_owner_or_version_mismatch")
        admitted = {item.ref() for item in self._evidence()}
        if any(ref not in admitted for ref in refs):
            raise VerticalSliceError("handoff_requires_admitted_refs")
        receipt = HandoffReceipt(
            task_id=self.task.task_id,
            task_version=task_version,
            from_owner=from_owner,
            to_role=to_role,
            source_identity=self.source.identity_digest,
            context_digest=context.context_digest,
            required_artifact_refs=tuple(refs),
            accepted_or_rejected="accepted",
            reason="identity-bound stage complete",
            next_owner=to_role,
            graph_identity=self.graph.identity_digest,
            objective_contract_digest=self.task.objective_contract_digest,
        )
        if receipt.graph_identity != context.graph_identity:
            raise VerticalSliceError("handoff_graph_mismatch")
        validate_handoff_receipt(receipt, task=self.task, source=self.source, context=context, expected_task_version=task_version)
        self._save_handoff(receipt)

    def _transition(
        self,
        state: TaskState,
        next_state: str,
        *,
        next_owner: str,
        reason: str,
        key: str,
        evidence_refs: Iterable[ArtifactRef] = (),
        context_digest: str | None = None,
    ) -> Transition:
        return self._control.transition(
            task_id=self.task.task_id,
            expected_version=state.version,
            expected_state=state.state,
            next_state=next_state,
            owner=state.owner,
            source=self.source,
            reason=reason,
            idempotency_key=key,
            next_owner=next_owner,
            evidence_refs=tuple(evidence_refs),
            context_digest=context_digest,
            objective_contract_digest=self.task.objective_contract_digest,
        )

    async def run(self, stop_after: str | None = None) -> VerticalSliceResult:
        """Advance until Release, optionally stopping after a committed state."""
        while True:
            state = self._state()
            if stop_after and state.state == stop_after:
                return self.result()
            if state.state == "DRAFT":
                self._transition(state, "ACCEPTED", next_owner="Architecture", reason="Owner accepted bounded defect", key="accept")
            elif state.state == "ACCEPTED":
                self._transition(state, "CONTEXT_READY", next_owner="Architecture", reason="current source and graph context assembled", key="context")
            elif state.state == "CONTEXT_READY":
                context = self._context("Architecture", ())
                await self._agent_run(role="Architecture", context=context, stage="architecture")
                artifact = self._artifact(context=context, artifact_type="architecture_packet", status="READY", payload={"affected_contract": "release topology", "approved_paths": ["src/quantengine_public/agent_platform"]})
                transition = self._transition(state, "ARCHITECTURE_READY", next_owner="Architecture", reason="architecture impact packet admitted", key="architecture", evidence_refs=(artifact.ref(),), context_digest=context.context_digest)
                self._handoff(from_owner="Architecture", to_role="Test", task_version=transition.version, context=context, refs=(artifact.ref(),), prior_state=state)
            elif state.state == "ARCHITECTURE_READY":
                refs = [item.ref() for item in self._evidence()]
                context = self._context("Test", refs)
                await self._agent_run(role="Test", context=context, stage="red-oracle")
                artifact = self._artifact(context=context, artifact_type="validation_plan", status="READY", payload={"negative_cases": ["missing runtime", "missing quality", "wrong producer", "authority injection"]})
                transition = self._transition(state, "VALIDATION_READY", next_owner="Test", reason="author red oracle admitted", key="validation", evidence_refs=(artifact.ref(),), context_digest=context.context_digest)
                self._handoff(from_owner="Test", to_role="Development", task_version=transition.version, context=context, refs=tuple(refs + [artifact.ref()]), prior_state=state)
            elif state.state == "VALIDATION_READY":
                refs = [item.ref() for item in self._evidence()]
                context = self._context("Development", refs)
                await self._agent_run(role="Development", context=context, stage="development")
                artifact = self._artifact(context=context, artifact_type="patch_manifest", status="READY", payload={"changed_paths": ["src/quantengine_public/agent_platform/vertical_slice.py"], "scope_checked": True})
                transition = self._transition(state, "IMPLEMENTATION_READY", next_owner="Development", reason="approved-scope implementation admitted", key="development", evidence_refs=(artifact.ref(),), context_digest=context.context_digest)
                self._handoff(from_owner="Development", to_role="Test", task_version=transition.version, context=context, refs=tuple(refs + [artifact.ref()]), prior_state=state)
            elif state.state == "IMPLEMENTATION_READY":
                refs = [item.ref() for item in self._evidence()]
                context = self._context("Test", refs)
                await self._agent_run(role="Test", context=context, stage="verify")
                artifact = self._artifact(context=context, artifact_type="test_result", payload={"red_oracle": "PASS", "verification": "PASS"})
                transition = self._transition(state, "TEST_VERIFIED", next_owner="Test", reason="independent declared tests pass", key="test-verify", evidence_refs=(artifact.ref(),), context_digest=context.context_digest)
                self._handoff(from_owner="Test", to_role="Ops", task_version=transition.version, context=context, refs=tuple(refs + [artifact.ref()]), prior_state=state)
            elif state.state == "TEST_VERIFIED":
                refs = [item.ref() for item in self._evidence()]
                context = self._context("Ops", refs)
                await self._agent_run(role="Ops", context=context, stage="ops")
                ops = self._artifact(context=context, artifact_type="ops_plan", status="READY", payload={"ci": "PASS", "clean_install": "PASS", "deployment": "FORBIDDEN"})
                runtime = self._artifact(context=context, artifact_type="runtime_evidence", upstream=(refs[-1], ops.ref()), payload={"status": "PASS", "authority": "zero"})
                transition = self._transition(state, "OPS_READY", next_owner="Ops", reason="Ops plan and zero-authority runtime evidence prepared", key="ops", evidence_refs=(ops.ref(),), context_digest=context.context_digest)
            elif state.state == "OPS_READY":
                evidence = self._evidence()
                refs = [item.ref() for item in evidence]
                pre_ops_refs = [
                    item.ref()
                    for item in evidence
                    if item.artifact_type
                    not in {"public_delivery.ops_plan", "public_delivery.runtime_evidence"}
                ]
                context = self._context("Ops", pre_ops_refs)
                runtime = next(
                    item
                    for item in evidence
                    if item.artifact_type == "public_delivery.runtime_evidence"
                )
                transition = self._transition(state, "RUNTIME_VERIFIED", next_owner="Ops", reason="runtime readback verified", key="runtime", evidence_refs=(runtime.ref(),), context_digest=runtime.context_digest)
                self._handoff(from_owner="Ops", to_role="Quality", task_version=transition.version, context=context, refs=tuple(refs), prior_state=state)
            elif state.state == "RUNTIME_VERIFIED":
                refs = [item.ref() for item in self._evidence()]
                runtime_ref = next(ref for ref in refs if ref.artifact_type == "public_delivery.runtime_evidence")
                context = self._context("Quality", refs)
                await self._agent_run(role="Quality", context=context, stage="independent-quality")
                quality = self._artifact(context=context, artifact_type="quality_verdict", upstream=(runtime_ref,), payload={"negative_attack_suite": "PASS", "authority": "zero"})
                transition = self._transition(state, "QUALITY_REVIEWED", next_owner="Quality", reason="independent quality consumes exact runtime evidence", key="quality", evidence_refs=(quality.ref(),), context_digest=context.context_digest)
                self._handoff(from_owner="Quality", to_role="Release Controller", task_version=transition.version, context=context, refs=tuple(refs + [quality.ref()]), prior_state=state)
            elif state.state == "QUALITY_REVIEWED":
                release = derive_release(
                    task_id=self.task.task_id,
                    source_identity=self.source.identity_digest,
                    graph_identity=self.graph.identity_digest,
                    evidence=self._evidence(),
                    objective_contract_digest=self.task.objective_contract_digest,
                )
                self._save_release(release)
                release_ref = ArtifactRef(release["artifact_type"], release["artifact_digest"])
                self._transition(
                    state,
                    "RELEASE_DECIDED",
                    next_owner="Owner",
                    reason="deterministic exact-topology release decision",
                    key="release",
                    evidence_refs=(release_ref,),
                    context_digest=release["payload"]["context_digest"],
                )
                return self.result(release=release)
            elif state.state == "RELEASE_DECIDED":
                return self.result()
            else:
                raise VerticalSliceError(f"unsupported_resume_state:{state.state}")

    def result(self, release: Mapping[str, Any] | None = None) -> VerticalSliceResult:
        state = self._state()
        if release is None:
            release = self._release()
        if release is None and state.state == "RELEASE_DECIDED":
            try:
                release = derive_release(
                    task_id=self.task.task_id,
                    source_identity=self.source.identity_digest,
                    graph_identity=self.graph.identity_digest,
                    evidence=self._evidence(),
                    objective_contract_digest=self.task.objective_contract_digest,
                )
            except ReleaseTopologyError:
                release = None
        return VerticalSliceResult(self.task, self.source, self.graph, state, tuple(self._evidence()), tuple(self._handoffs()), tuple(self._runs()), release)


__all__ = ["ReleaseTopologyError", "ROLE_SKILLS", "SliceArtifact", "VerticalSliceError", "VerticalSliceResult", "VerticalSliceRunner", "derive_release"]
