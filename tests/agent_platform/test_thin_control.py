from __future__ import annotations

import sqlite3

import pytest

from quantengine_public.agent_platform.context import (
    StaleContextError,
    build_context_snapshot,
    validate_context,
)
from quantengine_public.agent_platform.contracts import (
    ArtifactRef,
    ContextSnapshot,
    EvidenceAdmission,
    EvidenceAdmissionError,
    GraphIdentity,
    HandoffReceipt,
    SourceIdentity,
    TaskSnapshot,
    admit_evidence,
    validate_handoff_receipt,
)
from quantengine_public.agent_platform.control_state import (
    ConcurrentTransitionError,
    ControlStateStore,
    InvalidTransitionError,
)
from quantengine_public.agent_platform.tool_policy import (
    ToolCallReceipt,
    ToolDeniedError,
    ToolPolicy,
    record_tool_call,
)


def identities() -> tuple[TaskSnapshot, SourceIdentity, GraphIdentity]:
    source = SourceIdentity(
        repository="quantengine-public",
        branch="codex/test",
        commit="a" * 40,
        tree_digest="b" * 64,
        dirty=False,
    )
    task = TaskSnapshot(
        task_id="TASKSYS-1261",
        task_revision="r1",
        objective="implement thin control",
        measures=("resume", "fail closed"),
        acceptance_criteria=("identity bound",),
        non_goals=("runtime",),
        approved_scope=("src/quantengine_public/agent_platform",),
        required_approvals=(),
        source_reference=source.identity_digest,
    )
    graph = GraphIdentity(
        revision="graph-r1",
        source_commit=source.commit,
        graph_digest="c" * 64,
    )
    return task, source, graph


def test_contract_identities_are_canonical_and_context_is_revision_bound():
    task, source, graph = identities()
    assert task.snapshot_digest == TaskSnapshot.from_dict(task.to_dict()).snapshot_digest
    assert source.identity_digest == SourceIdentity.from_dict(source.to_dict()).identity_digest
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://architecture@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
        selected_context_refs=(("finding", "release-topology", "direct"),),
    )
    assert context.context_digest == ContextSnapshot.from_dict(context.to_dict()).context_digest
    validate_context(context, source, graph, task=task)

    changed = SourceIdentity(
        repository=source.repository,
        branch=source.branch,
        commit="d" * 40,
        tree_digest=source.tree_digest,
        dirty=False,
    )
    with pytest.raises(StaleContextError, match="source_revision_mismatch"):
        validate_context(context, changed, graph, task=task)


def test_graph_mismatch_fails_closed():
    task, source, graph = identities()
    with pytest.raises(StaleContextError, match="graph_source_mismatch"):
        build_context_snapshot(
            task=task,
            source=source,
            graph=GraphIdentity(
                revision=graph.revision,
                source_commit="e" * 40,
                graph_digest=graph.graph_digest,
            ),
            role="Architecture",
            skill_identity="skill://architecture@1",
            tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
        )


def test_state_is_append_only_optimistic_idempotent_and_survives_reopen(tmp_path):
    task, source, _ = identities()
    path = tmp_path / "control.sqlite3"
    store = ControlStateStore(path)
    store.create_task(task, source, owner="Owner")
    first = store.transition(
        task_id=task.task_id,
        expected_version=0,
        expected_state="DRAFT",
        next_state="ACCEPTED",
        owner="Owner",
        source=source,
        reason="accepted scope",
        idempotency_key="accept-1",
        next_owner="Architecture",
    )
    assert first.version == 1
    assert store.transition(
        task_id=task.task_id,
        expected_version=0,
        expected_state="DRAFT",
        next_state="ACCEPTED",
        owner="Owner",
        source=source,
        reason="accepted scope",
        idempotency_key="accept-1",
        next_owner="Architecture",
    ) == first
    with pytest.raises(ConcurrentTransitionError):
        store.transition(
            task_id=task.task_id,
            expected_version=0,
            expected_state="DRAFT",
            next_state="ACCEPTED",
            owner="Owner",
            source=source,
            reason="stale writer",
            idempotency_key="accept-2",
            next_owner="Architecture",
        )
    reopened = ControlStateStore(path)
    assert reopened.get_task(task.task_id).version == 1
    assert len(reopened.list_transitions(task.task_id)) == 1


def test_idempotency_key_cannot_replay_a_different_transition(tmp_path):
    task, source, _ = identities()
    store = ControlStateStore(tmp_path / "control.sqlite3")
    store.create_task(task, source, owner="Owner")
    store.transition(
        task_id=task.task_id,
        expected_version=0,
        expected_state="DRAFT",
        next_state="ACCEPTED",
        owner="Owner",
        source=source,
        reason="accepted scope",
        idempotency_key="accept-1",
        next_owner="Architecture",
    )
    with pytest.raises(ConcurrentTransitionError, match="idempotency_key_collision"):
        store.transition(
            task_id=task.task_id,
            expected_version=99,
            expected_state="RELEASE_DECIDED",
            next_state="LEARNING_RECORDED",
            owner="attacker",
            source=source,
            reason="different operation",
            idempotency_key="accept-1",
            next_owner="attacker",
        )


