from __future__ import annotations

import sqlite3

import pytest

from quantengine_public.agent_platform.context import StaleContextError, build_context_snapshot
from quantengine_public.agent_platform.contracts import (
    ArtifactRef,
    GraphIdentity,
    HandoffReceipt,
    SourceIdentity,
    TaskSnapshot,
)
from quantengine_public.agent_platform.control_state import (
    ConcurrentTransitionError,
    ControlStateError,
    ControlStateStore,
)
from quantengine_public.agent_platform.tool_policy import ToolPolicy
from quantengine_public.delivery.identity import seal_artifact


def identities() -> tuple[TaskSnapshot, SourceIdentity, GraphIdentity]:
    source = SourceIdentity(
        repository="quantengine-public",
        branch="codex/evidence-gate",
        commit="a" * 40,
        tree_digest="b" * 64,
    )
    task = TaskSnapshot(
        task_id="TASKSYS-1261",
        task_revision="r1",
        objective="evidence-gated state",
        measures=("fail closed",),
        acceptance_criteria=("admitted refs",),
        non_goals=("runtime",),
        approved_scope=("control_state.py",),
        required_approvals=(),
        source_reference=source.identity_digest,
    )
    graph = GraphIdentity("graph-r1", source.commit, "c" * 64)
    return task, source, graph


def artifact(
    task: TaskSnapshot,
    source: SourceIdentity,
    graph: GraphIdentity,
    *,
    artifact_type: str,
    producer: str,
    status: str,
    context_digest: str,
    digest_override: str | None = None,
) -> dict[str, object]:
    result = seal_artifact(
        artifact_type=artifact_type,
        producer=producer,
        status=status,
        upstream=[],
        payload={
            "task_id": task.task_id,
            "source_identity": source.identity_digest,
            "context_digest": context_digest,
            "graph_identity": graph.identity_digest,
        },
    )
    if digest_override is not None:
        result["artifact_digest"] = digest_override
    return result


def setup(tmp_path):
    task, source, graph = identities()
    store = ControlStateStore(tmp_path / "control.sqlite3")
    store.create_task(task, source, owner="Owner")
    return store, task, source, graph


def move(store, task, source, next_state, *, owner="Owner", next_owner="Architecture", refs=()):
    current = store.get_task(task.task_id)
    return store.transition(
        task_id=task.task_id,
        expected_version=current.version,
        expected_state=current.state,
        next_state=next_state,
        owner=owner,
        source=source,
        reason=next_state.lower(),
        idempotency_key=f"{current.version}-{next_state}",
        next_owner=next_owner,
        evidence_refs=refs,
    )


def test_evidence_gate_requires_admitted_matching_delivery_artifact(tmp_path):
    store, task, source, graph = setup(tmp_path)
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://architecture@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    move(store, task, source, "ACCEPTED", next_owner="Owner")
    move(store, task, source, "CONTEXT_READY", next_owner="Owner")
    with pytest.raises(ControlStateError, match="evidence_required:ARCHITECTURE_READY"):
        move(store, task, source, "ARCHITECTURE_READY")

    wrong = artifact(
        task,
        source,
        graph,
        artifact_type="public_delivery.validation_plan",
        producer="public_test_agent",
        status="READY",
        context_digest=context.context_digest,
    )
    wrong_ref = store.admit_artifact(wrong)
    with pytest.raises(ControlStateError, match="evidence_type_mismatch"):
        move(store, task, source, "ARCHITECTURE_READY", refs=(wrong_ref,))

    good = artifact(
        task,
        source,
        graph,
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent",
        status="READY",
        context_digest=context.context_digest,
    )
    ref = store.admit_artifact(good)
    transition = move(store, task, source, "ARCHITECTURE_READY", refs=(ref,))
    assert transition.evidence_refs == (ref,)


def test_admission_rejects_tamper_source_context_and_authority(tmp_path):
    store, task, source, graph = setup(tmp_path)
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://architecture@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    tampered = artifact(
        task, source, graph,
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent", status="READY",
        context_digest=context.context_digest, digest_override="d" * 64,
    )
    with pytest.raises(ControlStateError, match="artifact_invalid"):
        store.admit_artifact(tampered)
    bad_source = seal_artifact(
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent",
        status="READY",
        upstream=[],
        payload={
            "task_id": task.task_id,
            "source_identity": "e" * 64,
            "context_digest": context.context_digest,
            "graph_identity": graph.identity_digest,
        },
    )
    with pytest.raises(StaleContextError, match="source_identity_mismatch"):
        store.admit_artifact(bad_source)


