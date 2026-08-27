"""Deterministic authority and evidence contracts for hosted Phase 2 gates.

The module contains no API client and never reads credentials.  A separate
executor may consume an authorization, but only digest-only observations and
receipts cross back into the public evidence layer.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .contracts import canonical_json, content_digest

SCHEMA_VERSION = "quantengine_public.agent_platform.hosted_phase2.v1"
MODEL_ID = "gpt-5.6-luna"
OWNER_DECISION = "DEC-0017"
MAX_TOTAL_BUDGET_MICROUSD = 100_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROLE_ORDER = ("architecture", "test", "development", "quality")
_STAGE_POLICY: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "architecture": ((), ()),
    "readonly_tool": (("lookup_public_source",), ()),
    "handoff": ((), ("architecture", "test")),
    "development_loop": ((), _ROLE_ORDER),
}
_STAGE_REQUEST_MULTIPLIER = {
    "architecture": 1,
    "readonly_tool": 2,
    "handoff": 2,
    "development_loop": 4,
}
_OUTPUT_FIELDS: dict[str, frozenset[str]] = {
    "architecture": frozenset({"summary", "affected_paths", "risks", "validation"}),
    "readonly_tool": frozenset({"summary", "source_facts", "risks", "validation"}),
    "handoff": frozenset({"summary", "test_cases", "risks", "verdict"}),
    "development_loop": frozenset({"summary", "changed_paths", "tests", "verdict"}),
}
_SENSITIVE_MARKERS = (
    "sk-",
    "api_key",
    "openai_api_key",
    "/users/",
    "-----begin private key",
    '"authorization":',
    "bearer ",
    "private_key",
    "client_secret",
    "access_token",
    "refresh_token",
    "ssh-rsa",
    "ssh-ed25519",
)


class HostedPhase2Error(ValueError):
    """Raised when a Phase 2 request, observation, or receipt exceeds authority."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostedPhase2Error(f"{name}_required")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise HostedPhase2Error(f"{name}_invalid")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HostedPhase2Error(f"{name}_invalid")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HostedPhase2Error(f"{name}_invalid")
    return value


def _strings(values: Any, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise HostedPhase2Error(f"{name}_invalid")
    return tuple(_text(value, name) for value in values)


def _nonempty_strings(values: Any, name: str) -> tuple[str, ...]:
    checked = _strings(values, name)
    if not checked:
        raise HostedPhase2Error(f"{name}_required")
    return checked


def _public_relative_paths(values: Any, name: str) -> tuple[str, ...]:
    checked = _nonempty_strings(values, name)
    allowed_roots = (
        ".github/",
        "docs/",
        "scripts/",
        "src/",
        "tests/",
    )
    allowed_files = {"CHANGELOG.md", "README.md", "pyproject.toml"}
    for value in checked:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or (value not in allowed_files and not value.startswith(allowed_roots))
        ):
            raise HostedPhase2Error(f"{name}_outside_public_scope")
    return checked


def _validate_stage_output(stage: str, output: Mapping[str, Any]) -> None:
    required = _OUTPUT_FIELDS[stage]
    if set(output) != required:
        raise HostedPhase2Error("output_schema_invalid")
    _text(output["summary"], "output_summary")
    if stage == "architecture":
        _public_relative_paths(output["affected_paths"], "affected_paths")
        _nonempty_strings(output["risks"], "risks")
        _nonempty_strings(output["validation"], "validation")
    elif stage == "readonly_tool":
        _nonempty_strings(output["source_facts"], "source_facts")
        _strings(output["risks"], "risks")
        _nonempty_strings(output["validation"], "validation")
    elif stage == "handoff":
        _nonempty_strings(output["test_cases"], "test_cases")
        _strings(output["risks"], "risks")
        if output["verdict"] != "PASS":
            raise HostedPhase2Error("handoff_verdict_not_pass")
    else:
        _public_relative_paths(output["changed_paths"], "changed_paths")
        _nonempty_strings(output["tests"], "tests")
        if output["verdict"] != "PASS":
            raise HostedPhase2Error("development_loop_verdict_not_pass")


def estimate_cost_microusd(*, input_tokens: int, output_tokens: int) -> int:
    """Return a ceiling cost at the locked Luna price in millionths of USD.

    DEC-0017 locks the reviewed price of USD 0.20 per million
    input tokens and USD 1.20 per million output tokens.  That is 0.2 and
    1.2 micro-USD per token respectively.
    """

    _nonnegative_int(input_tokens, "input_tokens")
    _nonnegative_int(output_tokens, "output_tokens")
    tenths_of_microusd = input_tokens * 2 + output_tokens * 12
    return (tenths_of_microusd + 9) // 10