def test_state_machine_and_source_identity_are_fail_closed(tmp_path):
    task, source, _ = identities()
    store = ControlStateStore(tmp_path / "control.sqlite3")
    store.create_task(task, source, owner="Owner")
    with pytest.raises(InvalidTransitionError):
        store.transition(
            task_id=task.task_id,
            expected_version=0,
            expected_state="DRAFT",
            next_state="QUALITY_REVIEWED",
            owner="Owner",
            source=source,
            reason="jump",
            idempotency_key="jump-1",
            next_owner="Quality",
        )
    changed = SourceIdentity(
        repository=source.repository,
        branch=source.branch,
        commit="f" * 40,
        tree_digest=source.tree_digest,
        dirty=False,
    )
    with pytest.raises(StaleContextError, match="source_identity_mismatch"):
        store.transition(
            task_id=task.task_id,
            expected_version=0,
            expected_state="DRAFT",
            next_state="ACCEPTED",
            owner="Owner",
            source=changed,
            reason="wrong source",
            idempotency_key="wrong-source",
            next_owner="Architecture",
        )


def test_tool_allowlist_returns_denied_receipt_without_authority():
    policy = ToolPolicy.for_role("Architecture")
    allowed = record_tool_call(
        policy=policy,
        run_id="run-1",
        tool_id="read_source",
        arguments={"path": "src"},
        result={"ok": True},
    )
    assert allowed.allowed is True
    with pytest.raises(ToolDeniedError) as denied:
        record_tool_call(
            policy=policy,
            run_id="run-1",
            tool_id="edit_source",
            arguments={"path": "src/x.py"},
        )
    assert denied.value.receipt.allowed is False
    assert denied.value.receipt.error_class == "PERMISSION_DENIED"
    assert denied.value.receipt.authority_granted is False


def test_tool_receipt_cannot_claim_authority():
    with pytest.raises(ValueError, match="authority"):
        ToolCallReceipt(
            run_id="run-forged",
            role="Quality",
            tool_id="release",
            allowed=True,
            arguments_digest="1" * 64,
            result_digest="2" * 64,
            error_class=None,
            authority_granted=True,
        )


def test_handoff_is_bound_to_all_cross_run_identities():
    task, source, graph = identities()
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://architecture@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    receipt = HandoffReceipt(
        task_id=task.task_id,
        task_version=3,
        from_owner="Architecture",
        to_role="Development",
        source_identity=source.identity_digest,
        context_digest=context.context_digest,
        required_artifact_refs=(ArtifactRef("architecture_packet", "1" * 64),),
        accepted_or_rejected="accepted",
        reason="impact packet complete",
        next_owner="Development",
    )
    assert HandoffReceipt.from_dict(receipt.to_dict()) == receipt
    validate_handoff_receipt(receipt, task=task, source=source, context=context)
    with pytest.raises(ValueError, match="receipt_digest"):
        HandoffReceipt.from_dict({**receipt.to_dict(), "context_digest": "0" * 64})


def test_evidence_admission_never_grants_authority():
    task, source, graph = identities()
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Quality",
        skill_identity="skill://quality@1",
        tool_policy_identity=ToolPolicy.for_role("Quality").policy_digest,
    )
    evidence = admit_evidence(
        task=task,
        source=source,
        context=context,
        artifact_type="quality_verdict",
        producer="quality-agent",
        status="PASS",
        upstream=(ArtifactRef("runtime_evidence", "2" * 64),),
    )
    assert evidence.authority == {"deployment_allowed": False, "paper_allowed": False, "real_allowed": False}
    with pytest.raises(EvidenceAdmissionError, match="authority"):
        admit_evidence(
            task=task,
            source=source,
            context=context,
            artifact_type="release_verdict",
            producer="release-controller",
            status="PASS",
            upstream=(),
            authority={"deployment_allowed": True, "paper_allowed": False, "real_allowed": False},
        )


def test_evidence_authority_cannot_be_mutated_after_admission():
    task, source, graph = identities()
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Quality",
        skill_identity="skill://quality@1",
        tool_policy_identity=ToolPolicy.for_role("Quality").policy_digest,
    )
    evidence = admit_evidence(
        task=task,
        source=source,
        context=context,
        artifact_type="quality_verdict",
        producer="quality-agent",
        status="PASS",
    )
    with pytest.raises(TypeError):
        evidence.authority["real_allowed"] = True
    assert EvidenceAdmission.from_dict(evidence.to_dict()) == evidence
    tampered = evidence.to_dict()
    tampered["status"] = "FAIL"
    with pytest.raises(EvidenceAdmissionError, match="digest"):
        EvidenceAdmission.from_dict(tampered)


def test_context_validation_requires_matching_task_and_approved_policy():
    task, source, graph = identities()
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://architecture@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    with pytest.raises(StaleContextError):
        validate_context(context, source, graph, task=TaskSnapshot(
            task_id="other-task",
            task_revision=task.task_revision,
            objective=task.objective,
            measures=task.measures,
            acceptance_criteria=task.acceptance_criteria,
            non_goals=task.non_goals,
            approved_scope=task.approved_scope,
            required_approvals=task.required_approvals,
            source_reference=source.identity_digest,
        ))


def test_all_contract_from_dict_requires_schema_and_digest():
    task, source, graph = identities()
    context = build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://architecture@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )
    for factory, payload, field in (
        (SourceIdentity.from_dict, source.to_dict(), "identity_digest"),
        (GraphIdentity.from_dict, graph.to_dict(), "identity_digest"),
        (TaskSnapshot.from_dict, task.to_dict(), "snapshot_digest"),
        (ContextSnapshot.from_dict, context.to_dict(), "context_digest"),
    ):
        payload.pop(field)
        with pytest.raises(ValueError):
            factory(payload)
