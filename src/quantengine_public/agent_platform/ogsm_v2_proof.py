"""Deterministic, domain-neutral public proof for the OGSM V2 control slice."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from quantengine_public.delivery.identity import (
    artifact_ref,
    seal_artifact,
    verify_artifact,
    verify_artifact_chain,
)

from .contracts import (
    ArtifactRef,
    GraphIdentity,
    HandoffReceipt,
    SourceIdentity,
    TaskSnapshot,
    content_digest,
)
from .ogsm_v2 import (
    MeasureVerdict,
    ObjectiveChangeReceipt,
    ObjectiveContract,
    ObjectiveReviewReceipt,
    OgsmValidationError,
    validate_aar,
    validate_downstream_binding,
    validate_measure_verdict,
    validate_objective_change,
    validate_objective_contract,
    validate_wip,
)
from .vertical_slice import SliceArtifact, derive_release


PROOF_SCHEMA = "public_delivery.ogsm_v2_proof.v1"
PROOF_SECTIONS = (
    "00_outcome_card",
    "01_objective_review",
    "02_objective_contract",
    "03_task_snapshot",
    "04_architecture_packet",
    "05_validation_plan",
    "06_development_handoff",
    "07_patch_manifest",
    "08_test_result",
    "09_ops_plan",
    "10_runtime_evidence",
    "11_quality_verdict",
    "12_release_verdict",
    "13_measure_verdicts",
    "14_aar",
    "15_owner_decision",
)
ATTACK_IDS = (
    "objective_not_owner_accepted",
    "objective_changed_without_revision",
    "strategy_references_missing_goal",
    "measure_metadata_missing",
    "objective_review_blocked",
    "task_binds_superseded_objective",
    "run_or_handoff_objective_mismatch",
    "pass_consumes_excluded_evidence",
    "missing_evidence_claimed_as_pass",
    "proposed_scope_without_owner_acceptance",
    "accepted_change_omits_invalidation",
    "aar_adopt_omits_retained_failure",
    "release_binds_different_objective",
    "capacity_exceeded_without_change_receipt",
)
_ATTACK_STAGES = (
    "objective_gate",
    "revision_gate",
    "strategy_gate",
    "measure_gate",
    "review_gate",
    "task_gate",
    "run_handoff_gate",
    "measure_gate",
    "evidence_gate",
    "scope_gate",
    "invalidation_gate",
    "aar_gate",
    "release_gate",
    "capacity_gate",
)
_ATTACK_CODES = (
    "objective_not_accepted",
    "objective_change_requires_new_revision",
    "strategy_goal_reference_invalid",
    "measure_metadata_required",
    "objective_review_blocked",
    "objective_contract_stale",
    "objective_binding_mismatch",
    "excluded_evidence_cannot_pass",
    "missing_evidence_requires_gap",
    "proposed_scope_without_owner_acceptance",
    "objective_change_invalidation_required",
    "aar_retained_failure_required",
    "objective_binding_mismatch",
    "capacity_constraint_exceeded",
)
_ATTACK_PRODUCERS = (
    "owner_fixture",
    "owner_fixture",
    "owner_fixture",
    "public_quality_shield",
    "owner_fixture",
    "owner_fixture",
    "public_development_agent",
    "public_quality_shield",
    "public_quality_shield",
    "owner_fixture",
    "owner_fixture",
    "public_quality_shield",
    "public_release_controller",
    "owner_fixture",
)
_ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}


class PublicOgsmV2ProofError(ValueError):
    """Raised when committed OGSM V2 proof bytes do not rederive."""


def _review_payload(*, blocked: bool = False) -> dict[str, Any]:
    body = {
        "schema_version": "public_delivery.objective_review.v1",
        "review_id": "review-ogsm-v2-golden-path",
        "contract_id": "objective-contract-golden-path",
        "passes": [
            {
                "pass_id": "outcome_fit",
                "verdict": "PASS_AFTER_REVISION",
                "findings": ["Document production alone cannot satisfy the outcome."],
                "revisions": ["Require executable stale-work rejection."],
                "residual_warnings": [],
            },
            {
                "pass_id": "evidence_goodhart",
                "verdict": "PASS_AFTER_REVISION",
                "findings": ["A PASS must not consume missing or excluded evidence."],
                "revisions": ["Bind verdicts to classified immutable evidence."],
                "residual_warnings": [],
            },
            {
                "pass_id": "capacity_authority_minimalism",
                "verdict": "BLOCKED" if blocked else "PASS_AFTER_REVISION",
                "findings": ["One lineage and no new service are sufficient."],
                "revisions": ["Keep acceptance and consequential authority with the Owner."],
                "residual_warnings": [],
            },
        ],
        "reviewer": "public-ogsm-control",
        "reviewed_at": "2026-08-28T00:00:00Z",
    }
    return {**body, "review_receipt_digest": content_digest(body)}


def _contract_payload(
    *,
    status: str = "ACCEPTED",
    revision: int = 1,
    parent_digest: str | None = None,
    objective: str = "Reduce false release acceptance by blocking stale or incomplete evidence.",
    review: Mapping[str, Any] | None = None,
    strategies: list[dict[str, Any]] | None = None,
    measures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    review_value = dict(review or _review_payload())
    body = {
        "schema_version": "public_delivery.objective_contract.v2",
        "contract_id": "objective-contract-golden-path",
        "revision": revision,
        "parent_digest": parent_digest,
        "status": status,
        "owner": "Owner",
        "accepted_at": "2026-08-28T00:00:00Z" if status == "ACCEPTED" else None,
        "outcome_card": {
            "problem": "A valid-looking delivery can optimize the wrong objective.",
            "alternatives": ["document completion", "stale-evidence rejection"],
            "selected_outcome": "stale-evidence rejection",
            "selection_reason": "It is independently observable and fail-closed.",
        },
        "objective": objective,
        "goals": [{"goal_id": "goal-release-correctness", "statement": "Release consumes only current admissible evidence."}],
        "strategies": strategies if strategies is not None else [{
            "strategy_id": "strategy-bind-revisions",
            "statement": "Bind every downstream decision to one accepted contract digest.",
            "supports_goal_ids": ["goal-release-correctness"],
        }],
        "measures": measures if measures is not None else [{
            "measure_id": "measure-stale-rejection",
            "kind": "SAFETY",
            "statement": "A stale Objective digest never reaches release admission.",
            "formula_or_judgment_rule": "Every downstream digest equals the accepted contract digest.",
            "evidence_sources": ["task_snapshot", "run_result", "handoff_receipt", "release_verdict"],
            "sample_and_horizon": "Every bounded public delivery run.",
            "pass_rule": "All bindings equal the accepted digest.",
            "warn_rule": "No warning state; mismatch is unsafe.",
            "fail_rule": "Any mismatch blocks dependent work.",
            "decision_consequence": "Require a new accepted revision and rerun affected work.",
            "owner": "Owner",
        }],
        "evidence_boundary": {
            "admitted_classes": ["PRIMARY"],
            "supporting_classes": ["SUPPORTING"],
            "excluded_classes": ["EXCLUDED"],
        },
        "assumptions": ["The Owner accepts consequential objective changes explicitly."],
        "non_goals": ["Automatic objective acceptance", "production authority"],
        "capacity_constraints": {"max_active_task_lineages": 1},
        "review_receipt_digest": review_value["review_receipt_digest"],
    }
    return {**body, "contract_digest": content_digest(body)}


def _measure_payload(contract_digest: str, evidence_refs: list[str], *, verdict: str = "PASS") -> dict[str, Any]:
    body = {
        "schema_version": "public_delivery.measure_verdict.v1",
        "objective_contract_digest": contract_digest,
        "measure_id": "measure-stale-rejection",
        "evidence_refs": evidence_refs,
        "observed_value": "all downstream bindings matched",
        "verdict": verdict,
        "evaluator": "public-quality-shield",
        "evaluated_at": "2026-08-28T00:30:00Z",
        "decision_consequence": "Adopt only while the binding regression remains green.",
    }
    return {**body, "verdict_digest": content_digest(body)}


def _artifact(
    artifact_type: str,
    producer: str,
    status: str,
    upstream: list[dict[str, Any]],
    *,
    task: TaskSnapshot,
    source: SourceIdentity,
    graph: GraphIdentity,
    context_digest: str,
    stage: str,
) -> dict[str, Any]:
    return seal_artifact(
        artifact_type=artifact_type,
        producer=producer,
        status=status,
        upstream=[artifact_ref(item) for item in upstream],
        payload={
            "task_id": task.task_id,
            "source_identity": source.identity_digest,
            "graph_identity": graph.identity_digest,
            "context_digest": context_digest,
            "objective_contract_digest": task.objective_contract_digest,
            "stage": stage,
        },
        authority=deepcopy(_ZERO_AUTHORITY),
    )


def _positive_sections() -> tuple[dict[str, Any], list[dict[str, Any]], ObjectiveContract]:
    review_payload = _review_payload()
    review = ObjectiveReviewReceipt.from_dict(review_payload)
    contract_payload = _contract_payload(review=review_payload)
    contract = ObjectiveContract.from_dict(contract_payload)
    validate_objective_contract(contract, review)
    source = SourceIdentity("quantengine-public", "synthetic/ogsm-v2-golden-path", "a" * 40, "b" * 64)
    graph = GraphIdentity("ogsm-v2-golden-path-v1", source.commit, "c" * 64)
    task = TaskSnapshot(
        task_id="PUBLIC-OGSM-V2-001",
        task_revision="objective-r1",
        objective=contract.objective,
        measures=("stale Objective bindings fail closed",),
        acceptance_criteria=("positive path rederives", "fourteen attacks block"),
        non_goals=("network model call", "deployment", "Paper", "Replay", "Real"),
        approved_scope=("public domain-neutral fixture",),
        required_approvals=("Owner:synthetic-fixture",),
        source_reference=source.identity_digest,
        objective_contract_digest=contract.contract_digest,
    )
    contexts = {name: content_digest({"task": task.snapshot_digest, "role": name, "objective": contract.contract_digest}) for name in ("architecture", "validation", "development", "test", "ops", "runtime", "quality")}
    architecture = _artifact("public_delivery.architecture_packet", "public_architecture_agent", "READY", [], task=task, source=source, graph=graph, context_digest=contexts["architecture"], stage="architecture")
    validation = _artifact("public_delivery.validation_plan", "public_test_agent", "READY", [architecture], task=task, source=source, graph=graph, context_digest=contexts["validation"], stage="validation")
    handoff = HandoffReceipt(
        task_id=task.task_id,
        task_version=2,
        from_owner="Test",
        to_role="Development",
        source_identity=source.identity_digest,
        context_digest=contexts["development"],
        required_artifact_refs=(ArtifactRef(**artifact_ref(architecture)), ArtifactRef(**artifact_ref(validation))),
        accepted_or_rejected="accepted",
        reason="Objective-bound validation is ready for implementation.",
        next_owner="Development",
        graph_identity=graph.identity_digest,
        objective_contract_digest=contract.contract_digest,
    )
    patch = _artifact("public_delivery.patch_manifest", "public_development_agent", "READY", [validation], task=task, source=source, graph=graph, context_digest=contexts["development"], stage="development")
    test = _artifact("public_delivery.test_result", "public_test_agent", "PASS", [validation, patch], task=task, source=source, graph=graph, context_digest=contexts["test"], stage="test")
    ops = _artifact("public_delivery.ops_plan", "public_ops_agent", "READY", [patch, test], task=task, source=source, graph=graph, context_digest=contexts["ops"], stage="ops")
    runtime = _artifact("public_delivery.runtime_evidence", "quantengine_public", "PASS", [test, ops], task=task, source=source, graph=graph, context_digest=contexts["runtime"], stage="runtime")
    quality = _artifact("public_delivery.quality_verdict", "public_quality_shield", "PASS", [runtime], task=task, source=source, graph=graph, context_digest=contexts["quality"], stage="quality")
    evidence = [architecture, validation, patch, test, ops, runtime, quality]
    release = derive_release(
        task_id=task.task_id,
        source_identity=source.identity_digest,
        graph_identity=graph.identity_digest,
        evidence=tuple(SliceArtifact.from_dict(item) for item in evidence),
        objective_contract_digest=contract.contract_digest,
    )
    positive_artifacts = [*evidence, release]
    verdict = _measure_payload(contract.contract_digest, [item["artifact_digest"] for item in positive_artifacts])
    validate_measure_verdict(
        contract,
        MeasureVerdict.from_dict(verdict),
        evidence_classifications={item["artifact_digest"]: "PRIMARY" for item in positive_artifacts},
    )
    aar = {
        "schema_version": "public_delivery.aar.v2",
        "objective_contract_digest": contract.contract_digest,
        "decision": "ADOPT",
        "measure_verdict_digests": [verdict["verdict_digest"]],
        "retained_failure_refs": ["d" * 64],
        "regression_refs": ["e" * 64],
        "owner": "Owner",
    }
    validate_aar(aar)
    aar_digest = content_digest(aar)
    owner_body = {
        "schema_version": "public_delivery.owner_decision.v1",
        "objective_contract_digest": contract.contract_digest,
        "aar_digest": aar_digest,
        "decision": "ADOPT",
        "owner": "Owner",
        "authority": deepcopy(_ZERO_AUTHORITY),
    }
    owner_decision = {**owner_body, "decision_digest": content_digest(owner_body)}
    sections = {
        "00_outcome_card": deepcopy(contract_payload["outcome_card"]),
        "01_objective_review": review.to_dict(),
        "02_objective_contract": contract.to_dict(),
        "03_task_snapshot": task.to_dict(),
        "04_architecture_packet": architecture,
        "05_validation_plan": validation,
        "06_development_handoff": handoff.to_dict(),
        "07_patch_manifest": patch,
        "08_test_result": test,
        "09_ops_plan": ops,
        "10_runtime_evidence": runtime,
        "11_quality_verdict": quality,
        "12_release_verdict": release,
        "13_measure_verdicts": [verdict],
        "14_aar": {**aar, "aar_digest": aar_digest},
        "15_owner_decision": owner_decision,
    }
    return sections, positive_artifacts, contract


def _reseal(value: Mapping[str, Any], digest_field: str) -> dict[str, Any]:
    body = {key: deepcopy(item) for key, item in value.items() if key != digest_field}
    return {**body, digest_field: content_digest(body)}


def _expect_attack(call: Callable[[], None], expected_code: str) -> str:
    try:
        call()
    except OgsmValidationError as exc:
        if exc.code != expected_code:
            raise PublicOgsmV2ProofError(f"attack_wrong_code:{expected_code}:{exc.code}") from exc
        return exc.code
    raise PublicOgsmV2ProofError(f"attack_did_not_block:{expected_code}")


def _admit_proposed_scope(contract: ObjectiveContract) -> None:
    if contract.status != "ACCEPTED":
        raise OgsmValidationError("proposed_scope_without_owner_acceptance")


def _attack_calls(contract: ObjectiveContract) -> list[Callable[[], None]]:
    review = ObjectiveReviewReceipt.from_dict(_review_payload())
    proposed = ObjectiveContract.from_dict(_contract_payload(status="PROPOSED"))
    changed_without_revision = ObjectiveContract.from_dict(_contract_payload(objective="Changed without a new revision."))
    bad_strategy = _contract_payload(strategies=[{"strategy_id": "bad", "statement": "Bad reference.", "supports_goal_ids": ["missing"]}])
    bad_strategy = _reseal(bad_strategy, "contract_digest")
    bad_measures = deepcopy(_contract_payload()["measures"])
    bad_measures[0].pop("sample_and_horizon")
    bad_measure = _reseal(_contract_payload(measures=bad_measures), "contract_digest")
    blocked_review_payload = _review_payload(blocked=True)
    blocked_review = ObjectiveReviewReceipt.from_dict(blocked_review_payload)
    blocked_contract = ObjectiveContract.from_dict(_contract_payload(review=blocked_review_payload))
    current = ObjectiveContract.from_dict(_contract_payload(revision=2, parent_digest=contract.contract_digest))
    excluded_verdict = MeasureVerdict.from_dict(_measure_payload(contract.contract_digest, ["f" * 64]))
    missing_verdict = MeasureVerdict.from_dict(_measure_payload(contract.contract_digest, []))
    changed = ObjectiveContract.from_dict(_contract_payload(revision=2, parent_digest=contract.contract_digest, objective="Accepted revision requires invalidation."))
    no_invalidation = ObjectiveChangeReceipt(
        previous_contract_digest=contract.contract_digest,
        new_contract_digest=changed.contract_digest,
        changed_fields=("objective",),
        owner_rationale="Accepted change.",
        cause_refs=("1" * 64,),
        invalidated_dependencies=(),
        reusable_evidence=(),
        owner="Owner",
        accepted_at="2026-08-28T01:00:00Z",
    )
    bad_aar = {
        "schema_version": "public_delivery.aar.v2",
        "objective_contract_digest": contract.contract_digest,
        "decision": "ADOPT",
        "measure_verdict_digests": ["2" * 64],
        "retained_failure_refs": [],
        "regression_refs": [],
        "owner": "Owner",
    }
    return [
        lambda: validate_objective_contract(proposed, review),
        lambda: validate_objective_change(contract, changed_without_revision),
        lambda: ObjectiveContract.from_dict(bad_strategy),
        lambda: ObjectiveContract.from_dict(bad_measure),
        lambda: validate_objective_contract(blocked_contract, blocked_review),
        lambda: validate_downstream_binding(accepted_contract=current, task_objective_digest=contract.contract_digest, run_objective_digest=current.contract_digest, handoff_objective_digest=current.contract_digest, release_objective_digest=current.contract_digest),
        lambda: validate_downstream_binding(accepted_contract=contract, task_objective_digest=contract.contract_digest, run_objective_digest="3" * 64, handoff_objective_digest="4" * 64, release_objective_digest=contract.contract_digest),
        lambda: validate_measure_verdict(contract, excluded_verdict, evidence_classifications={"f" * 64: "EXCLUDED"}),
        lambda: validate_measure_verdict(contract, missing_verdict, evidence_classifications={}),
        lambda: _admit_proposed_scope(proposed),
        lambda: validate_objective_change(contract, changed, change_receipt=no_invalidation),
        lambda: validate_aar(bad_aar),
        lambda: validate_downstream_binding(accepted_contract=contract, task_objective_digest=contract.contract_digest, run_objective_digest=contract.contract_digest, handoff_objective_digest=contract.contract_digest, release_objective_digest="5" * 64),
        lambda: validate_wip(contract, active_task_lineages=2, accepted_change_receipt=None),
    ]


def _attacks(contract: ObjectiveContract) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for attack_id, stage, expected_code, producer, call in zip(
        ATTACK_IDS,
        _ATTACK_STAGES,
        _ATTACK_CODES,
        _ATTACK_PRODUCERS,
        _attack_calls(contract),
        strict=True,
    ):
        observed_code = _expect_attack(call, expected_code)
        request = {"attack_id": attack_id, "declared_stage": stage, "expected_code": expected_code}
        receipt = seal_artifact(
            artifact_type="public_delivery.block_receipt",
            producer=producer,
            status="EVIDENCE_GAP" if attack_id == "missing_evidence_claimed_as_pass" else "BLOCKED",
            upstream=[],
            payload={
                "attack_id": attack_id,
                "stage": stage,
                "reason": observed_code,
                "request_digest": content_digest(request),
                "objective_contract_digest": contract.contract_digest,
                "proof_role": "negative_only",
            },
            authority=deepcopy(_ZERO_AUTHORITY),
        )
        result.append({"attack_id": attack_id, "declared_stage": stage, "request": request, "block_receipt": receipt})
    return result


def _manifest(proof: Mapping[str, Any]) -> dict[str, Any]:
    sections = proof["sections"]
    attacks = proof["attacks"]
    body = {
        "schema_version": PROOF_SCHEMA,
        "proof_id": proof["proof_id"],
        "section_digests": {name: content_digest(sections[name]) for name in PROOF_SECTIONS},
        "positive_chain_digest": content_digest([item["artifact_digest"] for item in proof["positive_artifacts"]]),
        "attacks_digest": content_digest(attacks),
    }
    return {**body, "proof_digest": content_digest(body)}


def _bind_aar_to_attacks(sections: dict[str, Any], attacks: list[dict[str, Any]]) -> None:
    receipt_digests = [item["block_receipt"]["artifact_digest"] for item in attacks]
    aar = dict(sections["14_aar"])
    aar.pop("aar_digest", None)
    aar["retained_failure_refs"] = receipt_digests
    aar["regression_refs"] = receipt_digests
    validate_aar(aar)
    aar_digest = content_digest(aar)
    sections["14_aar"] = {**aar, "aar_digest": aar_digest}
    owner_body = {
        "schema_version": "public_delivery.owner_decision.v1",
        "objective_contract_digest": aar["objective_contract_digest"],
        "aar_digest": aar_digest,
        "decision": "ADOPT",
        "owner": "Owner",
        "authority": deepcopy(_ZERO_AUTHORITY),
    }
    sections["15_owner_decision"] = {**owner_body, "decision_digest": content_digest(owner_body)}


def build_public_ogsm_v2_proof() -> dict[str, Any]:
    sections, artifacts, contract = _positive_sections()
    attacks = _attacks(contract)
    _bind_aar_to_attacks(sections, attacks)
    proof: dict[str, Any] = {
        "schema_version": PROOF_SCHEMA,
        "proof_id": "public-ogsm-v2-golden-path",
        "execution": {"mode": "deterministic-domain-neutral-fixture", "network_model_calls": False},
        "authority": deepcopy(_ZERO_AUTHORITY),
        "sections": sections,
        "positive_artifacts": artifacts,
        "attacks": attacks,
    }
    proof["manifest"] = _manifest(proof)
    return proof


def verify_public_ogsm_v2_proof(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        proof = deepcopy(dict(value))
        if set(proof) != {"schema_version", "proof_id", "execution", "authority", "sections", "positive_artifacts", "attacks", "manifest"}:
            raise PublicOgsmV2ProofError("proof_fields_mismatch")
        if proof["schema_version"] != PROOF_SCHEMA or proof["authority"] != _ZERO_AUTHORITY:
            raise PublicOgsmV2ProofError("proof_identity_or_authority_mismatch")
        if proof["execution"] != {"mode": "deterministic-domain-neutral-fixture", "network_model_calls": False}:
            raise PublicOgsmV2ProofError("execution_identity_mismatch")
        sections = proof["sections"]
        if not isinstance(sections, dict) or tuple(sections) != PROOF_SECTIONS:
            raise PublicOgsmV2ProofError("proof_sections_mismatch")
        if proof["manifest"] != _manifest(proof):
            raise PublicOgsmV2ProofError("manifest_mismatch")
        review = ObjectiveReviewReceipt.from_dict(sections["01_objective_review"])
        contract = ObjectiveContract.from_dict(sections["02_objective_contract"])
        validate_objective_contract(contract, review)
        if sections["00_outcome_card"] != contract.to_dict()["outcome_card"]:
            raise PublicOgsmV2ProofError("outcome_card_binding_mismatch")
        task = TaskSnapshot.from_dict(sections["03_task_snapshot"])
        if task.objective_contract_digest != contract.contract_digest:
            raise PublicOgsmV2ProofError("task_objective_binding_mismatch")
        handoff = HandoffReceipt.from_dict(sections["06_development_handoff"])
        if handoff.objective_contract_digest != contract.contract_digest:
            raise PublicOgsmV2ProofError("handoff_objective_binding_mismatch")
        artifacts = proof["positive_artifacts"]
        if verify_artifact_chain(artifacts):
            raise PublicOgsmV2ProofError("positive_artifact_chain_invalid")
        if artifacts != [sections[name] for name in ("04_architecture_packet", "05_validation_plan", "07_patch_manifest", "08_test_result", "09_ops_plan", "10_runtime_evidence", "11_quality_verdict", "12_release_verdict")]:
            raise PublicOgsmV2ProofError("positive_section_binding_mismatch")
        for artifact in artifacts:
            if artifact["payload"].get("objective_contract_digest") != contract.contract_digest or artifact["authority"] != _ZERO_AUTHORITY:
                raise PublicOgsmV2ProofError("artifact_objective_or_authority_mismatch")
        release = derive_release(
            task_id=task.task_id,
            source_identity=artifacts[0]["payload"]["source_identity"],
            graph_identity=artifacts[0]["payload"]["graph_identity"],
            evidence=tuple(SliceArtifact.from_dict(item) for item in artifacts[:-1]),
            objective_contract_digest=contract.contract_digest,
        )
        if release != sections["12_release_verdict"]:
            raise PublicOgsmV2ProofError("release_not_rederived")
        classifications = {item["artifact_digest"]: "PRIMARY" for item in artifacts}
        verdicts = [MeasureVerdict.from_dict(item) for item in sections["13_measure_verdicts"]]
        for verdict in verdicts:
            validate_measure_verdict(contract, verdict, evidence_classifications=classifications)
        aar = dict(sections["14_aar"])
        supplied_aar_digest = aar.pop("aar_digest")
        if supplied_aar_digest != content_digest(aar):
            raise PublicOgsmV2ProofError("aar_digest_mismatch")
        validate_aar(aar)
        verdict_digests = [verdict.verdict_digest for verdict in verdicts]
        attack_digests = [item["block_receipt"]["artifact_digest"] for item in proof["attacks"]]
        if (
            aar["measure_verdict_digests"] != verdict_digests
            or aar["retained_failure_refs"] != attack_digests
            or aar["regression_refs"] != attack_digests
        ):
            raise PublicOgsmV2ProofError("aar_evidence_binding_mismatch")
        owner = dict(sections["15_owner_decision"])
        supplied_decision_digest = owner.pop("decision_digest")
        if supplied_decision_digest != content_digest(owner):
            raise PublicOgsmV2ProofError("owner_decision_digest_mismatch")
        if owner != {
            "schema_version": "public_delivery.owner_decision.v1",
            "objective_contract_digest": contract.contract_digest,
            "aar_digest": supplied_aar_digest,
            "decision": "ADOPT",
            "owner": "Owner",
            "authority": _ZERO_AUTHORITY,
        }:
            raise PublicOgsmV2ProofError("owner_decision_binding_mismatch")
        attacks = proof["attacks"]
        if tuple(item.get("attack_id") for item in attacks) != ATTACK_IDS:
            raise PublicOgsmV2ProofError("attack_inventory_mismatch")
        if attacks != _attacks(contract):
            raise PublicOgsmV2ProofError("attacks_not_rederived")
        for item, stage, code, producer in zip(
            attacks,
            _ATTACK_STAGES,
            _ATTACK_CODES,
            _ATTACK_PRODUCERS,
            strict=True,
        ):
            receipt = item["block_receipt"]
            if verify_artifact(receipt):
                raise PublicOgsmV2ProofError("attack_receipt_invalid")
            payload = receipt["payload"]
            if (
                item["declared_stage"] != stage
                or payload.get("stage") != stage
                or payload.get("reason") != code
                or payload.get("request_digest") != content_digest(item["request"])
                or payload.get("objective_contract_digest") != contract.contract_digest
                or payload.get("proof_role") != "negative_only"
                or receipt["producer"] != producer
                or receipt["authority"] != _ZERO_AUTHORITY
            ):
                raise PublicOgsmV2ProofError("attack_receipt_binding_mismatch")
        return deepcopy(proof["manifest"])
    except PublicOgsmV2ProofError:
        raise
    except Exception as exc:
        raise PublicOgsmV2ProofError(f"proof_invalid:{exc}") from exc


__all__ = [
    "ATTACK_IDS",
    "PROOF_SCHEMA",
    "PROOF_SECTIONS",
    "PublicOgsmV2ProofError",
    "build_public_ogsm_v2_proof",
    "verify_public_ogsm_v2_proof",
]
