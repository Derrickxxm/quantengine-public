from __future__ import annotations

import json

from quantengine_public.cli import main


def test_demo_generates_gate_artifact(tmp_path):
    assert main(["demo", "--artifact-dir", str(tmp_path)]) == 0

    gate = json.loads((tmp_path / "release_gate.json").read_text())
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())

    assert gate["release_gate"] == "pass"
    assert manifest["status"] == "completed"
    assert (tmp_path / "actual_state.json").exists()
    assert (tmp_path / "reconcile.json").exists()


def test_gate_command_reuses_demo_artifacts(tmp_path):
    assert main(["demo", "--artifact-dir", str(tmp_path)]) == 0

    assert main(
        [
            "gate",
            "--manifest",
            str(tmp_path / "run_manifest.json"),
            "--reconcile",
            str(tmp_path / "reconcile.json"),
            "--replay-errors",
            str(tmp_path / "replay_errors.json"),
            "--out",
            str(tmp_path / "gate_from_cli.json"),
        ]
    ) == 0

    gate = json.loads((tmp_path / "gate_from_cli.json").read_text())
    assert gate["release_gate"] == "pass"


def test_validate_command_reuses_demo_artifact_dir(tmp_path):
    assert main(["demo", "--artifact-dir", str(tmp_path)]) == 0

    assert main(["validate", "--artifact-dir", str(tmp_path)]) == 0

    gate = json.loads((tmp_path / "release_gate.json").read_text())
    assert gate["release_gate"] == "pass"


def test_validate_command_fails_missing_artifacts(tmp_path):
    assert main(["validate", "--artifact-dir", str(tmp_path)]) == 1

    gate = json.loads((tmp_path / "release_gate.json").read_text())
    assert gate["release_gate"] == "fail"
    assert gate["missing"]


def test_reconcile_command_reports_failure(tmp_path):
    expected = tmp_path / "expected.json"
    actual = tmp_path / "actual.json"
    out = tmp_path / "reconcile.json"
    expected.write_text('{"orders": {"order-001": {"status": "closed"}}}\n')
    actual.write_text('{"orders": {"order-001": {"status": "accepted"}}}\n')

    assert main(["reconcile", "--expected", str(expected), "--actual", str(actual), "--out", str(out)]) == 1

    result = json.loads(out.read_text())
    assert result["status"] == "fail"
    assert result["mismatches"][0]["path"] == "$.orders.order-001.status"
