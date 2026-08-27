from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from quantengine_public.agent_platform.contracts import GraphIdentity, SourceIdentity, TaskSnapshot
from quantengine_public.agent_platform.learning import (
    HISTORICAL_REGRESSION_CASES,
    LearningClosureError,
    execute_learning_closure,
    verify_learning_closure,
)
from quantengine_public.agent_platform.vertical_slice import SliceArtifact, VerticalSliceRunner
from quantengine_public.delivery.identity import seal_artifact


pytest.importorskip("agents", reason="install openai-agents==0.22.0")


@pytest.fixture
def subject_result(tmp_path):
    source = SourceIdentity("quantengine-public", "main", "a" * 40, "b" * 64)
    task = TaskSnapshot(
        task_id="TASKSYS-1262",
        task_revision="r1",
        objective="close release authority topology",
        measures=("zero false PASS",),
        acceptance_criteria=("exact topology",),
        non_goals=("deployment", "Paper", "QuantEngine Replay", "Real", "M7", "M8"),
        approved_scope=("src/quantengine_public/agent_platform",),
        required_approvals=(),
        source_reference=source.identity_digest,
    )
    graph = GraphIdentity("graph-r1", source.commit, "c" * 64)
    runner = VerticalSliceRunner(tmp_path / "subject.sqlite3", task=task, source=source, graph=graph)
    result = asyncio.run(runner.run())
    runner.close()
    return result


@pytest.fixture
def learning_identity():
    return {
        "learning_task_id": "TASKSYS-1264",
        "learning_source_identity": "d" * 64,
        "learning_graph_identity": "e" * 64,
        "learning_context_digest": "f" * 64,
        "reviewer_identity": "public-quality-reviewer@1",
    }


def _reseal(artifact: SliceArtifact, *, payload_updates=None, producer=None) -> SliceArtifact:
    payload = deepcopy(dict(artifact.payload))
    payload.update(payload_updates or {})
    return SliceArtifact.from_dict(
        seal_artifact(
            artifact_type=artifact.artifact_type,
            producer=producer or artifact.producer,
            status=artifact.status,
            upstream=[ref.to_dict() for ref in artifact.upstream],
            payload=payload,
            authority=dict(artifact.authority),
        )
    )


def test_learning_closure_executes_the_full_evidence_bound_flywheel(subject_result, learning_identity):
    result = execute_learning_closure(subject=subject_result, **learning_identity)

    assert [artifact.artifact_type for artifact in result.artifacts] == [
        "public_delivery.architecture_packet",
        "public_delivery.validation_plan",
        "public_delivery.patch_manifest",
        "public_delivery.test_result",
        "public_delivery.runtime_evidence",
        "public_delivery.quality_verdict",
        "public_delivery.aar",
    ]
    assert result.aar.status == "PASS"
    assert result.aar.producer == "public_learning_flywheel"
    assert result.aar.authority == {
        "deployment_allowed": False,
        "paper_allowed": False,
        "real_allowed": False,
    }
    assert result.aar.payload["promotion_decision"] == "PROMOTE_RETAINED_REGRESSION"
    assert result.aar.payload["subject_release_digest"] == subject_result.release["artifact_digest"]
    assert {case.case_id for case in result.replay_cases} == set(HISTORICAL_REGRESSION_CASES)
    assert all(case.status == "PASS" and case.observed_error == case.expected_error for case in result.replay_cases)
    assert verify_learning_closure(subject=subject_result, artifacts=result.artifacts, **learning_identity) == result.aar


def test_learning_closure_rejects_missing_or_non_independent_promotion_review(subject_result, learning_identity):
    result = execute_learning_closure(subject=subject_result, **learning_identity)
    without_review = tuple(
        artifact for artifact in result.artifacts
        if artifact.artifact_type != "public_delivery.quality_verdict"
    )
    with pytest.raises(LearningClosureError, match="requires_exactly_one:public_delivery.quality_verdict"):
        verify_learning_closure(subject=subject_result, artifacts=without_review, **learning_identity)

    review = next(
        artifact for artifact in result.artifacts
        if artifact.artifact_type == "public_delivery.quality_verdict"
    )
    forged_review = _reseal(review, payload_updates={"reviewer_identity": "public_development_agent"})
    forged = tuple(forged_review if artifact is review else artifact for artifact in result.artifacts)
    with pytest.raises(LearningClosureError, match="independent_promotion_review_required"):
        verify_learning_closure(subject=subject_result, artifacts=forged, **learning_identity)


def test_learning_closure_rejects_cross_task_stale_identity_and_forged_aar_binding(subject_result, learning_identity):
    result = execute_learning_closure(subject=subject_result, **learning_identity)
    test_result = next(
        artifact for artifact in result.artifacts
        if artifact.artifact_type == "public_delivery.test_result"
    )
    cross_task = _reseal(test_result, payload_updates={"task_id": "TASKSYS-OTHER"})
    forged_cross_task = tuple(cross_task if artifact is test_result else artifact for artifact in result.artifacts)
    with pytest.raises(LearningClosureError, match="learning_identity_mismatch"):
        verify_learning_closure(subject=subject_result, artifacts=forged_cross_task, **learning_identity)

    stale_identity = {**learning_identity, "learning_source_identity": "0" * 64}
    with pytest.raises(LearningClosureError, match="learning_identity_mismatch"):
        verify_learning_closure(subject=subject_result, artifacts=result.artifacts, **stale_identity)

    aar = result.aar
    forged_aar = _reseal(aar, payload_updates={"regression_result_digest": "0" * 64})
    forged_binding = tuple(forged_aar if artifact is aar else artifact for artifact in result.artifacts)
    with pytest.raises(LearningClosureError, match="aar_digest_binding_mismatch"):
        verify_learning_closure(subject=subject_result, artifacts=forged_binding, **learning_identity)


def test_learning_closure_is_deterministic_and_retains_named_attack_failures(subject_result, learning_identity):
    first = execute_learning_closure(subject=subject_result, **learning_identity)
    second = execute_learning_closure(subject=subject_result, **learning_identity)

    assert first.aar.artifact_digest == second.aar.artifact_digest
    observed = {case.case_id: case.observed_error for case in first.replay_cases}
    assert observed == dict(HISTORICAL_REGRESSION_CASES)
    assert set(observed) == {
        "missing_quality",
        "missing_runtime",
        "forged_quality_producer",
        "wrong_runtime_upstream_digest",
        "upstream_authority_injection",
        "stale_source_identity",
        "graph_identity_mismatch",
    }


def test_learning_closure_rejects_a_subject_release_that_was_not_rederived(subject_result, learning_identity):
    release = subject_result.release
    forged_release = seal_artifact(
        artifact_type=release["artifact_type"],
        producer=release["producer"],
        status=release["status"],
        upstream=deepcopy(release["upstream"]),
        payload={**deepcopy(release["payload"]), "decision": "forged-but-schema-valid"},
        authority=deepcopy(release["authority"]),
    )
    forged_subject = replace(subject_result, release=forged_release)

    with pytest.raises(LearningClosureError, match="subject_release_not_rederived"):
        execute_learning_closure(subject=forged_subject, **learning_identity)
