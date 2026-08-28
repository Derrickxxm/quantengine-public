"""DEC-0038 M2 acceptance for the deterministic OGSM V2 contract surface."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ogsm_v2_fixtures import (
    measure_verdict_payload,
    objective_contract_payload,
    objective_review_payload,
)
from quantengine_public.agent_platform import (
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
from quantengine_public.agent_platform.contracts import content_digest


def _accepted_contract() -> ObjectiveContract:
    return ObjectiveContract.from_dict(objective_contract_payload())


def _reseal(payload: dict, digest_field: str) -> dict:
    body = {key: value for key, value in payload.items() if key != digest_field}
    return {**body, digest_field: content_digest(body)}


def _assert_block(code: str, call) -> None:
    with pytest.raises(OgsmValidationError, match=code) as captured:
        call()
    assert captured.value.code == code
    assert captured.value.receipt["code"] == code
    receipt = dict(captured.value.receipt)
    supplied = receipt.pop("receipt_digest")
    assert supplied == content_digest(receipt)


def test_round_trips_canonical_contract_review_and_measure_verdict():
    contract = _accepted_contract()
    review = ObjectiveReviewReceipt.from_dict(objective_review_payload())
    verdict = MeasureVerdict.from_dict(measure_verdict_payload(contract.to_dict()))

    assert ObjectiveContract.from_dict(contract.to_dict()) == contract
    assert ObjectiveReviewReceipt.from_dict(review.to_dict()) == review
    assert MeasureVerdict.from_dict(verdict.to_dict()) == verdict
    validate_objective_contract(contract, review)
    validate_measure_verdict(
        contract,
        verdict,
        evidence_classifications={"a" * 64: "PRIMARY"},
    )


def test_contract_payload_is_recursively_immutable_and_exports_a_copy():
    contract = _accepted_contract()

    with pytest.raises(TypeError):
        contract._body["objective"] = "mutated"
    with pytest.raises(AttributeError):
        contract._body["goals"].append({"goal_id": "forged"})

    exported = contract.to_dict()
    exported["goals"][0]["statement"] = "mutated copy"
    assert contract.to_dict()["goals"][0]["statement"] != "mutated copy"


@pytest.mark.parametrize(
    ("factory", "digest_field", "mutated_field", "expected_code"),
    [
        (objective_contract_payload, "contract_digest", "objective", "contract_digest_mismatch"),
        (objective_review_payload, "review_receipt_digest", "reviewer", "review_receipt_digest_mismatch"),
    ],
)
def test_rejects_tampered_canonical_contracts(
    factory,
    digest_field: str,
    mutated_field: str,
    expected_code: str,
):
    payload = factory()
    payload[mutated_field] = "tampered"
    parser = ObjectiveContract.from_dict if digest_field == "contract_digest" else ObjectiveReviewReceipt.from_dict

    _assert_block(expected_code, lambda: parser(payload))


def test_rejects_tampered_measure_verdict_digest():
    payload = measure_verdict_payload(objective_contract_payload())
    payload["observed_value"] = "tampered"

    _assert_block("verdict_digest_mismatch", lambda: MeasureVerdict.from_dict(payload))


def test_rejects_duplicate_ids_and_unclassified_evidence():
    payload = objective_contract_payload()
    payload["goals"].append(dict(payload["goals"][0]))
    payload = _reseal(payload, "contract_digest")
    _assert_block("goal_id_duplicate", lambda: ObjectiveContract.from_dict(payload))

    contract = _accepted_contract()
    verdict = MeasureVerdict.from_dict(measure_verdict_payload(contract.to_dict()))
    _assert_block(
        "evidence_classification_missing",
        lambda: validate_measure_verdict(contract, verdict, evidence_classifications={}),
    )


def test_accepts_bound_revision_change_and_capacity_receipt():
    previous = _accepted_contract()
    changed = ObjectiveContract.from_dict(
        objective_contract_payload(
            revision=2,
            parent_digest=previous.contract_digest,
            objective="Reject stale evidence and preserve one active task lineage.",
            capacity_constraints={"max_active_task_lineages": 2},
        )
    )
    receipt = ObjectiveChangeReceipt(
        previous_contract_digest=previous.contract_digest,
        new_contract_digest=changed.contract_digest,
        changed_fields=("objective", "capacity_constraints"),
        owner_rationale="The accepted outcome now includes a bounded second lineage.",
        cause_refs=("d" * 64,),
        invalidated_dependencies=("task-old",),
        reusable_evidence=("e" * 64,),
        owner="Owner",
        accepted_at="2026-08-28T00:10:00Z",
    )

    validate_objective_change(previous, changed, change_receipt=receipt)
    validate_wip(changed, active_task_lineages=2, accepted_change_receipt=receipt)
    validate_downstream_binding(
        accepted_contract=changed,
        task_objective_digest=changed.contract_digest,
        run_objective_digest=changed.contract_digest,
        handoff_objective_digest=changed.contract_digest,
        release_objective_digest=changed.contract_digest,
    )
    assert receipt.receipt_digest == content_digest(receipt.to_dict(include_digest=False))
    assert ObjectiveChangeReceipt.from_dict(receipt.to_dict()) == receipt

    _assert_block(
        "objective_change_owner_mismatch",
        lambda: validate_objective_change(
            previous,
            changed,
            change_receipt=replace(receipt, owner="different-owner"),
        ),
    )

    tampered = receipt.to_dict()
    tampered["owner_rationale"] = "tampered"
    _assert_block(
        "receipt_digest_mismatch",
        lambda: ObjectiveChangeReceipt.from_dict(tampered),
    )

    unrelated_capacity_receipt = replace(receipt, changed_fields=("objective",))
    over_capacity = ObjectiveContract.from_dict(
        objective_contract_payload(
            revision=2,
            parent_digest=previous.contract_digest,
            objective="Keep the original capacity while changing the objective.",
        )
    )
    unrelated_capacity_receipt = replace(
        unrelated_capacity_receipt,
        new_contract_digest=over_capacity.contract_digest,
    )
    _assert_block(
        "capacity_change_receipt_mismatch",
        lambda: validate_wip(
            over_capacity,
            active_task_lineages=2,
            accepted_change_receipt=unrelated_capacity_receipt,
        ),
    )


def test_rejects_proposed_contract_at_every_admission_entry():
    proposed = ObjectiveContract.from_dict(objective_contract_payload(status="PROPOSED"))
    previous = _accepted_contract()
    proposed_revision = ObjectiveContract.from_dict(
        objective_contract_payload(
            revision=2,
            parent_digest=previous.contract_digest,
            status="PROPOSED",
            objective="A proposed revision has no admission authority.",
        )
    )
    receipt = ObjectiveChangeReceipt(
        previous_contract_digest=previous.contract_digest,
        new_contract_digest=proposed_revision.contract_digest,
        changed_fields=("objective",),
        owner_rationale="This remains proposed.",
        cause_refs=("d" * 64,),
        invalidated_dependencies=("task-old",),
        reusable_evidence=(),
        owner="Owner",
        accepted_at="2026-08-28T00:10:00Z",
    )
    verdict = MeasureVerdict.from_dict(measure_verdict_payload(proposed.to_dict()))

    _assert_block(
        "objective_not_accepted",
        lambda: validate_objective_change(previous, proposed_revision, change_receipt=receipt),
    )
    _assert_block(
        "objective_not_accepted",
        lambda: validate_measure_verdict(
            proposed,
            verdict,
            evidence_classifications={"a" * 64: "PRIMARY"},
        ),
    )
    _assert_block(
        "objective_not_accepted",
        lambda: validate_wip(proposed, active_task_lineages=1, accepted_change_receipt=None),
    )


def test_accepts_evidence_bound_adopt_aar_and_gap_verdict():
    contract = _accepted_contract()
    gap = MeasureVerdict.from_dict(
        measure_verdict_payload(contract.to_dict(), verdict="EVIDENCE_GAP", evidence_digests=[])
    )

    validate_measure_verdict(contract, gap, evidence_classifications={})
    validate_aar(
        {
            "schema_version": "public_delivery.aar.v2",
            "objective_contract_digest": contract.contract_digest,
            "decision": "ADOPT",
            "measure_verdict_digests": [gap.verdict_digest],
            "retained_failure_refs": ["f" * 64],
            "regression_refs": ["1" * 64],
            "owner": "Owner",
        }
    )
