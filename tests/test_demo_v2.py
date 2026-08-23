from __future__ import annotations

import json

from quantengine_public.cli import main as cli_main
from quantengine_public.demo import (
    _admit_candidate,
    _reconcile,
    _run_paper_runtime,
    _run_replay_oracle,
    _scenario,
    main,
    verify_package,
)


def test_demo_v2_generates_public_architecture_artifacts(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0

    expected_files = [
        "input_manifest.json",
        "strategy_admission.json",
        "package.manifest.json",
        "package_verification.json",
        "paper_events.jsonl",
        "paper_ledger.jsonl",
        "replay_result.json",
        "reconciliation.json",
        "stress_report.json",
        "recovery_receipt.json",
        "release_verdict.json",
        "release-package/strategy.json",
        "release-package/portfolio.json",
        "release-package/runtime_dependencies.json",
        "release-package/admission_result.json",
        "release-package/release.lock.json",
    ]
    for path in expected_files:
        assert (tmp_path / path).exists()

    verdict = json.loads((tmp_path / "release_verdict.json").read_text())
    package_manifest = json.loads((tmp_path / "package.manifest.json").read_text())
    admission = json.loads((tmp_path / "strategy_admission.json").read_text())

    assert verdict["verdict"] == "PASS"
    assert verdict["authority"]["paper_allowed"] is True
    assert verdict["package_verification"]["status"] == "PASS"
    assert admission["paper_allowed"] is True
    assert admission["real_allowed"] is False
    assert package_manifest["authority"]["paper_allowed"] is True
    assert package_manifest["authority"]["real_allowed"] is False


def test_demo_v2_reconciles_paper_and_replay_semantics(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0

    reconciliation = json.loads((tmp_path / "reconciliation.json").read_text())
    replay_result = json.loads((tmp_path / "replay_result.json").read_text())
    paper_ledger = [
        json.loads(line)
        for line in (tmp_path / "paper_ledger.jsonl").read_text().splitlines()
    ]

    assert reconciliation["status"] == "PASS"
    assert reconciliation["checks"]["decisions"] == "pass"
    assert reconciliation["checks"]["ledger"] == "pass"
    assert replay_result["summary"] == {
        "cash": 9985.7,
        "equity": 9985.7,
        "fees": 0.4,
        "funding": -0.5,
        "last_price": 101.0,
        "position": 0.0,
        "realized_pnl": -14.3,
    }
    assert paper_ledger[-1]["position"] == 0.0


def test_demo_v2_stress_checks_fail_closed_cases(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0

    stress_report = json.loads((tmp_path / "stress_report.json").read_text())
    recovery_receipt = json.loads((tmp_path / "recovery_receipt.json").read_text())

    assert stress_report["status"] == "PASS"
    assert stress_report["checks"]["duplicate_market_event"] == "pass"
    assert stress_report["checks"]["duplicate_fill"] == "pass"
    assert stress_report["checks"]["package_identity_drift"] == "pass"
    assert stress_report["checks"]["missing_replay_coverage"] == "pass"
    assert stress_report["checks"]["paper_replay_economic_mismatch"] == "pass"
    assert recovery_receipt["status"] == "PASS"


def test_demo_v2_package_verifier_detects_tamper_delete_and_extra_file(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0
    package_manifest = json.loads((tmp_path / "package.manifest.json").read_text())

    (tmp_path / "release-package" / "strategy.json").write_text('{"tampered": true}\n')
    receipt = verify_package(tmp_path / "release-package", package_manifest)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["failures"][0]["error"] == "sha256 mismatch"

    assert main(["--artifact-dir", str(tmp_path)]) == 0
    (tmp_path / "release-package" / "portfolio.json").unlink()
    receipt = verify_package(tmp_path / "release-package", package_manifest)
    assert receipt["status"] == "FAIL_CLOSED"
    assert any(item["error"] == "missing package file" for item in receipt["failures"])

    assert main(["--artifact-dir", str(tmp_path)]) == 0
    (tmp_path / "release-package" / "extra.json").write_text("{}\n")
    receipt = verify_package(tmp_path / "release-package", package_manifest)
    assert receipt["status"] == "FAIL_CLOSED"
    assert any(item["error"] == "unexpected package file" for item in receipt["failures"])


def test_demo_v2_rejects_conflicting_duplicate_events(tmp_path):
    scenario = _scenario()
    duplicate_events = [*scenario["market_events"], {**scenario["market_events"][0], "close": 999.0}]
    result = _run_paper_runtime(package_id="pkg", run_id="paper", events=duplicate_events)

    assert result["status"] == "FAIL_CLOSED"
    assert "duplicate event_id" in result["errors"][0]


def test_demo_v2_rejects_fill_without_decision_link():
    scenario = _scenario()
    bad_events = [
        *scenario["market_events"][:3],
        {**scenario["market_events"][3], "decision_id": "missing-decision"},
    ]
    result = _run_replay_oracle(package_id="pkg", run_id="replay", events=bad_events)

    assert result["status"] == "FAIL_CLOSED"
    assert "unknown decision_id" in result["errors"][0]


def test_demo_v2_admission_failure_blocks_paper_authority(tmp_path):
    scenario = _scenario()
    input_manifest = tmp_path / "input_manifest.json"
    input_manifest.write_text("{}\n")
    candidate = {
        **scenario["candidate"],
        "research_window": {"start": "2026-08-20T09:30:00Z", "end": "2026-08-20T09:40:00Z"},
    }

    admission = _admit_candidate(candidate, input_manifest)

    assert admission["status"] == "FAIL_CLOSED"
    assert admission["paper_allowed"] is False


def test_demo_v2_independent_replay_catches_economic_mismatch(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0
    package_manifest = json.loads((tmp_path / "package.manifest.json").read_text())
    scenario = _scenario()
    paper = _run_paper_runtime(
        package_id=package_manifest["package_id"],
        run_id="paper",
        events=scenario["market_events"],
    )
    replay = _run_replay_oracle(
        package_id=package_manifest["package_id"],
        run_id="replay",
        events=scenario["market_events"],
    )
    replay["summary"] = {**replay["summary"], "cash": replay["summary"]["cash"] + 1.0}

    reconciliation = _reconcile(package_manifest, paper, replay)

    assert reconciliation["status"] == "FAIL_CLOSED"
    assert reconciliation["checks"]["summary"] == "fail"


def test_demo_v2_is_available_from_installed_cli(tmp_path):
    assert cli_main(["demo-v2", "--artifact-dir", str(tmp_path)]) == 0

    verdict = json.loads((tmp_path / "release_verdict.json").read_text())

    assert verdict["verdict"] == "PASS"
