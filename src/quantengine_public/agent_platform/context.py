from __future__ import annotations

from .contracts import (
    ContextSnapshot,
    GraphIdentity,
    SourceIdentity,
    StaleContextError,
    TaskSnapshot,
)


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
    return ContextSnapshot(
        task_id=task.task_id,
        task_revision=task.task_revision,
        role=role,
        source_identity=source.identity_digest,
        graph_identity=graph.identity_digest if graph else None,
        skill_identity=skill_identity,
        tool_policy_identity=tool_policy_identity,
        upstream_artifact_refs=tuple(upstream_artifact_refs),
        selected_context_refs=tuple(selected_context_refs),
    )


def validate_context(
    context: ContextSnapshot,
    source: SourceIdentity,
    graph: GraphIdentity | None,
) -> None:
    if context.source_identity != source.identity_digest:
        raise StaleContextError("source_revision_mismatch")
    if graph is None:
        if context.graph_identity is not None:
            raise StaleContextError("graph_revision_missing")
    elif graph.source_commit != source.commit:
        raise StaleContextError("graph_source_mismatch")
    elif context.graph_identity != graph.identity_digest:
        raise StaleContextError("graph_revision_mismatch")


__all__ = ["StaleContextError", "build_context_snapshot", "validate_context"]
