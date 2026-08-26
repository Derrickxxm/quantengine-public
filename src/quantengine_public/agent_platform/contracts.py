from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping


SCHEMA_VERSION = "quantengine_public.agent_platform.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when a closed platform contract is malformed."""


class StaleContextError(ContractError):
    """Raised when an input no longer describes the accepted source."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name}_required")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContractError(f"{name}_invalid")
    return value


def _sequence(values: Any, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ContractError(f"{name}_must_be_sequence")
    return tuple(_text(item, name) for item in values)


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    repository: str
    branch: str
    commit: str
    tree_digest: str
    dirty: bool = False

    def __post_init__(self) -> None:
        _text(self.repository, "repository")
        _text(self.branch, "branch")
        if not isinstance(self.commit, str) or not re.fullmatch(r"[0-9a-f]{40}", self.commit):
            raise ContractError("commit_invalid")
        _digest(self.tree_digest, "tree_digest")
        if not isinstance(self.dirty, bool):
            raise ContractError("dirty_invalid")

    @property
    def identity_digest(self) -> str:
        return content_digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "repository": self.repository,
            "branch": self.branch,
            "commit": self.commit,
            "tree_digest": self.tree_digest,
            "dirty": self.dirty,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "identity_digest": self.identity_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceIdentity:
        data = dict(value)
        supplied = data.pop("identity_digest", None)
        data.pop("schema_version", None)
        result = cls(**data)
        if supplied is not None and supplied != result.identity_digest:
            raise ContractError("identity_digest_mismatch")
        return result


@dataclass(frozen=True, slots=True)
class GraphIdentity:
    revision: str
    source_commit: str
    graph_digest: str

    def __post_init__(self) -> None:
        _text(self.revision, "graph_revision")
        if not isinstance(self.source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", self.source_commit):
            raise ContractError("graph_source_commit_invalid")
        _digest(self.graph_digest, "graph_digest")

    @property
    def identity_digest(self) -> str:
        return content_digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": self.revision,
            "source_commit": self.source_commit,
            "graph_digest": self.graph_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "identity_digest": self.identity_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GraphIdentity:
        data = dict(value)
        supplied = data.pop("identity_digest", None)
        data.pop("schema_version", None)
        result = cls(**data)
        if supplied is not None and supplied != result.identity_digest:
            raise ContractError("identity_digest_mismatch")
        return result


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_id: str
    task_revision: str
    objective: str
    measures: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    non_goals: tuple[str, ...]
    approved_scope: tuple[str, ...]
    required_approvals: tuple[str, ...]
    source_reference: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _text(self.task_revision, "task_revision")
        _text(self.objective, "objective")
        for field_name in ("measures", "acceptance_criteria", "non_goals", "approved_scope", "required_approvals"):
            values = _sequence(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
        _text(self.source_reference, "source_reference")
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("schema_version_mismatch")

    @property
    def snapshot_digest(self) -> str:
        return content_digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "objective": self.objective,
            "measures": list(self.measures),
            "acceptance_criteria": list(self.acceptance_criteria),
            "non_goals": list(self.non_goals),
            "approved_scope": list(self.approved_scope),
            "required_approvals": list(self.required_approvals),
            "source_reference": self.source_reference,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "snapshot_digest": self.snapshot_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TaskSnapshot:
        data = dict(value)
        supplied = data.pop("snapshot_digest", None)
        result = cls(**data)
        if supplied is not None and supplied != result.snapshot_digest:
            raise ContractError("snapshot_digest_mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_type: str
    artifact_digest: str

    def __post_init__(self) -> None:
        _text(self.artifact_type, "artifact_type")
        _digest(self.artifact_digest, "artifact_digest")

    def to_dict(self) -> dict[str, str]:
        return {"artifact_type": self.artifact_type, "artifact_digest": self.artifact_digest}


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    task_id: str
    task_revision: str
    role: str
    source_identity: str
    graph_identity: str | None
    skill_identity: str
    tool_policy_identity: str
    upstream_artifact_refs: tuple[ArtifactRef, ...] = ()
    selected_context_refs: tuple[tuple[str, str, str], ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _text(self.task_revision, "task_revision")
        _text(self.role, "role")
        _digest(self.source_identity, "source_identity")
        if self.graph_identity is not None:
            _digest(self.graph_identity, "graph_identity")
        _text(self.skill_identity, "skill_identity")
        _text(self.tool_policy_identity, "tool_policy_identity")
        refs = tuple(self.upstream_artifact_refs)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise ContractError("upstream_artifact_ref_invalid")
        object.__setattr__(self, "upstream_artifact_refs", refs)
        refs: list[tuple[str, str, str]] = []
        for ref in self.selected_context_refs:
            if not isinstance(ref, (list, tuple)) or len(ref) != 3 or not all(isinstance(item, str) and item for item in ref):
                raise ContractError("selected_context_ref_invalid")
            refs.append((ref[0], ref[1], ref[2]))
        object.__setattr__(self, "selected_context_refs", tuple(refs))
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("schema_version_mismatch")

    @property
    def context_digest(self) -> str:
        return content_digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "role": self.role,
            "source_identity": self.source_identity,
            "graph_identity": self.graph_identity,
            "skill_identity": self.skill_identity,
            "tool_policy_identity": self.tool_policy_identity,
            "upstream_artifact_refs": [ref.to_dict() for ref in self.upstream_artifact_refs],
            "selected_context_refs": [list(ref) for ref in self.selected_context_refs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "context_digest": self.context_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ContextSnapshot:
        data = dict(value)
        supplied = data.pop("context_digest", None)
        data["upstream_artifact_refs"] = tuple(ArtifactRef(**ref) for ref in data.get("upstream_artifact_refs", ()))
        result = cls(**data)
        if supplied is not None and supplied != result.context_digest:
            raise ContractError("context_digest_mismatch")
        return result


@dataclass(frozen=True, slots=True)
class RunRequest:
    run_id: str
    task_id: str
    expected_task_version: int
    role: str
    collaboration_mode: str
    context_digest: str
    skill_identity: str
    allowed_tool_policy: str
    required_output_type: str
    upstream_artifact_refs: tuple[ArtifactRef, ...]
    timeout_policy: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for name in ("run_id", "task_id", "role", "collaboration_mode", "skill_identity", "allowed_tool_policy", "required_output_type", "timeout_policy", "idempotency_key"):
            _text(getattr(self, name), name)
        if not isinstance(self.expected_task_version, int) or self.expected_task_version < 0:
            raise ContractError("expected_task_version_invalid")
        _digest(self.context_digest, "context_digest")
        refs = tuple(self.upstream_artifact_refs)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise ContractError("upstream_artifact_ref_invalid")
        object.__setattr__(self, "upstream_artifact_refs", refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "expected_task_version": self.expected_task_version,
            "role": self.role,
            "collaboration_mode": self.collaboration_mode,
            "context_digest": self.context_digest,
            "skill_identity": self.skill_identity,
            "allowed_tool_policy": self.allowed_tool_policy,
            "required_output_type": self.required_output_type,
            "upstream_artifact_refs": [ref.to_dict() for ref in self.upstream_artifact_refs],
            "timeout_policy": self.timeout_policy,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    status: str
    stop_reason: str
    result_digest: str
    tool_call_refs: tuple[str, ...] = ()
    requested_next_action: str | None = None

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _text(self.status, "status")
        _text(self.stop_reason, "stop_reason")
        _digest(self.result_digest, "result_digest")
        object.__setattr__(self, "tool_call_refs", _sequence(self.tool_call_refs, "tool_call_ref"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "result_digest": self.result_digest,
            "tool_call_refs": list(self.tool_call_refs),
            "requested_next_action": self.requested_next_action,
        }


@dataclass(frozen=True, slots=True)
class HandoffReceipt:
    task_id: str
    task_version: int
    from_owner: str
    to_role: str
    source_identity: str
    context_digest: str
    required_artifact_refs: tuple[ArtifactRef, ...]
    accepted_or_rejected: str
    reason: str
    next_owner: str
    schema_version: str = SCHEMA_VERSION
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        if not isinstance(self.task_version, int) or self.task_version < 0:
            raise ContractError("task_version_invalid")
        for name in ("from_owner", "to_role", "accepted_or_rejected", "reason", "next_owner"):
            _text(getattr(self, name), name)
        if self.accepted_or_rejected not in {"accepted", "rejected"}:
            raise ContractError("handoff_decision_invalid")
        _digest(self.source_identity, "source_identity")
        _digest(self.context_digest, "context_digest")
        refs = tuple(self.required_artifact_refs)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise ContractError("handoff_artifact_ref_invalid")
        object.__setattr__(self, "required_artifact_refs", refs)
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("schema_version_mismatch")
        object.__setattr__(self, "receipt_digest", content_digest(self._body()))

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "task_version": self.task_version,
            "from_owner": self.from_owner,
            "to_role": self.to_role,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "required_artifact_refs": [ref.to_dict() for ref in self.required_artifact_refs],
            "accepted_or_rejected": self.accepted_or_rejected,
            "reason": self.reason,
            "next_owner": self.next_owner,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HandoffReceipt:
        data = dict(value)
        supplied = data.pop("receipt_digest", None)
        data["required_artifact_refs"] = tuple(ArtifactRef(**ref) for ref in data.get("required_artifact_refs", ()))
        result = cls(**data)
        if supplied is not None and supplied != result.receipt_digest:
            raise ContractError("receipt_digest_mismatch")
        return result


def validate_handoff_receipt(
    receipt: HandoffReceipt,
    *,
    task: TaskSnapshot,
    source: SourceIdentity,
    context: ContextSnapshot,
    expected_task_version: int | None = None,
) -> None:
    """Check every cross-run identity before a receiver accepts ownership."""
    if receipt.task_id != task.task_id:
        raise ContractError("handoff_task_mismatch")
    if expected_task_version is not None and receipt.task_version != expected_task_version:
        raise ContractError("handoff_task_version_mismatch")
    if task.source_reference != source.identity_digest or receipt.source_identity != source.identity_digest:
        raise StaleContextError("handoff_source_identity_mismatch")
    if context.task_id != task.task_id or context.task_revision != task.task_revision:
        raise ContractError("handoff_context_task_mismatch")
    if receipt.context_digest != context.context_digest:
        raise StaleContextError("handoff_context_mismatch")
    if receipt.from_owner == receipt.to_role:
        raise ContractError("handoff_owner_binding_invalid")
    if receipt.accepted_or_rejected == "accepted" and receipt.next_owner != receipt.to_role:
        raise ContractError("handoff_next_owner_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceAdmission:
    task_id: str
    source_identity: str
    context_digest: str
    artifact_type: str
    producer: str
    status: str
    upstream: tuple[ArtifactRef, ...]
    authority: dict[str, bool] = field(default_factory=lambda: {"deployment_allowed": False, "paper_allowed": False, "real_allowed": False})
    admission_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _digest(self.source_identity, "source_identity")
        _digest(self.context_digest, "context_digest")
        for name in ("artifact_type", "producer", "status"):
            _text(getattr(self, name), name)
        refs = tuple(self.upstream)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise EvidenceAdmissionError("upstream_artifact_ref_invalid")
        object.__setattr__(self, "upstream", refs)
        if set(self.authority) != {"deployment_allowed", "paper_allowed", "real_allowed"} or any(not isinstance(value, bool) for value in self.authority.values()):
            raise EvidenceAdmissionError("authority_invalid")
        if any(self.authority.values()):
            raise EvidenceAdmissionError("authority_cannot_be_granted_by_admission")
        object.__setattr__(self, "admission_digest", content_digest(self._body()))

    def _body(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "artifact_type": self.artifact_type,
            "producer": self.producer,
            "status": self.status,
            "upstream": [ref.to_dict() for ref in self.upstream],
            "authority": dict(self.authority),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "admission_digest": self.admission_digest}


class EvidenceAdmissionError(ContractError):
    pass


def admit_evidence(*, task: TaskSnapshot, source: SourceIdentity, context: ContextSnapshot, artifact_type: str, producer: str, status: str, upstream: tuple[ArtifactRef, ...] = (), authority: dict[str, bool] | None = None) -> EvidenceAdmission:
    if task.source_reference != source.identity_digest:
        raise EvidenceAdmissionError("source_identity_mismatch")
    if context.task_id != task.task_id or context.task_revision != task.task_revision:
        raise EvidenceAdmissionError("context_task_mismatch")
    if context.source_identity != source.identity_digest:
        raise EvidenceAdmissionError("context_source_mismatch")
    return EvidenceAdmission(
        task_id=task.task_id,
        source_identity=source.identity_digest,
        context_digest=context.context_digest,
        artifact_type=artifact_type,
        producer=producer,
        status=status,
        upstream=upstream,
        authority=authority or {"deployment_allowed": False, "paper_allowed": False, "real_allowed": False},
    )
