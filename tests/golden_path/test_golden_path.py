from __future__ import annotations

import json
from copy import deepcopy

import pytest

import quantengine_public.delivery.golden_path as golden_path_module
from quantengine_public.delivery.golden_path import (
    GOLDEN_PATH_FILENAMES,
    build_reference_request,
    main,
    run_golden_path,
)
from quantengine_public.delivery.identity import content_digest, verify_artifact, verify_artifact_chain


def test_public_golden_path_produces_fourteen_bound_artifacts(tmp_path):
    result = run_golden_path(build_reference_request(), tmp_path)

    assert result["status"] == "PASS"
    assert result["artifact_count"] == 14
    assert [path.name for path in sorted(tmp_path.glob("*.json"))] == sorted(GOLDEN_PATH_FILENAMES)

    artifacts = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in tmp_path.glob("*.json")
    }
    for artifact in artifacts.values():
        assert verify_artifact(artifact) == []
    ordered_artifacts = [artifacts[filename] for filename in GOLDEN_PATH_FILENAMES]
    assert verify_artifact_chain(ordered_artifacts) == []

    runtime = artifacts["09_runtime_evidence.json"]
    quality = artifacts["12_quality_verdict.json"]
    final = artifacts["13_release_verdict.json"]
    aar = artifacts["14_aar.json"]
    assert runtime["producer"] == "quantengine_public"
    assert runtime["authority"] == {
        "deployment_allowed": False,
        "paper_allowed": False,
        "real_allowed": False,
    }
    assert any(
        edge["artifact_digest"] == runtime["artifact_digest"]
        for edge in quality["upstream"]
    )
    assert final["producer"] == "public_release_controller"
    assert {edge["artifact_type"] for edge in final["upstream"]} == {
        "public_delivery.runtime_evidence",
        "public_delivery.quality_verdict",
    }
    assert final["status"] == "PASS"
    assert final["authority"] == {
        "deployment_allowed": False,
        "paper_allowed": True,
        "real_allowed": False,
    }
    assert aar["payload"]["decision"] == "KEEP"
    assert aar["payload"]["negative_evidence_retained"] is True
    assert aar["payload"]["eval_case"] == "package-integrity-negative-suite"
    assert aar["payload"]["repair_layer"] == "CONTRACT"
    assert aar["payload"]["historical_regressions_replayed"] is True
    assert aar["payload"]["promotion_status"] == "PROMOTED"


def test_public_golden_path_has_one_fixed_reproduction_entrypoint(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0
    assert (tmp_path / "14_aar.json").exists()


@pytest.mark.parametrize(
    ("mutation", "expected_stage", "expected_reason"),
    [
        (lambda request: request.update(acceptance_measures=[]), "objective_gate", "missing_acceptance_measure"),
        (
            lambda request: request["source_identity"].update(commit="7a2dd8d"),
            "architecture_gate",
            "invalid_source_commit",
        ),
        (
            lambda request: request.update(changed_paths=["private/strategy.py"]),
            "implementation_gate",
            "scope_escape",
        ),
        (
            lambda request: request.update(validation_cases=[{"id": "happy", "kind": "positive"}]),
            "validation_space_gate",
            "missing_negative_case",
        ),
        (lambda request: request.update(artifact_digests=[]), "ops_gate", "missing_artifact_digest"),
        (
            lambda request: request.update(artifact_digests=["c" * 64]),
            "ops_gate",
            "artifact_digest_mismatch",
        ),
        (lambda request: request.update(owner_evidence=[]), "qcs_gate", "evidence_gap"),
        (lambda request: request.update(provenance_matches=False), "quality_gate", "provenance_mismatch"),
        (
            lambda request: request.update(package_integrity=False),
            "runtime_evidence_gate",
            "package_integrity_failure",
        ),
    ],
)
def test_public_golden_path_fails_closed_at_the_owning_boundary(
    tmp_path,
    mutation,
    expected_stage,
    expected_reason,
):
    request = deepcopy(build_reference_request())
    mutation(request)

    result = run_golden_path(request, tmp_path)

    assert result["status"] == "FAIL_CLOSED"
    assert result["stage"] == expected_stage
    assert result["reason"] == expected_reason
    blocker = json.loads((tmp_path / "block_receipt.json").read_text(encoding="utf-8"))
    assert verify_artifact(blocker) == []
    assert blocker["status"] in {"BLOCKED", "EVIDENCE_GAP", "FAIL_CLOSED"}
    assert blocker["payload"]["reason"] == expected_reason
    assert blocker["payload"]["request_digest"] == content_digest(request)
    assert json.loads((tmp_path / "request.json").read_text(encoding="utf-8")) == request

    if expected_stage not in {"objective_gate", "architecture_gate"}:
        assert blocker["upstream"], "late-stage blockers must retain the valid causal chain"
    if expected_reason == "artifact_digest_mismatch":
        assert blocker["payload"]["details"] == {
            "actual_package_id": build_reference_request()["artifact_digests"][0],
            "declared_artifact_digests": ["c" * 64],
        }


def test_malformed_request_fails_closed_instead_of_crashing(tmp_path):
    request = deepcopy(build_reference_request())
    del request["objective"]

    result = run_golden_path(request, tmp_path)

    assert result == {
        "status": "FAIL_CLOSED",
        "stage": "objective_gate",
        "reason": "request_contract_mismatch",
    }
    blocker = json.loads((tmp_path / "block_receipt.json").read_text(encoding="utf-8"))
    assert verify_artifact(blocker) == []
    assert blocker["payload"]["request_digest"] == content_digest(request)


def test_failed_runtime_verdict_stops_before_qcs_and_quality(tmp_path, monkeypatch):
    original_run_demo = golden_path_module.run_demo

    def run_failed_demo(artifact_dir):
        result = original_run_demo(artifact_dir)
        result["release_verdict"]["verdict"] = "FAIL_CLOSED"
        result["release_verdict"]["authority"]["paper_allowed"] = False
        return result

    monkeypatch.setattr(golden_path_module, "run_demo", run_failed_demo)

    result = run_golden_path(build_reference_request(), tmp_path)

    assert result == {
        "status": "FAIL_CLOSED",
        "stage": "runtime_evidence_gate",
        "reason": "runtime_verdict_failed",
    }
    runtime = json.loads((tmp_path / "09_runtime_evidence.json").read_text(encoding="utf-8"))
    blocker = json.loads((tmp_path / "block_receipt.json").read_text(encoding="utf-8"))
    assert runtime["status"] == "FAIL_CLOSED"
    assert blocker["upstream"] == [
        {
            "artifact_type": runtime["artifact_type"],
            "artifact_digest": runtime["artifact_digest"],
        }
    ]
    assert not (tmp_path / "10_qcs_manifest.json").exists()
    assert not (tmp_path / "12_quality_verdict.json").exists()
