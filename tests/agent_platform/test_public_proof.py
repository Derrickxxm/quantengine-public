from __future__ import annotations

import json
from copy import deepcopy

import pytest

from quantengine_public.agent_platform.contracts import content_digest
from quantengine_public.agent_platform.public_proof import (
    PROOF_FILES,
    PublicProofError,
    generate_public_proof,
    verify_public_proof,
)
from scripts.release_smoke import verify_tag_identity


pytest.importorskip("agents", reason="install openai-agents==0.22.0")


IDENTITY = {
    "repository": "quantengine-public",
    "branch": "codex/TASKSYS-1266/m8-public-proof",
    "commit": "a" * 40,
    "tree_digest": "b" * 64,
    "graph_revision": "agent-platform-source-set-v1",
    "graph_digest": "c" * 64,
}


def _generate(tmp_path):
    output = tmp_path / "proof"
    manifest = generate_public_proof(output, **IDENTITY)
    return output, manifest


def test_public_proof_executes_sdk_slice_and_learning_closure(tmp_path):
    output, manifest = _generate(tmp_path)

    assert {path.name for path in output.iterdir()} == set(PROOF_FILES)
    assert verify_public_proof(output, expected_commit=IDENTITY["commit"]) == manifest
    assert manifest["execution"] == {
        "mode": "bounded-ci-scripted-model",
        "network_model_calls": False,
        "sdk_package": "openai-agents",
        "sdk_version": "0.22.0",
    }
    assert manifest["authority"] == {
        "deployment_allowed": False,
        "paper_allowed": False,
        "real_allowed": False,
    }
    assert manifest["counts"] == {
        "roles": 6,
        "handoffs": 6,
        "vertical_evidence": 7,
        "learning_evidence": 7,
        "historical_regressions": 7,
    }
    assert manifest["release_ref"]["artifact_type"] == "public_delivery.release_verdict"
    assert manifest["aar_ref"]["artifact_type"] == "public_delivery.aar"

    trace = json.loads((output / "public_trace.json").read_text())
    assert [entry["role"] for entry in trace] == [
        "Architecture", "Test", "Development", "Test", "Ops", "Quality"
    ]
    serialized = json.dumps(trace, sort_keys=True).lower()
    assert all(secret not in serialized for secret in ("prompt", "api_key", "hostname", "/users/"))
    assert all(set(entry) == {"result_digest", "role", "run_id", "status", "stop_reason"} for entry in trace)


def test_public_proof_verifier_rejects_tampering_stale_source_and_authority(tmp_path):
    output, _ = _generate(tmp_path)

    evidence_path = output / "evidence.json"
    evidence = json.loads(evidence_path.read_text())
    evidence[0]["status"] = "FORGED"
    evidence_path.write_text(json.dumps(evidence, sort_keys=True) + "\n")
    with pytest.raises(PublicProofError, match="file_digest_mismatch:evidence.json"):
        verify_public_proof(output, expected_commit=IDENTITY["commit"])

    output, _ = _generate(tmp_path / "fresh")
    with pytest.raises(PublicProofError, match="source_commit_mismatch"):
        verify_public_proof(output, expected_commit="d" * 40)

    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["authority"]["deployment_allowed"] = True
    body = {key: deepcopy(value) for key, value in manifest.items() if key != "proof_digest"}
    manifest["proof_digest"] = content_digest(body)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    with pytest.raises(PublicProofError, match="nonzero_authority"):
        verify_public_proof(output, expected_commit=IDENTITY["commit"])


def test_public_proof_is_deterministic_for_the_same_identity(tmp_path):
    first, first_manifest = _generate(tmp_path / "first")
    second, second_manifest = _generate(tmp_path / "second")

    assert first_manifest == second_manifest
    assert {
        name: (first / name).read_bytes()
        for name in PROOF_FILES
    } == {
        name: (second / name).read_bytes()
        for name in PROOF_FILES
    }


def test_release_tag_identity_matches_package_version():
    verify_tag_identity("0.5.0", ref_type="tag", ref_name="v0.5.0")
    verify_tag_identity("0.5.0", ref_type="branch", ref_name="main")
    with pytest.raises(RuntimeError, match="tag version mismatch"):
        verify_tag_identity("0.5.0", ref_type="tag", ref_name="v0.4.0")
