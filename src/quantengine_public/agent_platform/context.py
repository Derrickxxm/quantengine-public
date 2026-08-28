from __future__ import annotations

from .contracts import (
    ContextSnapshot,
    GraphIdentity,
    SourceIdentity,
    StaleContextError,
    TaskSnapshot,
)
from .tool_policy import ToolPolicy


def build_context_snapshot(
    *,
    task: TaskSnapshot,
    source: SourceIdentity,
    graph: GraphIdentity | None,
    role: str,
    skill_identity: str,
    tool_policy_identity: str,
    upstream_artifact_refs=(),
    selected_context_refs=(),
) -> ContextSnapshot:
    if task.source_reference != source.identity_digest:
        raise StaleContextError("source_revision_mismatch")
    if graph is not None and graph.source_commit != source.commit:
        raise StaleContextError("graph_source_mismatch")
    try:
        expected_policy = ToolPolicy.for_role(role)
    except ValueError as exc:
        raise StaleContextError("role_invalid") from exc
    if tool_policy_identity != expected_policy.policy_digest:
        raise StaleContextError("tool_policy_mismatch")
    return ContextSnapshot(
        task_id=task.task_id,
        task_revision=task.task_revision,
        role=role,
        source_identity=source.identity_digest,
        graph_identity=graph.identity_digest if graph else None,
        skill_identity=skill_identity,
        tool_policy_identity=tool_policy_identity,
        objective_contract_digest=task.objective_contract_digest,
        upstream_artifact_refs=tuple(upstream_artifact_refs),
        selected_context_refs=tuple(selected_context_refs),
    )


def validate_context(
    context: ContextSnapshot,
    source: SourceIdentity,
    graph: GraphIdentity | None,
    *,
    task: TaskSnapshot,
    expected_role: str | None = None,
    expected_skill_identity: str | None = None,
    expected_tool_policy_identity: str | None = None,
) -> None:
    if context.task_id != task.task_id or context.task_revision != task.task_revision:
        raise StaleContextError("task_revision_mismatch")
    if context.source_identity != source.identity_digest:
        raise StaleContextError("source_revision_mismatch")
    if task.objective_contract_digest is not None and context.objective_contract_digest != task.objective_contract_digest:
        raise StaleContextError("objective_contract_digest_mismatch")
    role = expected_role if expected_role is not None else context.role
    if context.role != role:
        raise StaleContextError("role_mismatch")
    try:
        expected_policy = ToolPolicy.for_role(role)
    except ValueError as exc:
        raise StaleContextError("role_invalid") from exc
    policy_identity = (
        expected_tool_policy_identity
        if expected_tool_policy_identity is not None
        else expected_policy.policy_digest
    )
    if context.tool_policy_identity != policy_identity:
        raise StaleContextError("tool_policy_mismatch")
    if expected_skill_identity is not None and context.skill_identity != expected_skill_identity:
        raise StaleContextError("skill_identity_mismatch")
    if graph is None:
        if context.graph_identity is not None:
            raise StaleContextError("graph_revision_missing")
    elif graph.source_commit != source.commit:
        raise StaleContextError("graph_source_mismatch")
    elif context.graph_identity != graph.identity_digest:
        raise StaleContextError("graph_revision_mismatch")


__all__ = ["StaleContextError", "build_context_snapshot", "validate_context"]