@dataclass(frozen=True, slots=True)
class HostedPhase2Policy:
    model: str = MODEL_ID
    max_turns: int = 2
    max_input_chars: int = 24_000
    max_output_tokens: int = 1_200
    max_timeout_seconds: int = 90
    total_budget_microusd: int = 100_000
    tracing_disabled: bool = True
    evidence_mode: str = "digest_only"

    def __post_init__(self) -> None:
        if self.model != MODEL_ID:
            raise HostedPhase2Error("model_not_authorized")
        _positive_int(self.max_turns, "max_turns")
        _positive_int(self.max_input_chars, "max_input_chars")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        _positive_int(self.max_timeout_seconds, "max_timeout_seconds")
        _positive_int(self.total_budget_microusd, "total_budget_microusd")
        if self.total_budget_microusd > MAX_TOTAL_BUDGET_MICROUSD:
            raise HostedPhase2Error("hosted_budget_cap_exceeded")
        if self.tracing_disabled is not True:
            raise HostedPhase2Error("hosted_trace_not_authorized")
        if self.evidence_mode != "digest_only":
            raise HostedPhase2Error("raw_evidence_not_authorized")

    @property
    def policy_digest(self) -> str:
        return content_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        body = {
            "schema_version": SCHEMA_VERSION,
            "model": self.model,
            "max_turns": self.max_turns,
            "max_input_chars": self.max_input_chars,
            "max_output_tokens": self.max_output_tokens,
            "max_timeout_seconds": self.max_timeout_seconds,
            "total_budget_microusd": self.total_budget_microusd,
            "tracing_disabled": self.tracing_disabled,
            "evidence_mode": self.evidence_mode,
        }
        if include_digest:
            body["policy_digest"] = self.policy_digest
        return body


@dataclass(frozen=True, slots=True)
class HostedStagePlan:
    stage: str
    task_id: str
    task_revision: str
    source_identity: str
    context_digest: str
    agent_graph_identity: str
    predecessor_receipt_digest: str
    model: str
    max_turns: int
    max_input_chars: int
    max_output_tokens: int
    timeout_seconds: int
    trace_mode: str
    evidence_mode: str
    tool_names: tuple[str, ...]
    handoff_route: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.stage not in _STAGE_POLICY:
            raise HostedPhase2Error("stage_not_authorized")
        _text(self.task_id, "task_id")
        _text(self.task_revision, "task_revision")
        _digest(self.source_identity, "source_identity")
        _digest(self.context_digest, "context_digest")
        _digest(self.agent_graph_identity, "agent_graph_identity")
        _digest(self.predecessor_receipt_digest, "predecessor_receipt_digest")
        _text(self.model, "model")
        _positive_int(self.max_turns, "max_turns")
        _positive_int(self.max_input_chars, "max_input_chars")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        _positive_int(self.timeout_seconds, "timeout_seconds")
        _text(self.trace_mode, "trace_mode")
        _text(self.evidence_mode, "evidence_mode")
        object.__setattr__(self, "tool_names", _strings(self.tool_names, "tool_names"))
        object.__setattr__(
            self, "handoff_route", _strings(self.handoff_route, "handoff_route")
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "agent_graph_identity": self.agent_graph_identity,
            "predecessor_receipt_digest": self.predecessor_receipt_digest,
            "model": self.model,
            "max_turns": self.max_turns,
            "max_input_chars": self.max_input_chars,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "trace_mode": self.trace_mode,
            "evidence_mode": self.evidence_mode,
            "tool_names": list(self.tool_names),
            "handoff_route": list(self.handoff_route),
        }

    @property
    def plan_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "plan_digest": self.plan_digest}


@dataclass(frozen=True, slots=True)
class StageAuthorization:
    run_identity: str
    sequence: int
    stage: str
    task_id: str
    plan_digest: str
    policy_digest: str
    prompt_digest: str
    owner_decision: str
    model: str
    trace_mode: str
    reserved_cost_microusd: int
    remaining_budget_microusd: int
    verdict: str = "AUTHORIZED"

    def __post_init__(self) -> None:
        _digest(self.run_identity, "run_identity")
        _nonnegative_int(self.sequence, "sequence")
        if self.stage not in _STAGE_POLICY:
            raise HostedPhase2Error("stage_not_authorized")
        _text(self.task_id, "task_id")
        _digest(self.plan_digest, "plan_digest")
        _digest(self.policy_digest, "policy_digest")
        _digest(self.prompt_digest, "prompt_digest")
        if self.owner_decision != OWNER_DECISION:
            raise HostedPhase2Error("owner_decision_mismatch")
        if self.model != MODEL_ID:
            raise HostedPhase2Error("model_not_authorized")
        if self.trace_mode != "disabled":
            raise HostedPhase2Error("hosted_trace_not_authorized")
        _nonnegative_int(self.reserved_cost_microusd, "reserved_cost_microusd")
        _nonnegative_int(self.remaining_budget_microusd, "remaining_budget_microusd")
        if self.verdict != "AUTHORIZED":
            raise HostedPhase2Error("authorization_not_granted")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_identity": self.run_identity,
            "sequence": self.sequence,
            "stage": self.stage,
            "task_id": self.task_id,
            "plan_digest": self.plan_digest,
            "policy_digest": self.policy_digest,
            "prompt_digest": self.prompt_digest,
            "owner_decision": self.owner_decision,
            "model": self.model,
            "trace_mode": self.trace_mode,
            "reserved_cost_microusd": self.reserved_cost_microusd,
            "remaining_budget_microusd": self.remaining_budget_microusd,
            "verdict": self.verdict,
        }

    @property
    def authorization_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "authorization_digest": self.authorization_digest}


