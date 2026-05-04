from __future__ import annotations

from quantengine_public.gates import evaluate_gate


def test_gate_passes_with_complete_manifest():
    manifest = {
        "schema_version": "quantengine_public.run_manifest.v1",
        "run_id": "run-001",
        "created_at": "2026-01-01T00:00:00+00:00",
        "command": ["quantengine-public", "demo"],
        "expected_outputs": [{"path": "actual_state.json", "exists": True}],
        "artifact_hashes": {"actual_state.json": "abc"},
        "status": "completed",
    }

    result = evaluate_gate(replay_ok=True, reconcile_ok=True, manifest=manifest)

    assert result["release_gate"] == "pass"


def test_gate_fails_when_artifact_missing():
    manifest = {
        "schema_version": "quantengine_public.run_manifest.v1",
        "run_id": "run-001",
        "created_at": "2026-01-01T00:00:00+00:00",
        "command": ["quantengine-public", "demo"],
        "expected_outputs": [{"path": "actual_state.json", "exists": False}],
        "artifact_hashes": {},
        "status": "completed",
    }

    result = evaluate_gate(replay_ok=True, reconcile_ok=True, manifest=manifest)

    assert result["release_gate"] == "fail"
    assert result["checks"]["expected_outputs"] == "fail"


def test_gate_fails_when_expected_outputs_empty():
    manifest = {
        "schema_version": "quantengine_public.run_manifest.v1",
        "run_id": "run-001",
        "created_at": "2026-01-01T00:00:00+00:00",
        "command": ["quantengine-public", "demo"],
        "expected_outputs": [],
        "artifact_hashes": {},
        "status": "completed",
    }

    result = evaluate_gate(replay_ok=True, reconcile_ok=True, manifest=manifest)

    assert result["release_gate"] == "fail"
    assert result["checks"]["artifact_hashes"] == "fail"
