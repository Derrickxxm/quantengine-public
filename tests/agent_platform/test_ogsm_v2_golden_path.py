"""DEC-0041 M5 end-to-end proof and adversarial acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from quantengine_public.agent_platform.contracts import (
    GraphIdentity,
    SourceIdentity,
    TaskSnapshot,
    content_digest,
)
from quantengine_public.agent_platform.ogsm_v2_proof import (
    ATTACK_IDS,
    PROOF_SECTIONS,
    PublicOgsmV2ProofError,
    build_public_ogsm_v2_proof,
    verify_public_ogsm_v2_proof,
)
from quantengine_public.delivery.identity import verify_artifact, verify_artifact_chain
from quantengine_public.agent_platform.vertical_slice import VerticalSliceRunner


ROOT = Path(__file__).resolve().parents[2]
COMMITTED_PROOF = ROOT / "examples" / "golden_path_v2" / "proof.json"
ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    for item in files:
        if item.is_file():
            digest.update(item.relative_to(path if path.is_dir() else path.parent).as_posix().encode())
            digest.update(b"\0")
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _objective_bindings(section):
    if isinstance(section, list):
        return [item["objective_contract_digest"] for item in section]
    if "objective_contract_digest" in section:
        return [section["objective_contract_digest"]]
    return [section["payload"]["objective_contract_digest"]]


def test_committed_v2_proof_is_deterministic_complete_and_independently_verified():
    committed = json.loads(COMMITTED_PROOF.read_text(encoding="utf-8"))
    generated = build_public_ogsm_v2_proof()

    assert committed == generated
    assert verify_public_ogsm_v2_proof(committed) == committed["manifest"]
    assert tuple(committed["sections"]) == PROOF_SECTIONS
    assert committed["authority"] == ZERO_AUTHORITY
    assert committed["execution"] == {
        "mode": "deterministic-domain-neutral-fixture",
        "network_model_calls": False,
    }


def test_positive_path_binds_every_downstream_section_and_rederives_release():
    proof = build_public_ogsm_v2_proof()
    sections = proof["sections"]
    objective_digest = sections["02_objective_contract"]["contract_digest"]
    downstream = PROOF_SECTIONS[3:]

    for name in downstream:
        assert set(_objective_bindings(sections[name])) == {objective_digest}

    artifacts = proof["positive_artifacts"]
    assert verify_artifact_chain(artifacts) == []
    assert artifacts[-1] == sections["12_release_verdict"]
    assert artifacts[-1]["status"] == "PASS"
    assert artifacts[-1]["authority"] == ZERO_AUTHORITY
    assert sections["13_measure_verdicts"][0]["verdict"] == "PASS"
    assert sections["14_aar"]["decision"] == "ADOPT"
    assert sections["15_owner_decision"]["decision"] == "ADOPT"


def test_objective_bound_vertical_slice_reaches_release_without_dropping_binding(tmp_path):
    proof = build_public_ogsm_v2_proof()
    task = TaskSnapshot.from_dict(proof["sections"]["03_task_snapshot"])
    source = SourceIdentity(
        "quantengine-public",
        "synthetic/ogsm-v2-golden-path",
        "a" * 40,
        "b" * 64,
    )
    graph = GraphIdentity("ogsm-v2-golden-path-v1", source.commit, "c" * 64)
    runner = VerticalSliceRunner(tmp_path / "ogsm-v2.sqlite3", task=task, source=source, graph=graph)
    try:
        result = asyncio.run(runner.run())
    finally:
        runner.close()

    expected = task.objective_contract_digest
    assert result.state.state == "RELEASE_DECIDED"
    assert result.release["payload"]["objective_contract_digest"] == expected
    assert {run.objective_contract_digest for run in result.runs} == {expected}
    assert {handoff.objective_contract_digest for handoff in result.handoffs} == {expected}
    assert {item.objective_contract_digest for item in result.evidence} == {expected}


def test_all_fourteen_attacks_block_at_declared_stage_with_typed_receipts():
    proof = build_public_ogsm_v2_proof()
    attacks = proof["attacks"]

    assert tuple(item["attack_id"] for item in attacks) == ATTACK_IDS
    assert len(attacks) == 14
    for item in attacks:
        receipt = item["block_receipt"]
        assert verify_artifact(receipt) == []
        assert receipt["artifact_type"] == "public_delivery.block_receipt"
        assert receipt["status"] in {"BLOCKED", "EVIDENCE_GAP", "FAIL_CLOSED"}
        assert receipt["authority"] == ZERO_AUTHORITY
        assert receipt["payload"]["attack_id"] == item["attack_id"]
        assert receipt["payload"]["stage"] == item["declared_stage"]
        assert receipt["payload"]["request_digest"] == content_digest(item["request"])
        assert receipt["payload"]["proof_role"] == "negative_only"


@pytest.mark.parametrize(
    "mutation",
    [
        "file_digest",
        "objective_binding",
        "release_topology",
        "measure_verdict",
        "attack_receipt",
        "owner_decision",
    ],
)
def test_independent_verifier_rejects_tampering_across_every_proof_layer(mutation: str):
    proof = deepcopy(build_public_ogsm_v2_proof())
    if mutation == "file_digest":
        proof["manifest"]["section_digests"]["03_task_snapshot"] = "0" * 64
    elif mutation == "objective_binding":
        proof["sections"]["07_patch_manifest"]["payload"]["objective_contract_digest"] = "0" * 64
    elif mutation == "release_topology":
        proof["sections"]["12_release_verdict"]["upstream"] = []
    elif mutation == "measure_verdict":
        proof["sections"]["13_measure_verdicts"][0]["verdict"] = "FAIL"
    elif mutation == "attack_receipt":
        proof["attacks"][0]["block_receipt"]["payload"]["stage"] = "forged_gate"
    else:
        proof["sections"]["15_owner_decision"]["decision"] = "ABANDON"

    with pytest.raises(PublicOgsmV2ProofError):
        verify_public_ogsm_v2_proof(proof)


def test_m5_does_not_modify_golden_path_or_public_proof_v1():
    assert _tree_digest(ROOT / "examples" / "golden_path") == (
        "2169edbabbe1ce00a712ba16136d3a7f9b9f4cf7ac282768cbfde539d941742e"
    )
    assert _tree_digest(ROOT / "src" / "quantengine_public" / "agent_platform" / "public_proof.py") == (
        "e4a4ec6604843b24508c0c6b00f9627c37a960ebf7abba1612376fe19013cd1c"
    )