def authorize_stage(
    plan: HostedStagePlan,
    policy: HostedPhase2Policy,
    *,
    owner_decision: str,
    run_identity: str,
    sequence: int,
    prompt_digest: str,
    predecessor_receipt_digest: str,
    spent_microusd: int,
) -> StageAuthorization:
    """Build a deterministic authorization value.

    This helper does not make the value consumable. Production execution must
    issue and consume it through :class:`HostedRunAuthority`, which owns the
    run sequence and atomic budget ledger.
    """

    if owner_decision != OWNER_DECISION:
        raise HostedPhase2Error("owner_decision_mismatch")
    _digest(predecessor_receipt_digest, "predecessor_receipt_digest")
    _digest(run_identity, "run_identity")
    _nonnegative_int(sequence, "sequence")
    _digest(prompt_digest, "prompt_digest")
    if predecessor_receipt_digest != plan.predecessor_receipt_digest:
        raise HostedPhase2Error("predecessor_receipt_mismatch")
    _nonnegative_int(spent_microusd, "spent_microusd")
    if plan.model != policy.model:
        raise HostedPhase2Error("model_not_authorized")
    if plan.max_turns > policy.max_turns:
        raise HostedPhase2Error("max_turns_exceeds_policy")
    if plan.max_input_chars > policy.max_input_chars:
        raise HostedPhase2Error("max_input_chars_exceeds_policy")
    if plan.max_output_tokens > policy.max_output_tokens:
        raise HostedPhase2Error("max_output_tokens_exceeds_policy")
    if plan.timeout_seconds > policy.max_timeout_seconds:
        raise HostedPhase2Error("timeout_exceeds_policy")
    if plan.trace_mode != "disabled" or not policy.tracing_disabled:
        raise HostedPhase2Error("hosted_trace_not_authorized")
    if plan.evidence_mode != policy.evidence_mode:
        raise HostedPhase2Error("raw_evidence_not_authorized")
    expected_tools, expected_route = _STAGE_POLICY[plan.stage]
    if plan.tool_names != expected_tools:
        raise HostedPhase2Error("stage_tool_policy_mismatch")
    if plan.handoff_route != expected_route:
        raise HostedPhase2Error("stage_handoff_policy_mismatch")
    per_request_reserve = estimate_cost_microusd(
        input_tokens=plan.max_input_chars,
        output_tokens=plan.max_output_tokens,
    )
    reserved = per_request_reserve * _STAGE_REQUEST_MULTIPLIER[plan.stage]
    remaining = policy.total_budget_microusd - spent_microusd - reserved
    if remaining < 0:
        raise HostedPhase2Error("hosted_budget_exceeded")
    return StageAuthorization(
        run_identity=run_identity,
        sequence=sequence,
        stage=plan.stage,
        task_id=plan.task_id,
        plan_digest=plan.plan_digest,
        policy_digest=policy.policy_digest,
        prompt_digest=prompt_digest,
        owner_decision=owner_decision,
        model=plan.model,
        trace_mode=plan.trace_mode,
        reserved_cost_microusd=reserved,
        remaining_budget_microusd=remaining,
    )


