"""DEC-0032 M1: red tests for public OGSM V2 goal control.

The production module intentionally does not exist in M1. Each test names one
required fail-closed behavior so M2 can add the smallest possible contract and
validator without inventing workflow orchestration.
"""

from __future__ import annotations

from importlib import import_module

import pytest

from ogsm_v2_fixtures import (
    measure_verdict_payload,
    objective_contract_payload,
    objective_review_payload,
)


def ogsm_api():
    """Load the intentionally absent M2 surface at test execution time."""
    return import_module("quantengine_public.agent_platform.ogsm_v2")


def accepted_contract(api):
    return api.ObjectiveContract.from_dict(objective_contract_payload())


def test_rejects_objective_contract_without_owner_acceptance():
    api = ogsm_api()
    with pytest.raises(api.OgsmValidationError, match="objective_not_accepted"):
        api.validate_objective_contract(
            api.ObjectiveContract.from_dict(objective_contract_payload(status="PROPOSED")),
            api.ObjectiveReviewReceipt.from_dict(objective_review_payload()),
        )


def test_rejects_in_place_objective_change_without_new_revision_and_parent_digest():
    api = ogsm_api()
    previous = accepted_contract(api)
    changed = api.ObjectiveContract.from_dict(
        objective_contract_payload(
            objective="Replace release evidence with a different outcome without a revision."
        )
    )
    with pytest.raises(api.OgsmValidationError, match="objective_change_requires_new_revision"):
        api.validate_objective_change(previous, changed, invalidated_dependencies=())


def test_rejects_strategy_that_references_a_missing_goal():
    api = ogsm_api()
    payload = objective_contract_payload(
        strategies=[
            {
                "strategy_id": "strategy-orphan",
                "statement": "This strategy has no valid goal.",
                "supports_goal_ids": ["goal-does-not-exist"],
            }
        ]
    )
    with pytest.raises(api.OgsmValidationError, match="strategy_goal_reference_invalid"):
        api.ObjectiveContract.from_dict(payload)


@pytest.mark.parametrize(
    "missing_field",
    ["evidence_sources", "sample_and_horizon", "pass_rule", "decision_consequence"],
)
def test_rejects_measure_without_required_evidence_or_decision_metadata(missing_field: str):
    api = ogsm_api()
    measure = objective_contract_payload()["measures"][0]
    measure.pop(missing_field)
    with pytest.raises(api.OgsmValidationError, match="measure_metadata_required"):
        api.ObjectiveContract.from_dict(objective_contract_payload(measures=[measure]))


def test_rejects_objective_review_missing_a_required_pass_or_containing_blocked_verdict():
    api = ogsm_api()
    with pytest.raises(api.OgsmValidationError, match="objective_review_incomplete"):
        api.ObjectiveReviewReceipt.from_dict(objective_review_payload(omit_pass=1))
    with pytest.raises(api.OgsmValidationError, match="objective_review_blocked"):
        api.validate_objective_contract(
            accepted_contract(api),
            api.ObjectiveReviewReceipt.from_dict(objective_review_payload(blocked=True)),
        )


def test_rejects_task_bound_to_a_superseded_objective_contract():
    api = ogsm_api()
    old = accepted_contract(api)
    current = api.ObjectiveContract.from_dict(
        objective_contract_payload(revision=2, parent_digest=old.contract_digest)
    )
    with pytest.raises(api.OgsmValidationError, match="objective_contract_stale"):
        api.validate_downstream_binding(
            accepted_contract=current,
            task_objective_digest=old.contract_digest,
            run_objective_digest=current.contract_digest,
            handoff_objective_digest=current.contract_digest,
            release_objective_digest=current.contract_digest,
        )


def test_rejects_run_or_handoff_bound_to_a_different_objective_contract_digest():
    api = ogsm_api()
    contract = accepted_contract(api)
    with pytest.raises(api.OgsmValidationError, match="objective_binding_mismatch"):
        api.validate_downstream_binding(
            accepted_contract=contract,
            task_objective_digest=contract.contract_digest,
            run_objective_digest="b" * 64,
            handoff_objective_digest="c" * 64,
            release_objective_digest=contract.contract_digest,
        )


