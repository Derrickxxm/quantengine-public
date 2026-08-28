"""Canonical public fixtures for the DEC-0037 OGSM V2 red suite.

These fixtures deliberately have no dependency on the implementation module.
They describe the public contract that M2 must admit or reject.
"""

from __future__ import annotations

from typing import Any

from quantengine_public.agent_platform.contracts import content_digest


def objective_review_payload(*, blocked: bool = False, omit_pass: int | None = None) -> dict[str, Any]:
    passes = [
        {
            "pass_id": "outcome_fit",
            "verdict": "PASS_AFTER_REVISION",
            "findings": ["Outcome cannot be satisfied by document production alone."],
            "revisions": ["Require stale-work rejection."],
            "residual_warnings": [],
        },
        {
            "pass_id": "evidence_goodhart",
            "verdict": "PASS_AFTER_REVISION",
            "findings": ["PASS must not consume excluded evidence."],
            "revisions": ["Classify evidence before verdict admission."],
            "residual_warnings": [],
        },
        {
            "pass_id": "capacity_authority_minimalism",
            "verdict": "BLOCKED" if blocked else "PASS_AFTER_REVISION",
            "findings": ["One task lineage and no new service."],
            "revisions": ["Keep Owner acceptance explicit."],
            "residual_warnings": [],
        },
    ]
    if omit_pass is not None:
        passes.pop(omit_pass)
    body = {
        "schema_version": "public_delivery.objective_review.v1",
        "review_id": "review-ogsm-v2-reference",
        "contract_id": "objective-contract-reference",
        "passes": passes,
        "reviewer": "public-ogsm-control",
        "reviewed_at": "2026-08-28T00:00:00Z",
    }
    return {**body, "review_receipt_digest": content_digest(body)}


def objective_contract_payload(
    *,
    revision: int = 1,
    parent_digest: str | None = None,
    status: str = "ACCEPTED",
    objective: str = "Reduce false release acceptance by blocking stale or incomplete evidence.",
    review: dict[str, Any] | None = None,
    strategies: list[dict[str, Any]] | None = None,
    measures: list[dict[str, Any]] | None = None,
    capacity_constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review = review or objective_review_payload()
    body = {
        "schema_version": "public_delivery.objective_contract.v2",
        "contract_id": "objective-contract-reference",
        "revision": revision,
        "parent_digest": parent_digest,
        "status": status,
        "owner": "Owner",
        "accepted_at": "2026-08-28T00:00:00Z" if status == "ACCEPTED" else None,
        "outcome_card": {
            "problem": "A valid-looking delivery can still optimize the wrong objective.",
            "alternatives": ["document completion", "stale-evidence rejection"],
            "selected_outcome": "stale-evidence rejection",
            "selection_reason": "It is independently observable and fail-closed.",
        },
        "objective": objective,
        "goals": [
            {
                "goal_id": "goal-release-correctness",
                "statement": "A released verdict consumes only current, admissible evidence.",
            }
        ],
        "strategies": strategies if strategies is not None else [
            {
                "strategy_id": "strategy-bind-revisions",
                "statement": "Bind every downstream decision to one accepted contract digest.",
                "supports_goal_ids": ["goal-release-correctness"],
            }
        ],
        "measures": measures if measures is not None else [
            {
                "measure_id": "measure-stale-rejection",
                "kind": "SAFETY",
                "statement": "A stale Objective Contract digest never reaches release admission.",
                "formula_or_judgment_rule": "Every downstream digest equals the accepted contract digest.",
                "evidence_sources": ["task_snapshot", "run_result", "handoff_receipt", "release_verdict"],
                "sample_and_horizon": "Every bounded public delivery run.",
                "pass_rule": "All bindings equal the accepted digest.",
                "warn_rule": "No warning state; mismatch is unsafe.",
                "fail_rule": "Any mismatch blocks the dependent work.",
                "decision_consequence": "Require a new accepted revision and rerun affected work.",
                "owner": "Owner",
            }
        ],
        "evidence_boundary": {
            "admitted_classes": ["PRIMARY"],
            "supporting_classes": ["SUPPORTING"],
            "excluded_classes": ["EXCLUDED"],
        },
        "assumptions": ["The Owner accepts consequential objective changes explicitly."],
        "non_goals": ["Automatic objective acceptance", "production authority"],
        "capacity_constraints": (
            capacity_constraints
            if capacity_constraints is not None
            else {"max_active_task_lineages": 1}
        ),
        "review_receipt_digest": review["review_receipt_digest"],
    }
    return {**body, "contract_digest": content_digest(body)}


def measure_verdict_payload(
    contract: dict[str, Any],
    *,
    verdict: str = "PASS",
    evidence_digests: list[str] | None = None,
    observed_value: str = "all bindings matched",
) -> dict[str, Any]:
    body = {
        "schema_version": "public_delivery.measure_verdict.v1",
        "objective_contract_digest": contract["contract_digest"],
        "measure_id": "measure-stale-rejection",
        "evidence_refs": ["a" * 64] if evidence_digests is None else evidence_digests,
        "observed_value": observed_value,
        "verdict": verdict,
        "evaluator": "quality-shield",
        "evaluated_at": "2026-08-28T00:00:00Z",
        "decision_consequence": "Require a new accepted revision and rerun affected work.",
    }
    return {**body, "verdict_digest": content_digest(body)}