class HostedRunAuthority:
    """Run-bound, single-use authorization and budget ledger.

    The ledger is deliberately in-process and non-serializable. It prevents a
    caller from replaying a stage lease, inventing ``spent_microusd``, or
    running stages out of order. A failed consumed lease is charged at its
    conservative reservation so a retry can never appear free.
    """

    _ORDER = ("architecture", "readonly_tool", "handoff", "development_loop")

    def __init__(
        self,
        *,
        policy: HostedPhase2Policy,
        run_identity: str,
        initial_predecessor_receipt_digest: str,
        prompt_manifest: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy
        self.run_identity = _digest(run_identity, "run_identity")
        self._predecessor = _digest(
            initial_predecessor_receipt_digest,
            "initial_predecessor_receipt_digest",
        )
        self._lock = threading.RLock()
        self._sequence = 0
        self._accounted_cost_microusd = 0
        self._active: StageAuthorization | None = None
        self._consumed = False
        self._blocked = False
        if prompt_manifest is None:
            self._prompt_manifest: Mapping[str, str] | None = None
        else:
            supplied = dict(prompt_manifest)
            if tuple(supplied) != self._ORDER:
                raise HostedPhase2Error("prompt_manifest_topology_invalid")
            checked = {
                stage: content_digest({"prompt": _text(supplied[stage], "prompt")})
                for stage in self._ORDER
            }
            self._prompt_manifest = MappingProxyType(checked)

    @property
    def prompt_manifest_bound(self) -> bool:
        return self._prompt_manifest is not None

    @property
    def prompt_manifest_digest(self) -> str:
        if self._prompt_manifest is None:
            raise HostedPhase2Error("prompt_manifest_required")
        return content_digest(dict(self._prompt_manifest))

    @property
    def accounted_cost_microusd(self) -> int:
        with self._lock:
            return self._accounted_cost_microusd

    @property
    def active_reserved_cost_microusd(self) -> int:
        with self._lock:
            return 0 if self._active is None else self._active.reserved_cost_microusd

    def authorize(self, plan: HostedStagePlan, *, prompt: str) -> StageAuthorization:
        with self._lock:
            if self._blocked:
                raise HostedPhase2Error("run_authority_blocked")
            if self._active is not None:
                raise HostedPhase2Error("authorization_already_active")
            if (
                self._sequence >= len(self._ORDER)
                or plan.stage != self._ORDER[self._sequence]
            ):
                raise HostedPhase2Error("stage_sequence_invalid")
            if plan.predecessor_receipt_digest != self._predecessor:
                raise HostedPhase2Error("predecessor_receipt_mismatch")
            prompt_value = _text(prompt, "prompt")
            if len(prompt_value) > plan.max_input_chars:
                raise HostedPhase2Error("prompt_exceeds_plan")
            if self._prompt_manifest is not None and self._prompt_manifest[
                plan.stage
            ] != content_digest({"prompt": prompt_value}):
                raise HostedPhase2Error("prompt_manifest_mismatch")
            authorization = authorize_stage(
                plan,
                self.policy,
                owner_decision=OWNER_DECISION,
                run_identity=self.run_identity,
                sequence=self._sequence,
                prompt_digest=content_digest({"prompt": prompt_value}),
                predecessor_receipt_digest=self._predecessor,
                spent_microusd=self._accounted_cost_microusd,
            )
            self._active = authorization
            self._consumed = False
            return authorization

    def consume(
        self,
        plan: HostedStagePlan,
        authorization: StageAuthorization,
        *,
        prompt: str,
    ) -> None:
        with self._lock:
            if type(authorization) is not StageAuthorization:
                raise HostedPhase2Error("authorization_invalid")
            if self._active is None or authorization != self._active:
                raise HostedPhase2Error("authorization_not_issued_by_run")
            if self._consumed:
                raise HostedPhase2Error("authorization_already_consumed")
            if authorization.run_identity != self.run_identity:
                raise HostedPhase2Error("authorization_run_mismatch")
            if authorization.sequence != self._sequence:
                raise HostedPhase2Error("authorization_sequence_mismatch")
            if authorization.plan_digest != plan.plan_digest:
                raise HostedPhase2Error("authorization_plan_mismatch")
            if authorization.policy_digest != self.policy.policy_digest:
                raise HostedPhase2Error("authorization_policy_mismatch")
            if authorization.prompt_digest != content_digest({"prompt": prompt}):
                raise HostedPhase2Error("authorization_prompt_mismatch")
            expected = authorize_stage(
                plan,
                self.policy,
                owner_decision=OWNER_DECISION,
                run_identity=self.run_identity,
                sequence=self._sequence,
                prompt_digest=authorization.prompt_digest,
                predecessor_receipt_digest=self._predecessor,
                spent_microusd=self._accounted_cost_microusd,
            )
            if authorization != expected:
                raise HostedPhase2Error("authorization_lease_mismatch")
            self._consumed = True

    def settle(
        self,
        authorization: StageAuthorization,
        *,
        receipt: HostedStageReceipt,
    ) -> None:
        with self._lock:
            if self._active != authorization or not self._consumed:
                raise HostedPhase2Error("authorization_not_consumed")
            if type(receipt) is not HostedStageReceipt:
                raise HostedPhase2Error("settlement_receipt_invalid")
            if (
                receipt.stage != authorization.stage
                or receipt.task_id != authorization.task_id
                or receipt.plan_digest != authorization.plan_digest
                or receipt.policy_digest != authorization.policy_digest
            ):
                raise HostedPhase2Error("settlement_receipt_identity_mismatch")
            actual = receipt.actual_cost_microusd
            if actual > authorization.reserved_cost_microusd:
                raise HostedPhase2Error("actual_cost_exceeds_reservation")
            new_total = self._accounted_cost_microusd + actual
            if new_total > self.policy.total_budget_microusd:
                raise HostedPhase2Error("hosted_budget_exceeded")
            if receipt.cumulative_cost_microusd != new_total:
                raise HostedPhase2Error("settlement_cumulative_cost_mismatch")
            self._accounted_cost_microusd = new_total
            self._predecessor = receipt.receipt_digest
            self._sequence += 1
            self._active = None
            self._consumed = False

    def block(self, authorization: StageAuthorization) -> int:
        """Close the run and conservatively account the active reservation."""

        with self._lock:
            if self._active != authorization:
                raise HostedPhase2Error("authorization_not_issued_by_run")
            total = self._accounted_cost_microusd + authorization.reserved_cost_microusd
            if total > self.policy.total_budget_microusd:
                raise HostedPhase2Error("hosted_budget_exceeded")
            self._accounted_cost_microusd = total
            self._blocked = True
            self._active = None
            self._consumed = False
            return total


class DurableRunClaim:
    """Cross-process, single-use claim for one Owner-approved hosted scope."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        approval_scope_digest: str,
        run_identity: str,
    ) -> None:
        self._state_dir = Path(state_dir).resolve()
        self.approval_scope_digest = _digest(
            approval_scope_digest,
            "approval_scope_digest",
        )
        self.run_identity = _digest(run_identity, "run_identity")
        self._path = self._state_dir / f"{self.approval_scope_digest}.json"
        self._claimed = False

    @property
    def claimed(self) -> bool:
        return self._claimed

    def claim(self) -> None:
        if self._claimed:
            return
        self._state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self._state_dir.chmod(0o700)
        except OSError as exc:
            raise HostedPhase2Error("hosted_claim_directory_unusable") from exc
        body = {
            "schema_version": f"{SCHEMA_VERSION}.durable-run-claim.v1",
            "approval_scope_digest": self.approval_scope_digest,
            "run_identity": self.run_identity,
            "owner_decision": OWNER_DECISION,
            "status": "CLAIMED",
        }
        payload = (canonical_json(body) + "\n").encode("utf-8")
        try:
            descriptor = os.open(
                self._path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise HostedPhase2Error("hosted_approval_already_consumed") from exc
        except OSError as exc:
            raise HostedPhase2Error("hosted_claim_unavailable") from exc
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            directory_descriptor = os.open(self._state_dir, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as exc:
            raise HostedPhase2Error("hosted_claim_directory_sync_failed") from exc
        self._claimed = True


@dataclass(frozen=True, slots=True)
class HostedStageObservation:
    """Private in-memory result; callers must persist only its evaluated receipt."""

    stage: str
    plan_digest: str
    output: Mapping[str, Any]
    requests: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_calls: tuple[str, ...]
    last_agent: str
    handoff_count: int

    def __post_init__(self) -> None:
        if self.stage not in _STAGE_POLICY:
            raise HostedPhase2Error("stage_not_authorized")
        _digest(self.plan_digest, "plan_digest")
        if not isinstance(self.output, Mapping):
            raise HostedPhase2Error("output_schema_invalid")
        _positive_int(self.requests, "requests")
        _nonnegative_int(self.input_tokens, "input_tokens")
        _nonnegative_int(self.output_tokens, "output_tokens")
        _nonnegative_int(self.latency_ms, "latency_ms")
        object.__setattr__(self, "tool_calls", _strings(self.tool_calls, "tool_calls"))
        _text(self.last_agent, "last_agent")
        _nonnegative_int(self.handoff_count, "handoff_count")


@dataclass(frozen=True, slots=True)
class HostedStageReceipt:
    stage: str
    task_id: str
    plan_digest: str
    policy_digest: str
    output_digest: str
    requests: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_call_count: int
    last_agent: str
    handoff_count: int
    actual_cost_microusd: int
    cumulative_cost_microusd: int
    verdict: str = "PASS"

    def __post_init__(self) -> None:
        if self.stage not in _STAGE_POLICY:
            raise HostedPhase2Error("stage_not_authorized")
        _text(self.task_id, "task_id")
        _digest(self.plan_digest, "plan_digest")
        _digest(self.policy_digest, "policy_digest")
        _digest(self.output_digest, "output_digest")
        _positive_int(self.requests, "requests")
        _nonnegative_int(self.input_tokens, "input_tokens")
        _nonnegative_int(self.output_tokens, "output_tokens")
        _nonnegative_int(self.latency_ms, "latency_ms")
        _nonnegative_int(self.tool_call_count, "tool_call_count")
        _text(self.last_agent, "last_agent")
        _nonnegative_int(self.handoff_count, "handoff_count")
        _nonnegative_int(self.actual_cost_microusd, "actual_cost_microusd")
        _nonnegative_int(self.cumulative_cost_microusd, "cumulative_cost_microusd")
        expected_tools, route = _STAGE_POLICY[self.stage]
        if self.tool_call_count != len(expected_tools):
            raise HostedPhase2Error("receipt_tool_count_invalid")
        expected_agent = route[-1] if route else "architecture"
        if self.last_agent != expected_agent:
            raise HostedPhase2Error("receipt_last_agent_invalid")
        if self.handoff_count != max(0, len(route) - 1):
            raise HostedPhase2Error("receipt_handoff_count_invalid")
        if self.actual_cost_microusd != estimate_cost_microusd(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        ):
            raise HostedPhase2Error("receipt_cost_invalid")
        if self.cumulative_cost_microusd < self.actual_cost_microusd:
            raise HostedPhase2Error("receipt_cumulative_cost_invalid")
        if self.verdict != "PASS":
            raise HostedPhase2Error("receipt_verdict_invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "task_id": self.task_id,
            "plan_digest": self.plan_digest,
            "policy_digest": self.policy_digest,
            "output_digest": self.output_digest,
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "tool_call_count": self.tool_call_count,
            "last_agent": self.last_agent,
            "handoff_count": self.handoff_count,
            "actual_cost_microusd": self.actual_cost_microusd,
            "cumulative_cost_microusd": self.cumulative_cost_microusd,
            "verdict": self.verdict,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}


def evaluate_stage(
    observation: HostedStageObservation,
    plan: HostedStagePlan,
    policy: HostedPhase2Policy,
    *,
    spent_microusd: int,
) -> HostedStageReceipt:
    _nonnegative_int(spent_microusd, "spent_microusd")
    if observation.stage != plan.stage or observation.plan_digest != plan.plan_digest:
        raise HostedPhase2Error("observation_plan_mismatch")
    _validate_stage_output(plan.stage, observation.output)
    serialized = canonical_json(observation.output).lower()
    if any(marker in serialized for marker in _SENSITIVE_MARKERS):
        raise HostedPhase2Error("sensitive_output_detected")
    stage_requests = _STAGE_REQUEST_MULTIPLIER[plan.stage]
    if observation.requests > stage_requests:
        raise HostedPhase2Error("request_count_exceeds_plan")
    if observation.input_tokens > plan.max_input_chars * stage_requests:
        raise HostedPhase2Error("input_tokens_exceed_plan")
    if observation.output_tokens > plan.max_output_tokens * stage_requests:
        raise HostedPhase2Error("output_tokens_exceed_plan")
    if observation.latency_ms > plan.timeout_seconds * 1_000:
        raise HostedPhase2Error("timeout_exceeded")
    expected_tools, expected_route = _STAGE_POLICY[plan.stage]
    if observation.tool_calls != expected_tools:
        reason = (
            "unexpected_tool_call"
            if not expected_tools
            else "required_tool_call_mismatch"
        )
        raise HostedPhase2Error(reason)
    expected_last_agent = expected_route[-1] if expected_route else "architecture"
    expected_handoffs = max(0, len(expected_route) - 1)
    if observation.handoff_count != expected_handoffs:
        reason = (
            "unexpected_handoff" if expected_handoffs == 0 else "handoff_count_mismatch"
        )
        raise HostedPhase2Error(reason)
    if observation.last_agent != expected_last_agent:
        raise HostedPhase2Error("last_agent_mismatch")
    actual_cost = estimate_cost_microusd(
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
    )
    cumulative = spent_microusd + actual_cost
    if cumulative > policy.total_budget_microusd:
        raise HostedPhase2Error("hosted_budget_exceeded")
    return HostedStageReceipt(
        stage=plan.stage,
        task_id=plan.task_id,
        plan_digest=plan.plan_digest,
        policy_digest=policy.policy_digest,
        output_digest=content_digest(dict(observation.output)),
        requests=observation.requests,
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
        latency_ms=observation.latency_ms,
        tool_call_count=len(observation.tool_calls),
        last_agent=observation.last_agent,
        handoff_count=observation.handoff_count,
        actual_cost_microusd=actual_cost,
        cumulative_cost_microusd=cumulative,
    )


@dataclass(frozen=True, slots=True)
class LocalSourceLookup:
    """Immutable allowlisted UTF-8 source snapshot used by one read-only tool."""

    _root: Path
    _max_chars: int
    _allowed_paths: tuple[str, ...]
    _content: Mapping[str, str]
    _capability_digest: str
    _calls: list[str]

    def __init__(
        self,
        root: str | Path,
        *,
        allowed_paths: Sequence[str],
        max_chars: int,
        snapshot_contents: Mapping[str, str] | None = None,
    ) -> None:
        resolved_root = Path(root).resolve()
        checked_max_chars = _positive_int(max_chars, "max_chars")
        normalized = tuple(self._normalize(path) for path in allowed_paths)
        if not normalized or len(set(normalized)) != len(normalized):
            raise HostedPhase2Error("allowed_source_paths_invalid")
        supplied = None if snapshot_contents is None else dict(snapshot_contents)
        if supplied is not None and set(supplied) != set(normalized):
            raise HostedPhase2Error("source_snapshot_paths_invalid")
        content: dict[str, str] = {}
        for relative_path in normalized:
            if supplied is None:
                candidate = (resolved_root / relative_path).resolve()
                try:
                    candidate.relative_to(resolved_root)
                except ValueError as exc:
                    raise HostedPhase2Error("source_path_not_allowed") from exc
                if not candidate.is_file():
                    raise HostedPhase2Error("source_path_not_allowed")
                try:
                    value = candidate.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise HostedPhase2Error("source_content_unreadable") from exc
            else:
                value = supplied[relative_path]
            if not isinstance(value, str):
                raise HostedPhase2Error("source_content_unreadable")
            if len(value) > checked_max_chars:
                raise HostedPhase2Error("source_content_exceeds_limit")
            content[relative_path] = value
        capability_digest = content_digest(
            {
                "allowed_sources": [
                    {
                        "path": path,
                        "content_digest": content_digest({"content": content[path]}),
                    }
                    for path in normalized
                ],
                "max_chars": checked_max_chars,
            }
        )
        object.__setattr__(self, "_root", resolved_root)
        object.__setattr__(self, "_max_chars", checked_max_chars)
        object.__setattr__(self, "_allowed_paths", normalized)
        object.__setattr__(self, "_content", MappingProxyType(content))
        object.__setattr__(self, "_capability_digest", capability_digest)
        object.__setattr__(self, "_calls", [])

    @staticmethod
    def _normalize(value: str) -> str:
        path = PurePosixPath(_text(value, "source_path"))
        if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
            raise HostedPhase2Error("source_path_not_allowed")
        return str(path)

    @property
    def calls(self) -> tuple[str, ...]:
        return tuple(self._calls)

    @property
    def allowed_paths(self) -> tuple[str, ...]:
        return self._allowed_paths

    @property
    def capability_digest(self) -> str:
        return self._capability_digest

    def lookup(self, relative_path: str) -> str:
        normalized = self._normalize(relative_path)
        if normalized not in self._allowed_paths:
            raise HostedPhase2Error("source_path_not_allowed")
        self._calls.append(normalized)
        return self._content[normalized]


@dataclass(frozen=True, slots=True)
class RoleReceipt:
    role: str
    task_id: str
    source_identity: str
    context_digest: str
    agent_graph_identity: str
    model: str
    authorization_digest: str
    input_digest: str
    output_digest: str
    verdict: str

    def __post_init__(self) -> None:
        if self.role not in _ROLE_ORDER:
            raise HostedPhase2Error("role_not_authorized")
        _text(self.task_id, "task_id")
        _digest(self.source_identity, "source_identity")
        _digest(self.context_digest, "context_digest")
        _digest(self.agent_graph_identity, "agent_graph_identity")
        if self.model != MODEL_ID:
            raise HostedPhase2Error("model_not_authorized")
        _digest(self.authorization_digest, "authorization_digest")
        _digest(self.input_digest, "input_digest")
        _digest(self.output_digest, "output_digest")
        if self.verdict != "PASS":
            raise HostedPhase2Error("role_verdict_not_pass")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "role": self.role,
            "task_id": self.task_id,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "agent_graph_identity": self.agent_graph_identity,
            "model": self.model,
            "authorization_digest": self.authorization_digest,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "verdict": self.verdict,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class Phase2HandoffReceipt:
    task_id: str
    source_identity: str
    context_digest: str
    agent_graph_identity: str
    model: str
    authorization_digest: str
    from_role: str
    to_role: str
    producer_receipt_digest: str
    consumer_receipt_digest: str
    accepted: bool

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _digest(self.source_identity, "source_identity")
        _digest(self.context_digest, "context_digest")
        _digest(self.agent_graph_identity, "agent_graph_identity")
        if self.model != MODEL_ID:
            raise HostedPhase2Error("model_not_authorized")
        _digest(self.authorization_digest, "authorization_digest")
        if self.from_role != "architecture" or self.to_role != "test":
            raise HostedPhase2Error("handoff_topology_invalid")
        _digest(self.producer_receipt_digest, "producer_receipt_digest")
        _digest(self.consumer_receipt_digest, "consumer_receipt_digest")
        if self.accepted is not True:
            raise HostedPhase2Error("handoff_not_accepted")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "agent_graph_identity": self.agent_graph_identity,
            "model": self.model,
            "authorization_digest": self.authorization_digest,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "producer_receipt_digest": self.producer_receipt_digest,
            "consumer_receipt_digest": self.consumer_receipt_digest,
            "accepted": self.accepted,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}


def derive_handoff_receipt(
    architecture: RoleReceipt,
    test: RoleReceipt,
) -> Phase2HandoffReceipt:
    if architecture.role != "architecture" or test.role != "test":
        raise HostedPhase2Error("handoff_topology_invalid")
    if (
        architecture.task_id != test.task_id
        or architecture.source_identity != test.source_identity
        or architecture.context_digest != test.context_digest
        or architecture.agent_graph_identity != test.agent_graph_identity
        or architecture.model != test.model
        or architecture.authorization_digest != test.authorization_digest
    ):
        raise HostedPhase2Error("handoff_identity_mismatch")
    if test.input_digest != architecture.output_digest:
        raise HostedPhase2Error("handoff_input_mismatch")
    return Phase2HandoffReceipt(
        task_id=architecture.task_id,
        source_identity=architecture.source_identity,
        context_digest=architecture.context_digest,
        agent_graph_identity=architecture.agent_graph_identity,
        model=architecture.model,
        authorization_digest=architecture.authorization_digest,
        from_role="architecture",
        to_role="test",
        producer_receipt_digest=architecture.receipt_digest,
        consumer_receipt_digest=test.receipt_digest,
        accepted=True,
    )


@dataclass(frozen=True, slots=True)
class DevelopmentLoopReceipt:
    task_id: str
    source_identity: str
    context_digest: str
    agent_graph_identity: str
    model: str
    authorization_digest: str
    roles: tuple[str, ...]
    role_receipt_digests: tuple[str, ...]
    final_output_digest: str
    verdict: str = "PASS"

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _digest(self.source_identity, "source_identity")
        _digest(self.context_digest, "context_digest")
        _digest(self.agent_graph_identity, "agent_graph_identity")
        if self.model != MODEL_ID:
            raise HostedPhase2Error("model_not_authorized")
        _digest(self.authorization_digest, "authorization_digest")
        object.__setattr__(self, "roles", _strings(self.roles, "roles"))
        if self.roles != _ROLE_ORDER:
            raise HostedPhase2Error("development_loop_topology_invalid")
        digests = tuple(
            _digest(value, "role_receipt_digest") for value in self.role_receipt_digests
        )
        object.__setattr__(self, "role_receipt_digests", digests)
        if len(digests) != len(_ROLE_ORDER):
            raise HostedPhase2Error("development_loop_receipts_invalid")
        _digest(self.final_output_digest, "final_output_digest")
        if self.verdict != "PASS":
            raise HostedPhase2Error("development_loop_verdict_invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "agent_graph_identity": self.agent_graph_identity,
            "model": self.model,
            "authorization_digest": self.authorization_digest,
            "roles": list(self.roles),
            "role_receipt_digests": list(self.role_receipt_digests),
            "final_output_digest": self.final_output_digest,
            "verdict": self.verdict,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}


def derive_development_loop_receipt(
    receipts: Sequence[RoleReceipt],
) -> DevelopmentLoopReceipt:
    rows = tuple(receipts)
    if tuple(receipt.role for receipt in rows) != _ROLE_ORDER:
        raise HostedPhase2Error("development_loop_topology_invalid")
    first = rows[0]
    if any(
        receipt.task_id != first.task_id
        or receipt.source_identity != first.source_identity
        or receipt.context_digest != first.context_digest
        or receipt.agent_graph_identity != first.agent_graph_identity
        or receipt.model != first.model
        or receipt.authorization_digest != first.authorization_digest
        for receipt in rows[1:]
    ):
        raise HostedPhase2Error("development_loop_identity_invalid")
    if any(
        current.input_digest != previous.output_digest
        for previous, current in pairwise(rows)
    ):
        raise HostedPhase2Error("development_loop_lineage_invalid")
    return DevelopmentLoopReceipt(
        task_id=first.task_id,
        source_identity=first.source_identity,
        context_digest=first.context_digest,
        agent_graph_identity=first.agent_graph_identity,
        model=first.model,
        authorization_digest=first.authorization_digest,
        roles=_ROLE_ORDER,
        role_receipt_digests=tuple(receipt.receipt_digest for receipt in rows),
        final_output_digest=rows[-1].output_digest,
    )