def test_rejects_pass_measure_verdict_that_consumes_excluded_evidence():
    api = ogsm_api()
    contract = accepted_contract(api)
    verdict = api.MeasureVerdict.from_dict(measure_verdict_payload(contract.to_dict()))
    with pytest.raises(api.OgsmValidationError, match="excluded_evidence_cannot_pass"):
        api.validate_measure_verdict(
            contract,
            verdict,
            evidence_classifications={"a" * 64: "EXCLUDED"},
        )


def test_rejects_missing_evidence_represented_as_zero_or_pass():
    api = ogsm_api()
    contract = accepted_contract(api)
    verdict = api.MeasureVerdict.from_dict(
        measure_verdict_payload(
            contract.to_dict(),
            evidence_digests=[],
            observed_value="0",
        )
    )
    with pytest.raises(api.OgsmValidationError, match="missing_evidence_requires_gap"):
        api.validate_measure_verdict(contract, verdict, evidence_classifications={})


def test_rejects_proposed_chat_idea_from_entering_approved_scope():
    api = ogsm_api()
    proposed = api.ObjectiveContract.from_dict(objective_contract_payload(status="PROPOSED"))
    with pytest.raises(api.OgsmValidationError, match="objective_not_accepted"):
        api.validate_downstream_binding(
            accepted_contract=proposed,
            task_objective_digest=proposed.contract_digest,
            run_objective_digest=proposed.contract_digest,
            handoff_objective_digest=proposed.contract_digest,
            release_objective_digest=proposed.contract_digest,
        )


def test_rejects_accepted_change_that_omits_invalidation_of_dependent_work():
    api = ogsm_api()
    old = accepted_contract(api)
    current = api.ObjectiveContract.from_dict(
        objective_contract_payload(revision=2, parent_digest=old.contract_digest)
    )
    receipt = api.ObjectiveChangeReceipt(
        previous_contract_digest=old.contract_digest,
        new_contract_digest=current.contract_digest,
        changed_fields=("objective",),
        owner_rationale="The old outcome no longer matches the accepted need.",
        cause_refs=("d" * 64,),
        invalidated_dependencies=(),
        reusable_evidence=(),
        owner="Owner",
        accepted_at="2026-08-28T00:00:00Z",
    )
    with pytest.raises(api.OgsmValidationError, match="objective_change_invalidation_required"):
        api.validate_objective_change(old, current, change_receipt=receipt)


def test_rejects_adopt_aar_that_omits_a_retained_failure_or_regression_receipt():
    api = ogsm_api()
    contract = accepted_contract(api)
    with pytest.raises(api.OgsmValidationError, match="aar_retained_failure_required"):
        api.validate_aar(
            {
                "schema_version": "public_delivery.aar.v2",
                "objective_contract_digest": contract.contract_digest,
                "decision": "ADOPT",
                "measure_verdict_digests": ["e" * 64],
                "retained_failure_refs": [],
                "regression_refs": [],
                "owner": "Owner",
            }
        )


def test_rejects_release_verdict_derived_from_another_objective_revision():
    api = ogsm_api()
    contract = accepted_contract(api)
    with pytest.raises(api.OgsmValidationError, match="objective_binding_mismatch"):
        api.validate_downstream_binding(
            accepted_contract=contract,
            task_objective_digest=contract.contract_digest,
            run_objective_digest=contract.contract_digest,
            handoff_objective_digest=contract.contract_digest,
            release_objective_digest="f" * 64,
        )


def test_rejects_capacity_overrun_without_an_accepted_change_receipt():
    api = ogsm_api()
    contract = accepted_contract(api)
    with pytest.raises(api.OgsmValidationError, match="capacity_constraint_exceeded"):
        api.validate_wip(contract, active_task_lineages=2, accepted_change_receipt=None)
