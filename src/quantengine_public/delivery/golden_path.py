from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from quantengine_public.artifacts import write_json
from quantengine_public.delivery.identity import artifact_ref, content_digest, seal_artifact
from quantengine_public.demo import run_demo


GOLDEN_PATH_FILENAMES = [
    "01_ogsm.json",
    "02_plane_task.json",
    "03_architecture_packet.json",
    "04_validation_plan.json",
    "05_worker_handoff.json",
    "06_patch_manifest.json",
    "07_test_result.json",
    "08_ops_delivery_plan.json",
    "09_runtime_evidence.json",
    "10_qcs_manifest.json",
    "11_qcs_receipt.json",
    "12_quality_verdict.json",
    "13_release_verdict.json",
    "14_aar.json",
]
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_KEYS = {
    "objective",
    "acceptance_measures",
    "non_goals",
    "plane_task_id",
    "source_identity",
    "affected_components",
    "allowed_paths",
    "changed_paths",
    "validation_cases",
    "artifact_digests",
    "owner_evidence",
    "provenance_matches",
    "package_integrity",
}


def main(argv: list[str] | None = None) -> int:
    """Reproduce the fixed public Golden Path evidence set."""
    parser = argparse.ArgumentParser(
        prog="python -m quantengine_public.delivery.golden_path",
        description="Generate the fixed public multi-Agent Golden Path evidence.",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_golden_path(build_reference_request(), args.artifact_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


def build_reference_request() -> dict[str, Any]:
    """Return the deterministic public request used by the first Golden Path."""
    return {
        "objective": "Prove one traceable specialist-Agent delivery path",
        "acceptance_measures": [
            "tampered package fails closed",
            "Paper and Replay remain independently reconcilable",
            "Real and deployment authority remain withheld",
        ],
        "non_goals": ["production deployment", "strategy profitability"],
        "plane_task_id": "PUBLIC-001",
        "source_identity": {
            "identity_mode": "synthetic_fixture",
            "repository": "Derrickxxm/quantengine-public",
            "branch": "synthetic/golden-path",
            "commit": "f" * 40,
            "source_tree": "a" * 64,
        },
        "affected_components": ["package verification", "release evidence"],
        "allowed_paths": [
            "src/quantengine_public/demo.py",
            "tests/test_demo_v2.py",
        ],
        "changed_paths": [
            "src/quantengine_public/demo.py",
            "tests/test_demo_v2.py",
        ],
        "validation_cases": [
            {"id": "clean-package", "kind": "positive"},
            {"id": "changed-file", "kind": "negative"},
            {"id": "missing-file", "kind": "negative"},
            {"id": "extra-file", "kind": "negative"},
        ],
        "artifact_digests": ["58f7123d64497761288c70a5f07a8ef6bce88f84eedd15e83b58600303fc0011"],
        "owner_evidence": ["package_verification", "release_verdict"],
        "provenance_matches": True,
        "package_integrity": True,
    }


def run_golden_path(request: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    """Generate one public-safe artifact chain or a sealed blocker receipt."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []

    if not isinstance(request, dict) or set(request) != _REQUEST_KEYS:
        return _block(artifact_dir, artifacts, request, "objective_gate", "request_contract_mismatch", "BLOCKED")
    if (
        not isinstance(request["objective"], str)
        or not request["objective"]
        or not _valid_string_list(request["acceptance_measures"])
        or not _valid_string_list(request["non_goals"])
    ):
        return _block(artifact_dir, artifacts, request, "objective_gate", "missing_acceptance_measure", "BLOCKED")

    ogsm = _append(
        artifacts,
        "public_delivery.ogsm",
        "owner_fixture",
        "READY",
        [],
        {
            "objective": request["objective"],
            "measures": request["acceptance_measures"],
            "non_goals": request["non_goals"],
        },
    )
    if not isinstance(request["plane_task_id"], str) or not request["plane_task_id"]:
        return _block(artifact_dir, artifacts, request, "objective_gate", "invalid_task_identity", "BLOCKED")
    task = _append(
        artifacts,
        "public_delivery.plane_task",
        "public_plane_fixture",
        "READY",
        [ogsm],
        {
            "task_id": request["plane_task_id"],
            "acceptance_measures": request["acceptance_measures"],
        },
    )

    source = request["source_identity"]
    if (
        not isinstance(source, dict)
        or set(source) != {"identity_mode", "repository", "branch", "commit", "source_tree"}
        or source.get("identity_mode") != "synthetic_fixture"
        or not isinstance(source.get("repository"), str)
        or not source.get("repository")
        or not isinstance(source.get("branch"), str)
        or not source.get("branch")
        or not _FULL_SHA_RE.fullmatch(str(source.get("commit", "")))
        or not _DIGEST_RE.fullmatch(str(source.get("source_tree", "")))
    ):
        return _block(artifact_dir, artifacts, request, "architecture_gate", "invalid_source_commit", "BLOCKED")
    if not _safe_paths(request["allowed_paths"]) or not _valid_string_list(request["affected_components"]):
        return _block(artifact_dir, artifacts, request, "architecture_gate", "unsafe_path", "BLOCKED")
    architecture = _append(
        artifacts,
        "public_delivery.architecture_packet",
        "public_architecture_agent",
        "READY",
        [task],
        {
            "source_identity": request["source_identity"],
            "affected_components": request["affected_components"],
            "allowed_paths": request["allowed_paths"],
        },
    )

    cases = request["validation_cases"]
    if not _valid_validation_cases(cases):
        return _block(
            artifact_dir,
            artifacts,
            request,
            "validation_space_gate",
            "missing_negative_case",
            "BLOCKED",
        )
    validation = _append(
        artifacts,
        "public_delivery.validation_plan",
        "public_test_agent",
        "READY",
        [task, architecture],
        {"cases": request["validation_cases"], "test_first": True},
    )
    handoff = _append(
        artifacts,
        "public_delivery.worker_handoff",
        "public_control_plane",
        "READY",
        [architecture, validation],
        {
            "source_identity": request["source_identity"],
            "allowed_paths": request["allowed_paths"],
            "dry_run": True,
        },
    )

    changed_paths = request["changed_paths"]
    if not _safe_paths(changed_paths):
        return _block(artifact_dir, artifacts, request, "implementation_gate", "unsafe_path", "BLOCKED")
    if not set(changed_paths).issubset(set(request["allowed_paths"])):
        return _block(artifact_dir, artifacts, request, "implementation_gate", "scope_escape", "BLOCKED")
    patch = _append(
        artifacts,
        "public_delivery.patch_manifest",
        "public_development_agent",
        "READY",
        [handoff],
        {
            "source_identity": request["source_identity"],
            "changed_paths": request["changed_paths"],
            "scope_compliant": True,
        },
    )
    test_result = _append(
        artifacts,
        "public_delivery.test_result",
        "public_test_agent",
        "PASS",
        [validation, patch],
        {
            "declared_cases": [case["id"] for case in request["validation_cases"]],
            "negative_cases_passed": True,
        },
    )

    digests = request["artifact_digests"]
    if not isinstance(digests, list) or not digests or any(
        not isinstance(item, str) or not _DIGEST_RE.fullmatch(item) for item in digests
    ):
        return _block(
            artifact_dir,
            artifacts,
            request,
            "ops_gate",
            "missing_artifact_digest",
            "BLOCKED",
        )
    ops_plan = _append(
        artifacts,
        "public_delivery.ops_plan",
        "public_ops_agent",
        "READY",
        [patch, test_result],
        {
            "artifact_digests": request["artifact_digests"],
            "ci_required": True,
            "readback_required": True,
            "rollback_required": True,
        },
    )

    engine_result = run_demo(artifact_dir / "engine")
    actual_package_id = engine_result["package_manifest"]["package_id"]
    if actual_package_id not in digests:
        return _block(
            artifact_dir,
            artifacts,
            request,
            "ops_gate",
            "artifact_digest_mismatch",
            "BLOCKED",
            details={
                "actual_package_id": actual_package_id,
                "declared_artifact_digests": digests,
            },
        )

    if request["package_integrity"] is not True:
        return _block(
            artifact_dir,
            artifacts,
            request,
            "runtime_evidence_gate",
            "package_integrity_failure",
            "FAIL_CLOSED",
        )

    engine_verdict = engine_result["release_verdict"]
    runtime_evidence = _append(
        artifacts,
        "public_delivery.runtime_evidence",
        "quantengine_public",
        "PASS" if engine_verdict["verdict"] == "PASS" else "FAIL_CLOSED",
        [ops_plan, test_result],
        {
            "engine_release_verdict": engine_verdict,
            "engine_evidence_dir": "engine",
        },
    )
    if runtime_evidence["status"] != "PASS":
        return _block(
            artifact_dir,
            artifacts,
            request,
            "runtime_evidence_gate",
            "runtime_verdict_failed",
            "FAIL_CLOSED",
            details={"engine_verdict": engine_verdict["verdict"]},
        )

    if not _valid_string_list(request["owner_evidence"]):
        return _block(artifact_dir, artifacts, request, "qcs_gate", "evidence_gap", "EVIDENCE_GAP")
    qcs_manifest = _append(
        artifacts,
        "public_delivery.qcs_manifest",
        "public_qcs",
        "READY",
        [runtime_evidence, test_result, ops_plan],
        {
            "risk_surfaces": ["package_integrity", "release_authority"],
            "required_owner_evidence": request["owner_evidence"],
        },
    )
    qcs_receipt = _append(
        artifacts,
        "public_delivery.qcs_receipt",
        "public_qcs",
        "PASS",
        [qcs_manifest, runtime_evidence, test_result],
        {"owner_evidence": request["owner_evidence"], "advisory_only": True},
    )

    if request["provenance_matches"] is not True:
        return _block(
            artifact_dir,
            artifacts,
            request,
            "quality_gate",
            "provenance_mismatch",
            "FAIL_CLOSED",
        )
    quality = _append(
        artifacts,
        "public_delivery.quality_verdict",
        "public_quality_shield",
        "PASS",
        [qcs_receipt, runtime_evidence, test_result, ops_plan],
        {"provenance_matches": True, "closed_world": True},
    )
    release = _append(
        artifacts,
        "public_delivery.release_verdict",
        "public_release_controller",
        "PASS" if quality["status"] == "PASS" and runtime_evidence["status"] == "PASS" else "FAIL_CLOSED",
        [quality, runtime_evidence],
        {
            "decision_basis": [
                "public_delivery.quality_verdict",
                "public_delivery.runtime_evidence",
            ],
            "engine_verdict": engine_verdict["verdict"],
        },
        authority={
            "deployment_allowed": False,
            "paper_allowed": engine_verdict["authority"]["paper_allowed"],
            "real_allowed": False,
        },
    )
    _append(
        artifacts,
        "public_delivery.aar",
        "public_learning_flywheel",
        "RECORDED",
        [release, test_result],
        {
            "problem": "A mutable or incomplete package could be mistaken for reviewed input",
            "reflection": "Package identity must be verified as a closed set before authority is derived",
            "decision": "KEEP",
            "negative_evidence_retained": True,
            "eval_case": "package-integrity-negative-suite",
            "repair_layer": "CONTRACT",
            "historical_regressions_replayed": True,
            "promotion_status": "PROMOTED",
            "next_action": "extend the same identity contract to the next public module",
        },
    )

    _write_artifacts(artifact_dir, artifacts)
    return {"status": "PASS", "artifact_count": len(artifacts)}


def _append(
    artifacts: list[dict[str, Any]],
    artifact_type: str,
    producer: str,
    status: str,
    upstream_artifacts: list[dict[str, Any]],
    payload: dict[str, Any],
    authority: dict[str, bool] | None = None,
) -> dict[str, Any]:
    artifact = seal_artifact(
        artifact_type=artifact_type,
        producer=producer,
        status=status,
        upstream=[artifact_ref(item) for item in upstream_artifacts],
        payload=payload,
        authority=authority,
    )
    artifacts.append(artifact)
    return artifact


def _block(
    artifact_dir: Path,
    artifacts: list[dict[str, Any]],
    request: dict[str, Any],
    stage: str,
    reason: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the valid prefix and bind a blocker to its latest evidence."""
    _write_artifacts(artifact_dir, artifacts)
    write_json(artifact_dir / "request.json", request)
    upstream = [artifact_ref(artifacts[-1])] if artifacts else []
    payload: dict[str, Any] = {
        "stage": stage,
        "reason": reason,
        "request_digest": content_digest(request),
    }
    if details:
        payload["details"] = details
    receipt = seal_artifact(
        artifact_type="public_delivery.block_receipt",
        producer=_producer_for_stage(stage),
        status=status,
        upstream=upstream,
        payload=payload,
    )
    write_json(artifact_dir / "block_receipt.json", receipt)
    return {"status": "FAIL_CLOSED", "stage": stage, "reason": reason}


def _write_artifacts(artifact_dir: Path, artifacts: list[dict[str, Any]]) -> None:
    for filename, artifact in zip(GOLDEN_PATH_FILENAMES, artifacts):
        write_json(artifact_dir / filename, artifact)


def _valid_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _valid_validation_cases(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(case, dict)
            and set(case) == {"id", "kind"}
            and isinstance(case["id"], str)
            and bool(case["id"])
            and case["kind"] in {"positive", "negative"}
            for case in value
        )
        and any(case["kind"] == "negative" for case in value)
    )


def _safe_paths(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, str) or not item:
            return False
        path = PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or "\\" in item:
            return False
    return True


def _producer_for_stage(stage: str) -> str:
    return {
        "objective_gate": "owner_fixture",
        "architecture_gate": "public_architecture_agent",
        "implementation_gate": "public_development_agent",
        "validation_space_gate": "public_test_agent",
        "ops_gate": "public_ops_agent",
        "qcs_gate": "public_qcs",
        "runtime_evidence_gate": "quantengine_public",
        "quality_gate": "public_quality_shield",
        "release_gate": "public_release_controller",
    }[stage]


if __name__ == "__main__":
    raise SystemExit(main())
