"""DEC-0040 M4 red contracts for Objective-bound Thin Control."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ogsm_v2_fixtures import objective_contract_payload
from quantengine_public.agent_platform.context import (
    StaleContextError,
    build_context_snapshot,
    validate_context,
)
from quantengine_public.agent_platform.contracts import (
    SCHEMA_VERSION,
    ArtifactRef,
    ContextSnapshot,
    EvidenceAdmission,
    GraphIdentity,
    HandoffReceipt,
    RunRequest,
    RunResult,
    SourceIdentity,
    TaskSnapshot,
    admit_evidence,
    validate_handoff_receipt,
    validate_run_binding,
)
from quantengine_public.agent_platform.control_state import ControlStateStore
from quantengine_public.agent_platform.ogsm_v2 import (
    ObjectiveChangeReceipt,
    ObjectiveContract,
)
from quantengine_public.agent_platform.tool_policy import ToolPolicy
from quantengine_public.delivery.identity import seal_artifact


def _contracts() -> tuple[ObjectiveContract, ObjectiveContract, ObjectiveChangeReceipt]:
    previous = ObjectiveContract.from_dict(objective_contract_payload())
    changed = ObjectiveContract.from_dict(
        objective_contract_payload(
            revision=2,
            parent_digest=previous.contract_digest,
            objective="Invalidate work bound to the superseded Objective Contract.",
        )
    )
    receipt = ObjectiveChangeReceipt(
        previous_contract_digest=previous.contract_digest,
        new_contract_digest=changed.contract_digest,
        changed_fields=("objective",),
        owner_rationale="The accepted outcome changed, so dependent work must be reconsidered.",
        cause_refs=("d" * 64,),
        invalidated_dependencies=("run-old", "handoff-old", "evidence-old"),
        reusable_evidence=("e" * 64,),
        owner="Owner",
        accepted_at="2026-08-28T01:00:00Z",
    )
    return previous, changed, receipt


def _identities(contract: ObjectiveContract):
    source = SourceIdentity(
        repository="quantengine-public",
        branch="codex/DEC-0040/ogsm-v2-thin-control",
        commit="a" * 40,
        tree_digest="b" * 64,
    )
    task = TaskSnapshot(
        task_id="TASKSYS-1335",
        task_revision=f"objective-r{contract.revision}",
        objective=contract.objective,
        measures=("all downstream identities are Objective-bound",),
        acceptance_criteria=("stale dependencies fail closed",),
        non_goals=("execution authority",),
        approved_scope=("src/quantengine_public/agent_platform",),
        required_approvals=(),
        source_reference=source.identity_digest,
        objective_contract_digest=contract.contract_digest,
    )
    graph = GraphIdentity("graph-r1", source.commit, "c" * 64)
    return task, source, graph


def _context(task, source, graph):
    return build_context_snapshot(
        task=task,
        source=source,
        graph=graph,
        role="Architecture",
        skill_identity="skill://public-ogsm-control@1",
        tool_policy_identity=ToolPolicy.for_role("Architecture").policy_digest,
    )


def _artifact(task, source, graph, context, *, objective_digest: str | None):
    payload = {
        "task_id": task.task_id,
        "source_identity": source.identity_digest,
        "context_digest": context.context_digest,
        "graph_identity": graph.identity_digest,
    }
    if objective_digest is not None:
        payload["objective_contract_digest"] = objective_digest
    return seal_artifact(
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent",
        status="READY",
        upstream=[],
        payload=payload,
    )


def test_v1_positional_contract_shape_and_digest_remain_unchanged():
    contract, _, _ = _contracts()
    task, source, _ = _identities(contract)
    legacy = TaskSnapshot(
        "legacy-task",
        "r1",
        "legacy objective",
        ("legacy measure",),
        ("legacy acceptance",),
        (),
        ("legacy scope",),
        (),
        source.identity_digest,
        SCHEMA_VERSION,
    )
    keyword = TaskSnapshot(
        task_id="legacy-task",
        task_revision="r1",
        objective="legacy objective",
        measures=("legacy measure",),
        acceptance_criteria=("legacy acceptance",),
        non_goals=(),
        approved_scope=("legacy scope",),
        required_approvals=(),
        source_reference=source.identity_digest,
    )
    assert legacy == keyword
    assert legacy.snapshot_digest == keyword.snapshot_digest
    assert "objective_contract_digest" not in legacy.to_dict()


def test_v2_contract_digest_flows_through_task_context_run_handoff_and_evidence():
    contract, _, _ = _contracts()
    task, source, graph = _identities(contract)
    context = _context(task, source, graph)

    assert TaskSnapshot.from_dict(task.to_dict()).objective_contract_digest == contract.contract_digest
    assert ContextSnapshot.from_dict(context.to_dict()).objective_contract_digest == contract.contract_digest
    validate_context(context, source, graph, task=task)

    request = RunRequest(
        run_id="run-bound",
        task_id=task.task_id,
        expected_task_version=0,
        role="Architecture",
        collaboration_mode="independent_review",
        context_digest=context.context_digest,
        skill_identity=context.skill_identity,
        allowed_tool_policy=context.tool_policy_identity,
        required_output_type="text",
        upstream_artifact_refs=(),
        timeout_policy="bounded",
        idempotency_key="run-bound",
        objective_contract_digest=contract.contract_digest,
    )
    result = RunResult(
        run_id=request.run_id,
        status="PASS",
        stop_reason="completed",
        result_digest="f" * 64,
        objective_contract_digest=contract.contract_digest,
    )
    receipt = HandoffReceipt(
        task_id=task.task_id,
        task_version=0,
        from_owner="Owner",
        to_role="Architecture",
        source_identity=source.identity_digest,
        context_digest=context.context_digest,
        required_artifact_refs=(ArtifactRef("public_delivery.ogsm", "1" * 64),),
        accepted_or_rejected="accepted",
        reason="Objective-bound handoff",
        next_owner="Architecture",
        graph_identity=graph.identity_digest,
        objective_contract_digest=contract.contract_digest,
    )
    evidence = admit_evidence(
        task=task,
        source=source,
        context=context,
        artifact_type="public_delivery.architecture_packet",
        producer="public_architecture_agent",
        status="READY",
    )

    assert request.to_dict()["objective_contract_digest"] == contract.contract_digest
    assert result.to_dict()["objective_contract_digest"] == contract.contract_digest
    assert HandoffReceipt.from_dict(receipt.to_dict()).objective_contract_digest == contract.contract_digest
    assert EvidenceAdmission.from_dict(evidence.to_dict()).objective_contract_digest == contract.contract_digest
    validate_handoff_receipt(receipt, task=task, source=source, context=context)
    validate_run_binding(request, task=task, context=context, result=result)

    with pytest.raises(StaleContextError, match="objective_contract_digest_mismatch"):
        validate_run_binding(
            replace(request, objective_contract_digest="0" * 64),
            task=task,
            context=context,
        )


def test_v2_context_and_handoff_reject_missing_or_stale_objective_binding():
    contract, changed, _ = _contracts()
    task, source, graph = _identities(contract)
    context = _context(task, source, graph)

    with pytest.raises(StaleContextError, match="objective_contract_digest_mismatch"):
        validate_context(
            replace(context, objective_contract_digest=changed.contract_digest),
            source,
            graph,
            task=task,
        )

    stale = HandoffReceipt(
        task_id=task.task_id,
        task_version=0,
        from_owner="Owner",
        to_role="Architecture",
        source_identity=source.identity_digest,
        context_digest=context.context_digest,
        required_artifact_refs=(ArtifactRef("public_delivery.ogsm", "1" * 64),),
        accepted_or_rejected="accepted",
        reason="stale Objective",
        next_owner="Architecture",
        graph_identity=graph.identity_digest,
        objective_contract_digest=changed.contract_digest,
    )
    with pytest.raises(StaleContextError, match="objective_contract_digest_mismatch"):
        validate_handoff_receipt(stale, task=task, source=source, context=context)


def test_v2_store_rejects_unbound_runs_evidence_and_transitions(tmp_path):
    contract, changed, _ = _contracts()
    task, source, graph = _identities(contract)
    context = _context(task, source, graph)
    store = ControlStateStore(tmp_path / "control.sqlite3")
    state = store.create_task(task, source, owner="Owner")
    assert state.objective_contract_digest == contract.contract_digest

    with pytest.raises(StaleContextError, match="objective_contract_digest_required"):
        store.record_run("run-missing", task_id=task.task_id, task_version=0, status="ready")
    with pytest.raises(StaleContextError, match="objective_contract_digest_mismatch"):
        store.record_run(
            "run-stale",
            task_id=task.task_id,
            task_version=0,
            status="ready",
            objective_contract_digest=changed.contract_digest,
        )
    store.record_run(
        "run-current",
        task_id=task.task_id,
        task_version=0,
        status="ready",
        objective_contract_digest=contract.contract_digest,
    )

    with pytest.raises(StaleContextError, match="objective_contract_digest_required"):
        store.admit_artifact(_artifact(task, source, graph, context, objective_digest=None))
    ref = store.admit_artifact(
        _artifact(task, source, graph, context, objective_digest=contract.contract_digest)
    )
    with pytest.raises(StaleContextError, match="objective_contract_digest_required"):
        store.transition(
            task_id=task.task_id,
            expected_version=0,
            expected_state="DRAFT",
            next_state="ACCEPTED",
            owner="Owner",
            source=source,
            reason="missing Objective binding",
            idempotency_key="accept-missing",
            next_owner="Owner",
        )
    accepted = store.transition(
        task_id=task.task_id,
        expected_version=0,
        expected_state="DRAFT",
        next_state="ACCEPTED",
        owner="Owner",
        source=source,
        reason="current Objective binding",
        idempotency_key="accept-current",
        next_owner="Owner",
        objective_contract_digest=contract.contract_digest,
    )
    assert accepted.objective_contract_digest == contract.contract_digest
    assert store.list_admitted_artifacts(task.task_id)[0].objective_contract_digest == contract.contract_digest
    assert ref.artifact_type == "public_delivery.architecture_packet"


def test_objective_revision_is_append_only_and_invalidates_old_dependencies(tmp_path):
    previous, changed, receipt = _contracts()
    task, source, graph = _identities(previous)
    context = _context(task, source, graph)
    store = ControlStateStore(tmp_path / "control.sqlite3")
    store.create_task(task, source, owner="Owner")
    old_ref = store.admit_artifact(
        _artifact(task, source, graph, context, objective_digest=previous.contract_digest)
    )
    changed_task = replace(
        task,
        task_revision="objective-r2",
        objective=changed.objective,
        objective_contract_digest=changed.contract_digest,
    )

    revision = store.revise_objective(
        task=changed_task,
        source=source,
        expected_version=0,
        previous_contract=previous,
        changed_contract=changed,
        change_receipt=receipt,
    )

    current = store.get_task(task.task_id)
    assert current.state == "REVISION_REQUIRED"
    assert current.version == 1
    assert current.objective_contract_digest == changed.contract_digest
    assert revision.receipt_digest == receipt.receipt_digest
    assert store.list_objective_revisions(task.task_id) == [revision]
    assert store.list_admitted_artifacts(task.task_id)[0].artifact_digest == old_ref.artifact_digest

    with pytest.raises(StaleContextError, match="evidence_objective_contract_mismatch"):
        store.transition(
            task_id=task.task_id,
            expected_version=1,
            expected_state="REVISION_REQUIRED",
            next_state="CONTEXT_READY",
            owner="Owner",
            source=source,
            reason="old evidence cannot be silently reused",
            idempotency_key="reuse-old",
            next_owner="Architecture",
            evidence_refs=(old_ref,),
            objective_contract_digest=changed.contract_digest,
        )
