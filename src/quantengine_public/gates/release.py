from __future__ import annotations

from typing import Any


def evaluate_gate(
    *,
    replay_ok: bool,
    reconcile_ok: bool,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected_outputs = manifest.get("expected_outputs", [])
    outputs_ok = all(item.get("exists") is True for item in expected_outputs)
    checks = {
        "replay": "pass" if replay_ok else "fail",
        "reconcile": "pass" if reconcile_ok else "fail",
        "expected_outputs": "pass" if outputs_ok else "fail",
        "artifact_hashes": "pass" if _artifact_hashes_ok(manifest) else "fail",
        "manifest": "pass" if _manifest_ok(manifest) else "fail",
    }
    return {
        "release_gate": "pass" if all(value == "pass" for value in checks.values()) else "fail",
        "checks": checks,
    }


def _manifest_ok(manifest: dict[str, Any]) -> bool:
    return bool(
        manifest.get("schema_version")
        and manifest.get("run_id")
        and manifest.get("created_at")
        and isinstance(manifest.get("command"), list)
        and isinstance(manifest.get("expected_outputs"), list)
        and isinstance(manifest.get("artifact_hashes"), dict)
        and manifest.get("status") in {"completed", "failed"}
    )


def _artifact_hashes_ok(manifest: dict[str, Any]) -> bool:
    expected_outputs = manifest.get("expected_outputs", [])
    artifact_hashes = manifest.get("artifact_hashes", {})
    if not isinstance(expected_outputs, list) or not isinstance(artifact_hashes, dict):
        return False
    if not expected_outputs:
        return False
    existing_paths = [
        item.get("path")
        for item in expected_outputs
        if item.get("exists") is True
    ]
    return all(isinstance(artifact_hashes.get(path), str) and artifact_hashes[path] for path in existing_paths)
