from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    artifact_hashes = manifest.get("artifact_hashes", {})
    expected_outputs = manifest.get("expected_outputs", [])
    if not isinstance(artifact_hashes, dict) or not isinstance(expected_outputs, list):
        return [{"path": "$", "error": "invalid manifest artifact fields"}]

    for item in expected_outputs:
        path_text = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path_text, str) or not path_text:
            mismatches.append({"path": "$.expected_outputs", "error": "invalid output path"})
            continue
        path = Path(path_text)
        expected_exists = item.get("exists") is True
        actual_exists = path.exists()
        if expected_exists != actual_exists:
            mismatches.append(
                {
                    "path": path_text,
                    "error": "exists mismatch",
                    "expected_exists": expected_exists,
                    "actual_exists": actual_exists,
                }
            )
            continue
        if expected_exists:
            expected_hash = artifact_hashes.get(path_text)
            actual_hash = file_sha256(path)
            if expected_hash != actual_hash:
                mismatches.append(
                    {
                        "path": path_text,
                        "error": "sha256 mismatch",
                        "expected_sha256": expected_hash,
                        "actual_sha256": actual_hash,
                    }
                )
    return mismatches


def build_manifest(
    *,
    run_id: str,
    command: list[str],
    artifact_dir: Path,
    inputs: list[Path],
    outputs: list[Path],
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": "quantengine_public.run_manifest.v1",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "command": command,
        "git": _git_info(),
        "python": sys.version.split()[0],
        "artifact_dir": str(artifact_dir),
        "input_hashes": {
            str(path): file_sha256(path)
            for path in inputs
            if path.exists()
        },
        "artifact_hashes": {
            str(path): file_sha256(path)
            for path in outputs
            if path.exists()
        },
        "expected_outputs": [
            {"path": str(path), "exists": path.exists()}
            for path in outputs
        ],
        "status": status,
    }


def _git_info() -> dict[str, Any]:
    return {
        "commit": _git(["rev-parse", "--short", "HEAD"]),
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(_git(["status", "--porcelain"])),
    }


def _git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
