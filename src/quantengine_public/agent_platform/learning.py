"""Deterministic Milestone-5 learning closure for one retained public defect.

This module does not add an Agent orchestrator.  It replays the historical
Release attacks against the existing deterministic controller, seals the
result with the existing public artifact contract, requires an independent
Quality promotion review, and derives a zero-authority AAR.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from quantengine_public.delivery.identity import content_digest, verify_artifact_chain

from .contracts import ArtifactRef
from .vertical_slice import (
    ReleaseTopologyError,
    SliceArtifact,
    VerticalSliceResult,
    derive_release,
)


DEFECT_ID = "QEP-RELEASE-AUTHORITY-TOPOLOGY-001"
REPAIR_LAYER = "quantengine_public.agent_platform.vertical_slice.derive_release"
PROMOTION_DECISION = "PROMOTE_RETAINED_REGRESSION"
RED_TEST_RECEIPT_DIGEST = content_digest(
    {
        "command": "pytest -q tests/agent_platform/test_learning_closure.py",
        "failure": "ModuleNotFoundError:quantengine_public.agent_platform.learning",
        "phase": "RED",
    }
)

HISTORICAL_REGRESSION_CASES: Mapping[str, str] = MappingProxyType(
    {
        "missing_quality": "requires_exactly_one:public_delivery.quality_verdict",
        "missing_runtime": "requires_exactly_one:public_delivery.runtime_evidence",
        "forged_quality_producer": "invalid_artifact:producer_mismatch",
        "wrong_runtime_upstream_digest": "invalid_evidence_chain:unknown_upstream",
        "upstream_authority_injection": "invalid_artifact:invalid_authority_semantics",
        "stale_source_identity": "release_identity_mismatch",
        "graph_identity_mismatch": "graph_identity_mismatch",
    }
)

_LEARNING_TYPES = (
    "public_delivery.architecture_packet",
    "public_delivery.validation_plan",
    "public_delivery.patch_manifest",
    "public_delivery.test_result",
    "public_delivery.runtime_evidence",
    "public_delivery.quality_verdict",
    "public_delivery.aar",
)
_INDEPENDENCE_FORBIDDEN = {
    "public_architecture_agent",
    "public_test_agent",
    "public_development_agent",
    "quantengine_public",
    "public_release_controller",
    "public_learning_flywheel",
}


class LearningClosureError(RuntimeError):
    """Raised when learning evidence cannot support deterministic promotion."""


@dataclass(frozen=True, slots=True)
class RegressionReplay:
    case_id: str
    expected_error: str
    observed_error: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "expected_error": self.expected_error,
            "observed_error": self.observed_error,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class LearningClosureResult:
    subject_task_id: str
    learning_task_id: str
    replay_cases: tuple[RegressionReplay, ...]
    artifacts: tuple[SliceArtifact, ...]
    aar: SliceArtifact


def _raw_with(
    artifact: SliceArtifact,
    *,
    producer: str | None = None,
    authority: Mapping[str, bool] | None = None,
    upstream: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    raw = deepcopy(artifact.to_dict())
    if producer is not None:
        raw["producer"] = producer
    if authority is not None:
        raw["authority"] = dict(authority)
    if upstream is not None:
        raw["upstream"] = [dict(ref) for ref in upstream]
    material = {key: deepcopy(value) for key, value in raw.items() if key != "artifact_digest"}
    raw["artifact_digest"] = content_digest(material)
    return raw


def _failure_code(call: Callable[[], Any], expected: str) -> str:
    try:
        call()
    except (ReleaseTopologyError, ValueError) as exc:
        observed = str(exc)
        return expected if observed.startswith(expected) else observed
    return "NO_FAILURE"


def replay_historical_release_attacks(subject: VerticalSliceResult) -> tuple[RegressionReplay, ...]:
    """Execute retained attacks against the current Release controller."""
    evidence = list(subject.evidence)
    source_identity = subject.source.identity_digest
    graph_identity = subject.graph.identity_digest

    def run(items: Sequence[SliceArtifact | Mapping[str, Any]], **overrides: str) -> Any:
        return derive_release(
            task_id=subject.task.task_id,
            source_identity=overrides.get("source_identity", source_identity),
            graph_identity=overrides.get("graph_identity", graph_identity),
            evidence=items,
        )

    quality = next(item for item in evidence if item.artifact_type == "public_delivery.quality_verdict")
    runtime = next(item for item in evidence if item.artifact_type == "public_delivery.runtime_evidence")
    test_result = next(item for item in evidence if item.artifact_type == "public_delivery.test_result")

    missing_quality = [item for item in evidence if item is not quality]
    missing_runtime = [item for item in evidence if item not in (runtime, quality)]
    forged_quality = [
        _raw_with(item, producer="attacker") if item is quality else item
        for item in evidence
    ]
    wrong_runtime = _raw_with(
        runtime,
        upstream=(
            {
                "artifact_type": runtime.upstream[0].artifact_type,
                "artifact_digest": "0" * 64,
            },
            runtime.upstream[1].to_dict(),
        ),
    )
    wrong_runtime_upstream = [wrong_runtime if item is runtime else item for item in evidence]
    injected_test = _raw_with(
        test_result,
        authority={
            "deployment_allowed": True,
            "paper_allowed": False,
            "real_allowed": False,
        },
    )
    authority_injection = [injected_test if item is test_result else item for item in evidence]

    calls: Mapping[str, Callable[[], Any]] = {
        "missing_quality": lambda: run(missing_quality),
        "missing_runtime": lambda: run(missing_runtime),
        "forged_quality_producer": lambda: run(forged_quality),
        "wrong_runtime_upstream_digest": lambda: run(wrong_runtime_upstream),
        "upstream_authority_injection": lambda: run(authority_injection),
        "stale_source_identity": lambda: run(evidence, source_identity="0" * 64),
        "graph_identity_mismatch": lambda: run(evidence, graph_identity="0" * 64),
    }
    results = tuple(
        RegressionReplay(
            case_id=case_id,
            expected_error=expected,
            observed_error=(observed := _failure_code(calls[case_id], expected)),
            status="PASS" if observed == expected else "FAIL",
        )
        for case_id, expected in HISTORICAL_REGRESSION_CASES.items()
    )
    if any(result.status != "PASS" for result in results):
        failed = ",".join(result.case_id for result in results if result.status != "PASS")
        raise LearningClosureError(f"historical_regression_replay_failed:{failed}")
    return results


def _learning_artifact(
    *,
    learning_task_id: str,
    learning_source_identity: str,
    learning_graph_identity: str,
    learning_context_digest: str,
    artifact_type: str,
    producer: str,
    status: str,
    upstream: Sequence[ArtifactRef],
    payload: Mapping[str, Any],
) -> SliceArtifact:
    return SliceArtifact.create(
        task_id=learning_task_id,
        source_identity=learning_source_identity,
        graph_identity=learning_graph_identity,
        context_digest=learning_context_digest,
        artifact_type=artifact_type,
        producer=producer,
        status=status,
        upstream=upstream,
        payload=payload,
    )


def _subject_release(subject: VerticalSliceResult) -> SliceArtifact:
    if subject.release is None:
        raise LearningClosureError("subject_release_missing")
    try:
        release = SliceArtifact.from_dict(subject.release)
    except ReleaseTopologyError as exc:
        raise LearningClosureError(f"subject_release_invalid:{exc}") from exc
    chain = [item.to_dict() for item in (*subject.evidence, release)]
    errors = verify_artifact_chain(chain)
    if errors:
        raise LearningClosureError("subject_chain_invalid:" + ",".join(errors))
    if (
        release.artifact_type != "public_delivery.release_verdict"
        or release.producer != "public_release_controller"
        or release.status != "PASS"
        or release.task_id != subject.task.task_id
        or release.source_identity != subject.source.identity_digest
        or release.graph_identity != subject.graph.identity_digest
        or any(release.authority.values())
    ):
        raise LearningClosureError("subject_release_identity_or_authority_mismatch")
    try:
        rederived = derive_release(
            task_id=subject.task.task_id,
            source_identity=subject.source.identity_digest,
            graph_identity=subject.graph.identity_digest,
            evidence=subject.evidence,
        )
    except ReleaseTopologyError as exc:
        raise LearningClosureError(f"subject_release_not_rederived:{exc}") from exc
    if rederived["artifact_digest"] != release.artifact_digest:
        raise LearningClosureError("subject_release_not_rederived:digest_mismatch")
    return release


def execute_learning_closure(
    *,
    subject: VerticalSliceResult,
    learning_task_id: str,
    learning_source_identity: str,
    learning_graph_identity: str,
    learning_context_digest: str,
    reviewer_identity: str,
) -> LearningClosureResult:
    """Replay the defect and build a fully bound M7 learning evidence chain."""
    subject_release = _subject_release(subject)
    replay_cases = replay_historical_release_attacks(subject)
    common = {
        "subject_task_id": subject.task.task_id,
        "subject_source_identity": subject.source.identity_digest,
        "subject_graph_identity": subject.graph.identity_digest,
        "subject_release_digest": subject_release.artifact_digest,
        "defect_id": DEFECT_ID,
    }

    defect = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="architecture_packet",
        producer="public_architecture_agent",
        status="RECORDED",
        upstream=(subject_release.ref(),),
        payload={
            **common,
            "historical_failure": "release accepted without exact runtime and independent Quality topology",
            "repair_layer": REPAIR_LAYER,
        },
    )
    validation = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="validation_plan",
        producer="public_test_agent",
        status="READY",
        upstream=(defect.ref(),),
        payload={
            **common,
            "regression_ids": list(HISTORICAL_REGRESSION_CASES),
            "expected_failures": dict(HISTORICAL_REGRESSION_CASES),
            "red_test_receipt_digest": RED_TEST_RECEIPT_DIGEST,
        },
    )
    repair = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="patch_manifest",
        producer="public_development_agent",
        status="READY",
        upstream=(defect.ref(), validation.ref()),
        payload={
            **common,
            "repair_layer": REPAIR_LAYER,
            "repair_source_identity": learning_source_identity,
            "changed_contract": "exact Release evidence topology",
        },
    )
    regression = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="test_result",
        producer="public_test_agent",
        status="PASS",
        upstream=(validation.ref(), repair.ref()),
        payload={
            **common,
            "red_test_receipt_digest": RED_TEST_RECEIPT_DIGEST,
            "regression_ids": list(HISTORICAL_REGRESSION_CASES),
            "result": "all_retained_cases_rejected_fail_closed",
        },
    )
    replay = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="runtime_evidence",
        producer="quantengine_public",
        status="PASS",
        upstream=(regression.ref(), subject_release.ref()),
        payload={
            **common,
            "replay_kind": "local_historical_defect_replay",
            "formal_quantengine_replay_authority": False,
            "cases": [case.to_dict() for case in replay_cases],
        },
    )
    review = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="quality_verdict",
        producer="public_quality_shield",
        status="PASS",
        upstream=(replay.ref(),),
        payload={
            **common,
            "reviewer_identity": reviewer_identity,
            "independent_from": sorted(_INDEPENDENCE_FORBIDDEN),
            "reviewed_regression_digest": regression.artifact_digest,
            "reviewed_replay_digest": replay.artifact_digest,
            "promotion_decision": PROMOTION_DECISION,
        },
    )
    aar = _learning_artifact(
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        artifact_type="aar",
        producer="public_learning_flywheel",
        status="PASS",
        upstream=(
            subject_release.ref(),
            defect.ref(),
            validation.ref(),
            repair.ref(),
            regression.ref(),
            replay.ref(),
            review.ref(),
        ),
        payload={
            **common,
            "repair_layer": REPAIR_LAYER,
            "red_test_receipt_digest": RED_TEST_RECEIPT_DIGEST,
            "regression_plan_digest": validation.artifact_digest,
            "repair_manifest_digest": repair.artifact_digest,
            "regression_result_digest": regression.artifact_digest,
            "historical_replay_digest": replay.artifact_digest,
            "promotion_review_digest": review.artifact_digest,
            "promotion_decision": PROMOTION_DECISION,
        },
    )
    artifacts = (defect, validation, repair, regression, replay, review, aar)
    verified = verify_learning_closure(
        subject=subject,
        learning_task_id=learning_task_id,
        learning_source_identity=learning_source_identity,
        learning_graph_identity=learning_graph_identity,
        learning_context_digest=learning_context_digest,
        reviewer_identity=reviewer_identity,
        artifacts=artifacts,
    )
    return LearningClosureResult(subject.task.task_id, learning_task_id, replay_cases, artifacts, verified)


def verify_learning_closure(
    *,
    subject: VerticalSliceResult,
    learning_task_id: str,
    learning_source_identity: str,
    learning_graph_identity: str,
    learning_context_digest: str,
    reviewer_identity: str,
    artifacts: Sequence[SliceArtifact | Mapping[str, Any]],
) -> SliceArtifact:
    """Fail closed unless the supplied artifacts form the exact M7 topology."""
    try:
        items = tuple(item if isinstance(item, SliceArtifact) else SliceArtifact.from_dict(item) for item in artifacts)
    except ReleaseTopologyError as exc:
        raise LearningClosureError(f"invalid_learning_artifact:{exc}") from exc

    for item in items:
        if (
            item.task_id != learning_task_id
            or item.source_identity != learning_source_identity
            or item.graph_identity != learning_graph_identity
            or item.context_digest != learning_context_digest
        ):
            raise LearningClosureError("learning_identity_mismatch")

    def exact(artifact_type: str, producer: str) -> SliceArtifact:
        found = [item for item in items if item.artifact_type == artifact_type and item.producer == producer]
        if len(found) != 1:
            raise LearningClosureError(f"requires_exactly_one:{artifact_type}")
        return found[0]

    if len(items) != len(_LEARNING_TYPES) or {item.artifact_type for item in items} != set(_LEARNING_TYPES):
        for artifact_type in _LEARNING_TYPES:
            if sum(item.artifact_type == artifact_type for item in items) != 1:
                raise LearningClosureError(f"requires_exactly_one:{artifact_type}")
        raise LearningClosureError("unknown_learning_evidence")

    subject_release = _subject_release(subject)
    defect = exact("public_delivery.architecture_packet", "public_architecture_agent")
    validation = exact("public_delivery.validation_plan", "public_test_agent")
    repair = exact("public_delivery.patch_manifest", "public_development_agent")
    regression = exact("public_delivery.test_result", "public_test_agent")
    replay = exact("public_delivery.runtime_evidence", "quantengine_public")
    review = exact("public_delivery.quality_verdict", "public_quality_shield")
    aar = exact("public_delivery.aar", "public_learning_flywheel")

    # Check reviewer independence before resolving downstream AAR edges so a
    # re-sealed self-review fails with its exact policy identity.
    if (
        review.status != "PASS"
        or review.payload.get("reviewer_identity") != reviewer_identity
        or reviewer_identity in _INDEPENDENCE_FORBIDDEN
        or review.payload.get("independent_from") != sorted(_INDEPENDENCE_FORBIDDEN)
        or review.payload.get("reviewed_regression_digest") != regression.artifact_digest
        or review.payload.get("reviewed_replay_digest") != replay.artifact_digest
        or review.payload.get("promotion_decision") != PROMOTION_DECISION
    ):
        raise LearningClosureError("independent_promotion_review_required")

    full_chain = [item.to_dict() for item in (*subject.evidence, subject_release, *items)]
    chain_errors = verify_artifact_chain(full_chain)
    if chain_errors:
        raise LearningClosureError("invalid_learning_chain:" + ",".join(chain_errors))

    def refs(item: SliceArtifact) -> set[ArtifactRef]:
        return set(item.upstream)

    expected_topology = (
        (defect, {subject_release.ref()}),
        (validation, {defect.ref()}),
        (repair, {defect.ref(), validation.ref()}),
        (regression, {validation.ref(), repair.ref()}),
        (replay, {regression.ref(), subject_release.ref()}),
        (review, {replay.ref()}),
        (aar, {
            subject_release.ref(), defect.ref(), validation.ref(), repair.ref(),
            regression.ref(), replay.ref(), review.ref(),
        }),
    )
    if any(refs(item) != expected for item, expected in expected_topology):
        raise LearningClosureError("learning_topology_mismatch")

    for item in items:
        payload = item.payload
        if (
            payload.get("subject_task_id") != subject.task.task_id
            or payload.get("subject_source_identity") != subject.source.identity_digest
            or payload.get("subject_graph_identity") != subject.graph.identity_digest
            or payload.get("subject_release_digest") != subject_release.artifact_digest
            or payload.get("defect_id") != DEFECT_ID
        ):
            raise LearningClosureError("subject_identity_binding_mismatch")

    if validation.payload.get("expected_failures") != dict(HISTORICAL_REGRESSION_CASES):
        raise LearningClosureError("regression_plan_mismatch")
    if validation.payload.get("regression_ids") != list(HISTORICAL_REGRESSION_CASES):
        raise LearningClosureError("regression_plan_mismatch")
    if repair.payload.get("repair_layer") != REPAIR_LAYER or repair.payload.get("repair_source_identity") != learning_source_identity:
        raise LearningClosureError("repair_layer_binding_mismatch")
    if regression.status != "PASS" or regression.payload.get("red_test_receipt_digest") != RED_TEST_RECEIPT_DIGEST:
        raise LearningClosureError("regression_result_mismatch")

    replay_values = replay.payload.get("cases")
    expected_replay = [
        {
            "case_id": case_id,
            "expected_error": expected,
            "observed_error": expected,
            "status": "PASS",
        }
        for case_id, expected in HISTORICAL_REGRESSION_CASES.items()
    ]
    if (
        replay.status != "PASS"
        or replay_values != expected_replay
        or replay.payload.get("replay_kind") != "local_historical_defect_replay"
        or replay.payload.get("formal_quantengine_replay_authority") is not False
    ):
        raise LearningClosureError("historical_replay_mismatch")

    if (
        review.status != "PASS"
        or review.payload.get("reviewer_identity") != reviewer_identity
        or reviewer_identity in _INDEPENDENCE_FORBIDDEN
        or review.payload.get("independent_from") != sorted(_INDEPENDENCE_FORBIDDEN)
        or review.payload.get("reviewed_regression_digest") != regression.artifact_digest
        or review.payload.get("reviewed_replay_digest") != replay.artifact_digest
        or review.payload.get("promotion_decision") != PROMOTION_DECISION
    ):
        raise LearningClosureError("independent_promotion_review_required")

    expected_aar_bindings = {
        "regression_plan_digest": validation.artifact_digest,
        "repair_manifest_digest": repair.artifact_digest,
        "regression_result_digest": regression.artifact_digest,
        "historical_replay_digest": replay.artifact_digest,
        "promotion_review_digest": review.artifact_digest,
    }
    if any(aar.payload.get(key) != value for key, value in expected_aar_bindings.items()):
        raise LearningClosureError("aar_digest_binding_mismatch")
    if (
        aar.status != "PASS"
        or aar.payload.get("repair_layer") != REPAIR_LAYER
        or aar.payload.get("promotion_decision") != PROMOTION_DECISION
        or aar.payload.get("red_test_receipt_digest") != RED_TEST_RECEIPT_DIGEST
        or any(aar.authority.values())
    ):
        raise LearningClosureError("aar_promotion_mismatch")
    return aar


__all__ = [
    "DEFECT_ID",
    "HISTORICAL_REGRESSION_CASES",
    "LearningClosureError",
    "LearningClosureResult",
    "PROMOTION_DECISION",
    "RED_TEST_RECEIPT_DIGEST",
    "REPAIR_LAYER",
    "RegressionReplay",
    "execute_learning_closure",
    "replay_historical_release_attacks",
    "verify_learning_closure",
]
