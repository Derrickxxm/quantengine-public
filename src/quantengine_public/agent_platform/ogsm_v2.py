"""Deterministic contracts for the public OGSM V2 goal-control slice.

This module validates structure, identity, references, and admission state. It
does not select objectives, judge business value, or grant execution authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contracts import canonical_json, content_digest


OBJECTIVE_SCHEMA = "public_delivery.objective_contract.v2"
REVIEW_SCHEMA = "public_delivery.objective_review.v1"
MEASURE_VERDICT_SCHEMA = "public_delivery.measure_verdict.v1"
BLOCK_RECEIPT_SCHEMA = "public_delivery.ogsm_block_receipt.v1"
CHANGE_RECEIPT_SCHEMA = "public_delivery.objective_change_receipt.v1"
AAR_SCHEMA = "public_delivery.aar.v2"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_PASSES = {
    "outcome_fit",
    "evidence_goodhart",
    "capacity_authority_minimalism",
}
_REVIEW_VERDICTS = {"PASS", "PASS_AFTER_REVISION", "BLOCKED"}
_OBJECTIVE_STATUSES = {"PROPOSED", "ACCEPTED", "SUPERSEDED", "ABANDONED"}
_MEASURE_KINDS = {"LEADING", "INTERMEDIATE", "LAGGING", "SAFETY", "LEARNING"}
_MEASURE_VERDICTS = {"PASS", "WARN", "FAIL", "EVIDENCE_GAP"}
_EVIDENCE_CLASSES = {"PRIMARY", "SUPPORTING", "EXCLUDED"}
_AAR_DECISIONS = {"ADOPT", "ADJUST", "ABANDON", "GATHER_MORE_EVIDENCE"}


class OgsmValidationError(ValueError):
    """A typed fail-closed OGSM admission error."""

    def __init__(self, code: str):
        self.code = code
        body = {
            "schema_version": BLOCK_RECEIPT_SCHEMA,
            "blocked": True,
            "code": code,
        }
        self.receipt = {**body, "receipt_digest": content_digest(body)}
        super().__init__(code)


def _block(code: str) -> None:
    raise OgsmValidationError(code)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(_thaw(value)))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _block(code)
    return _clone(dict(value))


def _text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _block(code)
    return value


def _digest(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _block(code)
    return value


def _rows(value: Any, code: str, *, allow_empty: bool = False) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        _block(code)
    if not allow_empty and not value:
        _block(code)
    return value


def _text_rows(value: Any, code: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    rows = _rows(value, code, allow_empty=allow_empty)
    return tuple(_text(item, code) for item in rows)


def _verified_body(value: Mapping[str, Any], *, schema: str, digest_field: str) -> tuple[dict[str, Any], str]:
    data = _mapping(value, "contract_mapping_required")
    if data.get("schema_version") != schema:
        _block("schema_version_mismatch")
    supplied = _digest(data.pop(digest_field, None), f"{digest_field}_invalid")
    if supplied != content_digest(data):
        _block(f"{digest_field}_mismatch")
    return data, supplied


@dataclass(frozen=True, slots=True)
class ObjectiveReviewReceipt:
    _body: Mapping[str, Any]
    review_receipt_digest: str

    @property
    def contract_id(self) -> str:
        return self._body["contract_id"]

    @property
    def passes(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(MappingProxyType(_clone(row)) for row in self._body["passes"])

    def to_dict(self) -> dict[str, Any]:
        return {**_clone(self._body), "review_receipt_digest": self.review_receipt_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObjectiveReviewReceipt":
        body, supplied = _verified_body(
            value,
            schema=REVIEW_SCHEMA,
            digest_field="review_receipt_digest",
        )
        for name in ("review_id", "contract_id", "reviewer", "reviewed_at"):
            _text(body.get(name), f"{name}_required")
        passes = _rows(body.get("passes"), "objective_review_incomplete")
        ids: list[str] = []
        for raw in passes:
            row = _mapping(raw, "objective_review_incomplete")
            pass_id = _text(row.get("pass_id"), "objective_review_incomplete")
            verdict = _text(row.get("verdict"), "objective_review_incomplete")
            if verdict not in _REVIEW_VERDICTS:
                _block("objective_review_verdict_invalid")
            for name in ("findings", "revisions", "residual_warnings"):
                _text_rows(row.get(name), "objective_review_incomplete", allow_empty=True)
            ids.append(pass_id)
        if set(ids) != _REVIEW_PASSES or len(ids) != len(_REVIEW_PASSES):
            _block("objective_review_incomplete")
        return cls(_freeze(body), supplied)


@dataclass(frozen=True, slots=True)
class ObjectiveContract:
    _body: Mapping[str, Any]
    contract_digest: str

    @property
    def contract_id(self) -> str:
        return self._body["contract_id"]

    @property
    def revision(self) -> int:
        return self._body["revision"]

    @property
    def parent_digest(self) -> str | None:
        return self._body["parent_digest"]

    @property
    def status(self) -> str:
        return self._body["status"]

    @property
    def objective(self) -> str:
        return self._body["objective"]

    @property
    def owner(self) -> str:
        return self._body["owner"]

    @property
    def review_receipt_digest(self) -> str:
        return self._body["review_receipt_digest"]

    @property
    def measure_ids(self) -> frozenset[str]:
        return frozenset(row["measure_id"] for row in self._body["measures"])

    @property
    def max_active_task_lineages(self) -> int:
        return self._body["capacity_constraints"]["max_active_task_lineages"]

    def to_dict(self) -> dict[str, Any]:
        return {**_clone(self._body), "contract_digest": self.contract_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObjectiveContract":
        body, supplied = _verified_body(
            value,
            schema=OBJECTIVE_SCHEMA,
            digest_field="contract_digest",
        )
        _validate_contract_body(body)
        return cls(_freeze(body), supplied)


def _validate_contract_body(body: dict[str, Any]) -> None:
    for name in ("contract_id", "owner", "objective"):
        _text(body.get(name), f"{name}_required")
    revision = body.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        _block("objective_revision_invalid")
    parent = body.get("parent_digest")
    if revision == 1:
        if parent is not None:
            _block("objective_parent_digest_invalid")
    else:
        _digest(parent, "objective_parent_digest_invalid")
    status = body.get("status")
    if status not in _OBJECTIVE_STATUSES:
        _block("objective_status_invalid")
    if status == "ACCEPTED":
        _text(body.get("accepted_at"), "accepted_at_required")
    elif body.get("accepted_at") is not None:
        _block("accepted_at_requires_accepted_status")

    outcome = _mapping(body.get("outcome_card"), "outcome_card_required")
    for name in ("problem", "selected_outcome", "selection_reason"):
        _text(outcome.get(name), "outcome_card_required")
    _text_rows(outcome.get("alternatives"), "outcome_card_required")

    goals = _rows(body.get("goals"), "goal_required")
    goal_ids: list[str] = []
    for raw in goals:
        row = _mapping(raw, "goal_invalid")
        goal_ids.append(_text(row.get("goal_id"), "goal_invalid"))
        _text(row.get("statement"), "goal_invalid")
    if len(goal_ids) != len(set(goal_ids)):
        _block("goal_id_duplicate")

    strategies = _rows(body.get("strategies"), "strategy_required")
    strategy_ids: list[str] = []
    for raw in strategies:
        row = _mapping(raw, "strategy_invalid")
        strategy_ids.append(_text(row.get("strategy_id"), "strategy_invalid"))
        _text(row.get("statement"), "strategy_invalid")
        references = _text_rows(row.get("supports_goal_ids"), "strategy_goal_reference_invalid")
        if not set(references).issubset(goal_ids):
            _block("strategy_goal_reference_invalid")
    if len(strategy_ids) != len(set(strategy_ids)):
        _block("strategy_id_duplicate")

    measures = _rows(body.get("measures"), "measure_required")
    measure_ids: list[str] = []
    required_measure_text = (
        "measure_id",
        "statement",
        "formula_or_judgment_rule",
        "sample_and_horizon",
        "pass_rule",
        "warn_rule",
        "fail_rule",
        "decision_consequence",
        "owner",
    )
    for raw in measures:
        row = _mapping(raw, "measure_metadata_required")
        for name in required_measure_text:
            _text(row.get(name), "measure_metadata_required")
        if row.get("kind") not in _MEASURE_KINDS:
            _block("measure_kind_invalid")
        _text_rows(row.get("evidence_sources"), "measure_metadata_required")
        measure_ids.append(row["measure_id"])
    if len(measure_ids) != len(set(measure_ids)):
        _block("measure_id_duplicate")

    boundary = _mapping(body.get("evidence_boundary"), "evidence_boundary_required")
    for name in ("admitted_classes", "supporting_classes", "excluded_classes"):
        values = _text_rows(boundary.get(name), "evidence_boundary_required")
        if not set(values).issubset(_EVIDENCE_CLASSES):
            _block("evidence_class_invalid")
    _text_rows(body.get("assumptions"), "assumptions_required", allow_empty=True)
    _text_rows(body.get("non_goals"), "non_goals_required", allow_empty=True)
    capacity = _mapping(body.get("capacity_constraints"), "capacity_constraints_required")
    maximum = capacity.get("max_active_task_lineages")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        _block("capacity_constraints_invalid")
    _digest(body.get("review_receipt_digest"), "review_receipt_digest_invalid")


@dataclass(frozen=True, slots=True)
class MeasureVerdict:
    _body: Mapping[str, Any]
    verdict_digest: str

    @property
    def objective_contract_digest(self) -> str:
        return self._body["objective_contract_digest"]

    @property
    def measure_id(self) -> str:
        return self._body["measure_id"]

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(self._body["evidence_refs"])

    @property
    def verdict(self) -> str:
        return self._body["verdict"]

    def to_dict(self) -> dict[str, Any]:
        return {**_clone(self._body), "verdict_digest": self.verdict_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MeasureVerdict":
        body, supplied = _verified_body(
            value,
            schema=MEASURE_VERDICT_SCHEMA,
            digest_field="verdict_digest",
        )
        _digest(body.get("objective_contract_digest"), "objective_contract_digest_invalid")
        for name in ("measure_id", "observed_value", "evaluator", "evaluated_at", "decision_consequence"):
            _text(body.get(name), f"{name}_required")
        evidence_refs = _text_rows(body.get("evidence_refs"), "evidence_refs_invalid", allow_empty=True)
        for ref in evidence_refs:
            _digest(ref, "evidence_ref_invalid")
        if body.get("verdict") not in _MEASURE_VERDICTS:
            _block("measure_verdict_invalid")
        return cls(_freeze(body), supplied)


@dataclass(frozen=True, slots=True)
class ObjectiveChangeReceipt:
    previous_contract_digest: str
    new_contract_digest: str
    changed_fields: tuple[str, ...]
    owner_rationale: str
    cause_refs: tuple[str, ...]
    invalidated_dependencies: tuple[str, ...]
    reusable_evidence: tuple[str, ...]
    owner: str
    accepted_at: str
    schema_version: str = CHANGE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != CHANGE_RECEIPT_SCHEMA:
            _block("objective_change_receipt_schema_invalid")
        _digest(self.previous_contract_digest, "previous_contract_digest_invalid")
        _digest(self.new_contract_digest, "new_contract_digest_invalid")
        for name in ("changed_fields", "cause_refs", "invalidated_dependencies", "reusable_evidence"):
            value = getattr(self, name)
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                _block(f"{name}_invalid")
            normalized = tuple(_text(item, f"{name}_invalid") for item in value)
            object.__setattr__(self, name, normalized)
        if not self.changed_fields:
            _block("changed_fields_required")
        if not self.cause_refs:
            _block("cause_refs_required")
        for ref in (*self.cause_refs, *self.reusable_evidence):
            _digest(ref, "objective_change_evidence_ref_invalid")
        _text(self.owner_rationale, "owner_rationale_required")
        _text(self.owner, "owner_required")
        _text(self.accepted_at, "accepted_at_required")

    @property
    def receipt_digest(self) -> str:
        return content_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        body = {
            "schema_version": self.schema_version,
            "previous_contract_digest": self.previous_contract_digest,
            "new_contract_digest": self.new_contract_digest,
            "changed_fields": list(self.changed_fields),
            "owner_rationale": self.owner_rationale,
            "cause_refs": list(self.cause_refs),
            "invalidated_dependencies": list(self.invalidated_dependencies),
            "reusable_evidence": list(self.reusable_evidence),
            "owner": self.owner,
            "accepted_at": self.accepted_at,
        }
        return {**body, "receipt_digest": self.receipt_digest} if include_digest else body

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObjectiveChangeReceipt":
        body, supplied = _verified_body(
            value,
            schema=CHANGE_RECEIPT_SCHEMA,
            digest_field="receipt_digest",
        )
        result = cls(**body)
        if result.receipt_digest != supplied:
            _block("receipt_digest_mismatch")
        return result


def validate_objective_contract(contract: ObjectiveContract, review: ObjectiveReviewReceipt) -> None:
    if contract.status != "ACCEPTED":
        _block("objective_not_accepted")
    if any(row["verdict"] == "BLOCKED" for row in review.passes):
        _block("objective_review_blocked")
    if contract.review_receipt_digest != review.review_receipt_digest:
        _block("objective_review_binding_mismatch")
    if contract.contract_id != review.contract_id:
        _block("objective_review_contract_mismatch")


def validate_objective_change(
    previous: ObjectiveContract,
    changed: ObjectiveContract,
    *,
    invalidated_dependencies: Sequence[str] | None = None,
    change_receipt: ObjectiveChangeReceipt | None = None,
) -> None:
    if previous.status != "ACCEPTED" or changed.status != "ACCEPTED":
        _block("objective_not_accepted")
    if changed.revision != previous.revision + 1 or changed.parent_digest != previous.contract_digest:
        _block("objective_change_requires_new_revision")
    if previous.contract_id != changed.contract_id or changed.contract_digest == previous.contract_digest:
        _block("objective_change_identity_invalid")
    if change_receipt is None:
        if invalidated_dependencies:
            _block("objective_change_receipt_required")
        _block("objective_change_invalidation_required")
    if change_receipt.previous_contract_digest != previous.contract_digest:
        _block("objective_change_previous_binding_mismatch")
    if change_receipt.new_contract_digest != changed.contract_digest:
        _block("objective_change_new_binding_mismatch")
    if change_receipt.owner != changed.owner:
        _block("objective_change_owner_mismatch")
    if not change_receipt.invalidated_dependencies:
        _block("objective_change_invalidation_required")


def validate_downstream_binding(
    *,
    accepted_contract: ObjectiveContract,
    task_objective_digest: str,
    run_objective_digest: str,
    handoff_objective_digest: str,
    release_objective_digest: str,
) -> None:
    if accepted_contract.status != "ACCEPTED":
        _block("objective_not_accepted")
    expected = accepted_contract.contract_digest
    bindings = (
        task_objective_digest,
        run_objective_digest,
        handoff_objective_digest,
        release_objective_digest,
    )
    for value in bindings:
        _digest(value, "objective_binding_digest_invalid")
    if task_objective_digest != expected and all(value == expected for value in bindings[1:]):
        _block("objective_contract_stale")
    if any(value != expected for value in bindings):
        _block("objective_binding_mismatch")


def validate_measure_verdict(
    contract: ObjectiveContract,
    verdict: MeasureVerdict,
    *,
    evidence_classifications: Mapping[str, str],
) -> None:
    if contract.status != "ACCEPTED":
        _block("objective_not_accepted")
    if verdict.objective_contract_digest != contract.contract_digest:
        _block("objective_binding_mismatch")
    if verdict.measure_id not in contract.measure_ids:
        _block("measure_reference_invalid")
    if not verdict.evidence_refs:
        if verdict.verdict != "EVIDENCE_GAP":
            _block("missing_evidence_requires_gap")
        return
    classifications = dict(evidence_classifications)
    if any(ref not in classifications for ref in verdict.evidence_refs):
        _block("evidence_classification_missing")
    classes = {classifications[ref] for ref in verdict.evidence_refs}
    if not classes.issubset(_EVIDENCE_CLASSES):
        _block("evidence_class_invalid")
    if verdict.verdict == "PASS" and "EXCLUDED" in classes:
        _block("excluded_evidence_cannot_pass")


def validate_aar(value: Mapping[str, Any]) -> None:
    data = _mapping(value, "aar_mapping_required")
    if data.get("schema_version") != AAR_SCHEMA:
        _block("aar_schema_invalid")
    _digest(data.get("objective_contract_digest"), "aar_objective_digest_invalid")
    if data.get("decision") not in _AAR_DECISIONS:
        _block("aar_decision_invalid")
    verdicts = _text_rows(data.get("measure_verdict_digests"), "aar_measure_verdicts_required")
    for ref in verdicts:
        _digest(ref, "aar_measure_verdict_digest_invalid")
    retained = _text_rows(data.get("retained_failure_refs"), "aar_retained_failure_invalid", allow_empty=True)
    regressions = _text_rows(data.get("regression_refs"), "aar_regression_ref_invalid", allow_empty=True)
    for ref in (*retained, *regressions):
        _digest(ref, "aar_evidence_ref_invalid")
    _text(data.get("owner"), "aar_owner_required")
    if data["decision"] == "ADOPT" and (not retained or not regressions):
        _block("aar_retained_failure_required")


def validate_wip(
    contract: ObjectiveContract,
    *,
    active_task_lineages: int,
    accepted_change_receipt: ObjectiveChangeReceipt | None,
) -> None:
    if contract.status != "ACCEPTED":
        _block("objective_not_accepted")
    if not isinstance(active_task_lineages, int) or isinstance(active_task_lineages, bool) or active_task_lineages < 0:
        _block("active_task_lineages_invalid")
    if active_task_lineages > contract.max_active_task_lineages:
        if accepted_change_receipt is None:
            _block("capacity_constraint_exceeded")
        if (
            accepted_change_receipt.new_contract_digest != contract.contract_digest
            or "capacity_constraints" not in accepted_change_receipt.changed_fields
        ):
            _block("capacity_change_receipt_mismatch")


__all__ = [
    "MeasureVerdict",
    "ObjectiveChangeReceipt",
    "ObjectiveContract",
    "ObjectiveReviewReceipt",
    "OgsmValidationError",
    "validate_aar",
    "validate_downstream_binding",
    "validate_measure_verdict",
    "validate_objective_change",
    "validate_objective_contract",
    "validate_wip",
]