def test_handoff_is_atomic_owner_version_bound_and_rejected_cannot_take_over(tmp_path):
    store, task, source, graph = setup(tmp_path)
    context = build_context_snapshot(
        task=task, source=source, graph=graph, role="Architecture",
        skill_identity="skill://architecture@1", tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    evidence = artifact(
        task, source, graph,
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent", status="READY",
        context_digest=context.context_digest,
    )
    ref = store.admit_artifact(evidence)
    rejected = HandoffReceipt(
        task_id=task.task_id, task_version=0, from_owner="Owner", to_role="Development",
        source_identity=source.identity_digest, context_digest=context.context_digest,
        required_artifact_refs=(ref,), accepted_or_rejected="rejected",
        reason="not ready", next_owner="Development", graph_identity=graph.identity_digest,
    )
    store.record_handoff(rejected)
    with pytest.raises(ControlStateError, match="handoff_rejected"):
        store.accept_handoff(rejected)

    receipt = HandoffReceipt(
        task_id=task.task_id, task_version=0, from_owner="Owner", to_role="Architecture",
        source_identity=source.identity_digest, context_digest=context.context_digest,
        required_artifact_refs=(ref,), accepted_or_rejected="accepted",
        reason="architecture evidence", next_owner="Architecture", graph_identity=graph.identity_digest,
    )
    store.record_handoff(receipt)
    accepted = store.accept_handoff(receipt)
    assert accepted.receipt_digest == receipt.receipt_digest
    assert accepted.graph_identity == graph.identity_digest
    assert store.get_task(task.task_id).owner == "Architecture"
    reopened = ControlStateStore(store.path)
    assert reopened.get_task(task.task_id).owner == "Architecture"
    assert reopened._db.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 2


def test_transition_cas_rowcount_and_evidence_index_survive_reopen(tmp_path):
    store, task, source, graph = setup(tmp_path)
    context = build_context_snapshot(
        task=task, source=source, graph=graph, role="Architecture",
        skill_identity="skill://architecture@1", tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    good = artifact(
        task, source, graph,
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent", status="READY",
        context_digest=context.context_digest,
    )
    ref = store.admit_artifact(good)
    move(store, task, source, "ACCEPTED", next_owner="Owner")
    move(store, task, source, "CONTEXT_READY", next_owner="Owner")
    move(store, task, source, "ARCHITECTURE_READY", refs=(ref,))
    with pytest.raises(ConcurrentTransitionError):
        store.transition(
            task_id=task.task_id, expected_version=0, expected_state="DRAFT",
            next_state="ACCEPTED", owner="Owner", source=source, reason="stale",
            idempotency_key="stale", next_owner="Architecture",
        )
    reopened = ControlStateStore(store.path)
    assert reopened.get_task(task.task_id).state == "ARCHITECTURE_READY"
    assert reopened.list_admitted_artifacts(task.task_id)[0].artifact_digest == ref.artifact_digest
    tables = {row[0] for row in reopened._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"artifacts", "handoffs", "runs", "tool_calls", "approvals"}.issubset(tables)


def test_handoff_allows_historical_context_refs_but_binds_graph_and_current_context(tmp_path):
    store, task, source, graph = setup(tmp_path)
    current = build_context_snapshot(
        task=task, source=source, graph=graph, role="Architecture",
        skill_identity="skill://architecture@1", tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    historical = build_context_snapshot(
        task=task, source=source, graph=graph, role="Architecture",
        skill_identity="skill://owner-context@1", tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    current_ref = store.admit_artifact(artifact(
        task, source, graph, artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent", status="READY", context_digest=current.context_digest,
    ))
    historical_ref = store.admit_artifact(artifact(
        task, source, graph, artifact_type="public_delivery.ogsm",
        producer="owner_fixture", status="READY", context_digest=historical.context_digest,
    ))
    receipt = HandoffReceipt(
        task_id=task.task_id, task_version=0, from_owner="Owner", to_role="Architecture",
        source_identity=source.identity_digest, context_digest=current.context_digest,
        required_artifact_refs=(historical_ref, current_ref), accepted_or_rejected="accepted",
        reason="bound current evidence", next_owner="Architecture", graph_identity=graph.identity_digest,
    )
    store.record_handoff(receipt, graph_identity=graph.identity_digest)
    assert store.accept_handoff(receipt, graph_identity=graph.identity_digest).receipt_digest == receipt.receipt_digest

    other_graph = GraphIdentity("graph-r2", source.commit, "d" * 64)
    other_ref = store.admit_artifact(artifact(
        task, source, other_graph, artifact_type="public_delivery.validation_plan",
        producer="public_test_agent", status="READY", context_digest=current.context_digest,
    ))
    with pytest.raises(ControlStateError, match="handoff_graph_identity_mismatch"):
        store.record_handoff(HandoffReceipt(
            task_id=task.task_id, task_version=0, from_owner="Owner", to_role="Development",
            source_identity=source.identity_digest, context_digest=current.context_digest,
            required_artifact_refs=(current_ref, other_ref), accepted_or_rejected="rejected",
            reason="graph mismatch", next_owner="Development", graph_identity=graph.identity_digest,
        ))


def test_run_tool_and_approval_indexes_are_append_only(tmp_path):
    store, *_ = setup(tmp_path)
    store.record_run("run-1", task_id="TASKSYS-1261", status="completed")
    store.record_run("run-1", task_id="TASKSYS-1261", status="completed")
    with pytest.raises(ControlStateError, match="run_id_collision"):
        store.record_run("run-1", task_id="TASKSYS-1261", status="failed")
    store.record_tool_call("call-1", run_id="run-1", tool_id="read_source", status="allowed")
    store.record_approval("approval-1", task_id="TASKSYS-1261", run_id="run-1", owner="Owner", status="denied")
    assert store._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert store._db.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 1
    assert store._db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1
