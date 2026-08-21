from __future__ import annotations

import json

from quantengine_public.cli import main as cli_main
from quantengine_public.demo import main


def test_demo_v2_generates_public_architecture_artifacts(tmp_path):
    assert main(["--artifact-dir", str(tmp_path)]) == 0

    expected_files = [
        "input_manifest.json",
        "strategy_admission.json",
        "package.manifest.json",
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


def test_demo_v2_is_available_from_installed_cli(tmp_path):
    assert cli_main(["demo-v2", "--artifact-dir", str(tmp_path)]) == 0

    verdict = json.loads((tmp_path / "release_verdict.json").read_text())

    assert verdict["verdict"] == "PASS"
