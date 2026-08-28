"""DEC-0039 M3 acceptance for the public OGSM control Skill and packet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from quantengine_public.agent_platform import (
    ObjectiveContract,
    ObjectiveReviewReceipt,
    OgsmValidationError,
    validate_objective_contract,
)
from quantengine_public.agent_platform.contracts import content_digest


ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = ROOT / "skills" / "public-ogsm-control" / "SKILL.md"
PACKET_PATH = ROOT / "skills" / "public-ogsm-control" / "assets" / "owner-acceptance-packet.json"


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n")
    _, raw, _ = text.split("---", 2)
    return yaml.safe_load(raw)


def _packet() -> dict:
    return json.loads(PACKET_PATH.read_text(encoding="utf-8"))


def _assert_packet_digest(packet: dict) -> None:
    body = {key: value for key, value in packet.items() if key != "packet_digest"}
    assert packet["packet_digest"] == content_digest(body)


def test_skill_has_discriminating_discovery_metadata_and_bounded_asset():
    text = SKILL_PATH.read_text(encoding="utf-8")
    metadata = _frontmatter(text)

    assert metadata["name"] == "public-ogsm-control"
    assert "Owner acceptance packets" in metadata["description"]
    assert "do not use it to accept an Objective" in metadata["description"]
    assert "assets/owner-acceptance-packet.json" in text
    assert PACKET_PATH.is_file()


def test_owner_packet_is_content_addressed_proposal_with_zero_authority():
    packet = _packet()
    _assert_packet_digest(packet)

    review = ObjectiveReviewReceipt.from_dict(packet["objective_review"])
    contract = ObjectiveContract.from_dict(packet["objective_contract_proposal"])

    assert packet["template"] is True
    assert "Synthetic example only" in packet["template_notice"]
    assert packet["packet_status"] == "PROPOSED"
    assert contract.status == "PROPOSED"
    assert contract.to_dict()["accepted_at"] is None
    assert review.review_receipt_digest == contract.review_receipt_digest
    assert packet["owner_decision"] == {
        "status": "PENDING",
        "accepted_contract_digest": None,
        "decided_at": None,
        "rationale": None,
    }
    assert packet["authority"]
    assert not any(packet["authority"].values())
    assert set(packet["task_lineage"]) == {
        "task_id",
        "task_revision",
        "repository",
        "source_commit",
        "source_tree_digest",
    }
    assert len(packet["task_lineage"]["source_commit"]) == 40
    assert len(packet["task_lineage"]["source_tree_digest"]) == 64
    assert packet["unresolved_blockers"] == []
    assert packet["requested_owner_action"] == "ACCEPT_REVISE_OR_REJECT"
    assert {row["classification"] for row in packet["evidence_inventory"]} == {
        "PRIMARY",
        "EXCLUDED",
    }
    assert all(len(row["evidence_ref"]) == 64 for row in packet["evidence_inventory"])

    with pytest.raises(OgsmValidationError, match="objective_not_accepted"):
        validate_objective_contract(contract, review)


def test_owner_packet_contains_complete_review_and_measure_control_graph():
    packet = _packet()
    review = packet["objective_review"]
    contract = packet["objective_contract_proposal"]

    assert {row["pass_id"] for row in review["passes"]} == {
        "outcome_fit",
        "evidence_goodhart",
        "capacity_authority_minimalism",
    }
    goal_ids = {row["goal_id"] for row in contract["goals"]}
    assert goal_ids
    assert all(set(row["supports_goal_ids"]).issubset(goal_ids) for row in contract["strategies"])
    required_measure_fields = {
        "measure_id",
        "kind",
        "statement",
        "formula_or_judgment_rule",
        "evidence_sources",
        "sample_and_horizon",
        "pass_rule",
        "warn_rule",
        "fail_rule",
        "decision_consequence",
        "owner",
    }
    assert contract["measures"]
    assert all(required_measure_fields.issubset(row) for row in contract["measures"])


def test_packet_can_be_adapted_without_acquiring_owner_authority():
    packet = _packet()
    contract = packet["objective_contract_proposal"]
    contract["objective"] = "Reject promotion when required evidence is absent."
    contract["outcome_card"]["selected_outcome"] = contract["objective"]
    contract_body = {key: value for key, value in contract.items() if key != "contract_digest"}
    contract["contract_digest"] = content_digest(contract_body)
    packet_body = {key: value for key, value in packet.items() if key != "packet_digest"}
    packet["packet_digest"] = content_digest(packet_body)

    adapted = ObjectiveContract.from_dict(contract)
    _assert_packet_digest(packet)
    assert adapted.status == "PROPOSED"
    assert packet["owner_decision"]["status"] == "PENDING"
    assert not any(packet["authority"].values())
