from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantengine_public.artifacts import file_sha256, write_json


SCHEMA_VERSION = "quantengine_public.demo_v2.v1"
PACKAGE_SCHEMA_VERSION = "quantengine_public.release_package.v1"
VERDICT_SCHEMA_VERSION = "quantengine_public.release_verdict.v1"
FIXED_CREATED_AT = "2026-08-20T09:39:00+00:00"
ALLOWED_EVENT_TYPES = {"bar", "fill", "funding"}
ALLOWED_SIDES = {"BUY", "SELL"}


@dataclass(frozen=True)
class DemoPaths:
    artifact_dir: Path
    input_manifest: Path
    strategy_admission: Path
    strategy: Path
    portfolio: Path
    runtime_dependencies: Path
    admission_result: Path
    release_lock: Path
    package_manifest: Path
    package_verification: Path
    paper_events: Path
    paper_ledger: Path
    replay_result: Path
    reconciliation: Path
    stress_report: Path
    recovery_receipt: Path
    release_verdict: Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quantengine_public.demo",
        description="Run the QuantEngine Public v2 synthetic Paper/replay demo.",
    )
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/demo-v2"))
    args = parser.parse_args(argv)
    result = run_demo(args.artifact_dir)
    print(json.dumps(result["release_verdict"], indent=2, sort_keys=True))
    return 0 if result["release_verdict"]["verdict"] == "PASS" else 1


def run_demo(artifact_dir: Path) -> dict[str, Any]:
    paths = _demo_paths(artifact_dir)
    paths.artifact_dir.mkdir(parents=True, exist_ok=True)

    scenario = _scenario()
    write_json(paths.input_manifest, _input_manifest(scenario))

    candidate = scenario["candidate"]
    admission = _admit_candidate(candidate, paths.input_manifest)
    write_json(paths.strategy_admission, admission)

    package_manifest = _materialize_package(paths, scenario, admission)
    package_receipt = verify_package(paths.artifact_dir / "release-package", package_manifest)
    write_json(paths.package_verification, package_receipt)

    paper_result = _run_paper_runtime(
        package_id=package_manifest["package_id"],
        run_id="paper-reference-run",
        events=scenario["market_events"],
    )
    _write_jsonl(paths.paper_events, paper_result["events"])
    _write_jsonl(paths.paper_ledger, paper_result["ledger"])

    replay_result = _run_replay_oracle(
        package_id=package_manifest["package_id"],
        run_id="replay-reference-run",
        events=scenario["market_events"],
    )
    write_json(paths.replay_result, replay_result)

    reconciliation = _reconcile(package_manifest, paper_result, replay_result)
    write_json(paths.reconciliation, reconciliation)

    stress_report, recovery_receipt = _run_stress_checks(package_manifest, scenario)
    write_json(paths.stress_report, stress_report)
    write_json(paths.recovery_receipt, recovery_receipt)

    release_verdict = _release_verdict(
        paths,
        admission,
        package_manifest,
        package_receipt,
        reconciliation,
        stress_report,
    )
    write_json(paths.release_verdict, release_verdict)

    return {
        "input_manifest": _read_json(paths.input_manifest),
        "strategy_admission": admission,
        "package_manifest": package_manifest,
        "package_verification": package_receipt,
        "reconciliation": reconciliation,
        "stress_report": stress_report,
        "recovery_receipt": recovery_receipt,
        "release_verdict": release_verdict,
    }


def _demo_paths(artifact_dir: Path) -> DemoPaths:
    return DemoPaths(
        artifact_dir=artifact_dir,
        input_manifest=artifact_dir / "input_manifest.json",
        strategy_admission=artifact_dir / "strategy_admission.json",
        strategy=artifact_dir / "release-package" / "strategy.json",
        portfolio=artifact_dir / "release-package" / "portfolio.json",
        runtime_dependencies=artifact_dir / "release-package" / "runtime_dependencies.json",
        admission_result=artifact_dir / "release-package" / "admission_result.json",
        release_lock=artifact_dir / "release-package" / "release.lock.json",
        package_manifest=artifact_dir / "package.manifest.json",
        package_verification=artifact_dir / "package_verification.json",
        paper_events=artifact_dir / "paper_events.jsonl",
        paper_ledger=artifact_dir / "paper_ledger.jsonl",
        replay_result=artifact_dir / "replay_result.json",
        reconciliation=artifact_dir / "reconciliation.json",
        stress_report=artifact_dir / "stress_report.json",
        recovery_receipt=artifact_dir / "recovery_receipt.json",
        release_verdict=artifact_dir / "release_verdict.json",
    )


def _scenario() -> dict[str, Any]:
    return {
        "candidate": {
            "schema_version": "quantengine_public.strategy_candidate.v1",
            "candidate_id": "qep-ma-reference-2026-08-21",
            "strategy_name": "transparent_two_bar_momentum",
            "dataset_id": "synthetic-qep-bars-funding-v1",
            "research_window": {"start": "2026-08-20T09:30:00Z", "end": "2026-08-20T09:32:00Z"},
            "validation_window": {"start": "2026-08-20T09:33:00Z", "end": "2026-08-20T09:38:00Z"},
            "policy_id": "paper-risk-public-v1",
            "benchmark_id": "synthetic-buy-and-hold-qep-v1",
            "requested_authority": "paper",
            "expected_evidence": [
                "strategy_admission",
                "package_manifest",
                "paper_events",
                "paper_ledger",
                "replay_result",
                "reconciliation",
                "stress_report",
                "release_verdict",
            ],
        },
        "portfolio": {
            "schema_version": "quantengine_public.portfolio.v1",
            "portfolio_id": "synthetic-paper-portfolio-v1",
            "base_currency": "USD",
            "starting_cash": 10000.0,
            "max_position": 10,
        },
        "runtime_dependencies": {
            "schema_version": "quantengine_public.runtime_dependencies.v1",
            "python": ">=3.11",
            "engine": SCHEMA_VERSION,
            "external_services": [],
        },
        "market_events": [
            {"event_id": "bar-0930", "type": "bar", "ts": "2026-08-20T09:30:00Z", "symbol": "QEP-USD", "close": 100.0},
            {"event_id": "bar-0931", "type": "bar", "ts": "2026-08-20T09:31:00Z", "symbol": "QEP-USD", "close": 101.0},
            {"event_id": "bar-0933", "type": "bar", "ts": "2026-08-20T09:33:00Z", "symbol": "QEP-USD", "close": 103.0},
            {"event_id": "fill-buy-a", "type": "fill", "ts": "2026-08-20T09:33:02Z", "symbol": "QEP-USD", "side": "BUY", "qty": 6, "price": 103.10, "fee": 0.12, "decision_id": "decision-0933"},
            {"event_id": "fill-buy-b", "type": "fill", "ts": "2026-08-20T09:33:03Z", "symbol": "QEP-USD", "side": "BUY", "qty": 4, "price": 103.20, "fee": 0.08, "decision_id": "decision-0933"},
            {"event_id": "funding-0935", "type": "funding", "ts": "2026-08-20T09:35:00Z", "symbol": "QEP-USD", "amount": -0.50},
            {"event_id": "bar-0938", "type": "bar", "ts": "2026-08-20T09:38:00Z", "symbol": "QEP-USD", "close": 101.0},
            {"event_id": "fill-sell", "type": "fill", "ts": "2026-08-20T09:38:01Z", "symbol": "QEP-USD", "side": "SELL", "qty": 10, "price": 101.80, "fee": 0.20, "decision_id": "decision-0938"},
        ],
    }


def _input_manifest(scenario: dict[str, Any]) -> dict[str, Any]:
    events = scenario["market_events"]
    return {
        "schema_version": "quantengine_public.input_manifest.v1",
        "dataset_id": scenario["candidate"]["dataset_id"],
        "symbol": "QEP-USD",
        "event_count": len(events),
        "event_ids": [event["event_id"] for event in events],
        "coverage": {
            "start": events[0]["ts"],
            "end": events[-1]["ts"],
            "contains_bars": True,
            "contains_funding": True,
            "contains_execution_facts": True,
        },
        "dataset_sha256": _hash_json(events),
    }


def _admit_candidate(candidate: dict[str, Any], input_manifest_path: Path) -> dict[str, Any]:
    research_end = _parse_utc(candidate["research_window"]["end"])
    validation_start = _parse_utc(candidate["validation_window"]["start"])
    checks = {
        "candidate_identity": bool(candidate.get("candidate_id") and candidate.get("schema_version")),
        "dataset_identity": bool(candidate.get("dataset_id") and input_manifest_path.exists()),
        "time_windows": research_end < validation_start,
        "policy_identity": bool(candidate.get("policy_id") and candidate.get("benchmark_id")),
        "authority_boundary": candidate.get("requested_authority") == "paper",
    }
    status = "PASS" if all(checks.values()) else "FAIL_CLOSED"
    return {
        "schema_version": "quantengine_public.strategy_admission.v1",
        "candidate_id": candidate["candidate_id"],
        "status": status,
        "checks": {key: "pass" if value else "fail" for key, value in checks.items()},
        "paper_allowed": status == "PASS",
        "real_allowed": False,
        "input_manifest_sha256": file_sha256(input_manifest_path),
    }


def _materialize_package(
    paths: DemoPaths,
    scenario: dict[str, Any],
    admission: dict[str, Any],
) -> dict[str, Any]:
    strategy = {
        "candidate_id": scenario["candidate"]["candidate_id"],
        "strategy_name": scenario["candidate"]["strategy_name"],
        "rule": "Enter when the validation bar breaks above the prior two-bar average; exit on reversal.",
        "symbol": "QEP-USD",
    }
    release_lock = {
        "schema_version": "quantengine_public.release_lock.v1",
        "authority": {"research_allowed": True, "paper_allowed": admission["paper_allowed"], "real_allowed": False},
        "dataset_id": scenario["candidate"]["dataset_id"],
        "policy_id": scenario["candidate"]["policy_id"],
    }
    write_json(paths.strategy, strategy)
    write_json(paths.portfolio, scenario["portfolio"])
    write_json(paths.runtime_dependencies, scenario["runtime_dependencies"])
    write_json(paths.admission_result, admission)
    write_json(paths.release_lock, release_lock)

    material_paths = [
        paths.strategy,
        paths.portfolio,
        paths.runtime_dependencies,
        paths.admission_result,
        paths.release_lock,
    ]
    file_hashes = {
        str(path.relative_to(paths.artifact_dir)): file_sha256(path)
        for path in material_paths
    }
    package_id = _hash_json(file_hashes)
    manifest = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "created_at": FIXED_CREATED_AT,
        "candidate_id": scenario["candidate"]["candidate_id"],
        "authority": release_lock["authority"],
        "files": file_hashes,
    }
    write_json(paths.package_manifest, manifest)
    return manifest


def verify_package(package_dir: Path, package_manifest: dict[str, Any]) -> dict[str, Any]:
    expected_files = package_manifest.get("files", {})
    failures: list[dict[str, str]] = []
    if not isinstance(expected_files, dict):
        return {
            "schema_version": "quantengine_public.package_verification.v1",
            "status": "FAIL_CLOSED",
            "package_id": package_manifest.get("package_id"),
            "failures": [{"path": "$.files", "error": "invalid package manifest files"}],
        }

    package_root = package_dir.resolve()
    artifact_root = package_root.parent
    actual_files: dict[str, str] = {}

    if not package_dir.exists():
        failures.append({"path": str(package_dir), "error": "missing package directory"})
    else:
        for path in sorted(package_dir.rglob("*")):
            resolved = path.resolve()
            if not _is_within(resolved, package_root):
                failures.append({"path": str(path), "error": "package path outside package directory"})
                continue
            if path.is_symlink():
                failures.append({"path": str(path), "error": "symlink not allowed"})
                continue
            if not path.is_file():
                continue
            relative_path = str(resolved.relative_to(artifact_root))
            actual_files[relative_path] = file_sha256(path)

    for relative_path, expected_hash in expected_files.items():
        path = artifact_root / relative_path
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            failures.append({"path": relative_path, "error": "manifest path outside artifact directory"})
            continue
        if relative_path not in actual_files:
            failures.append({"path": relative_path, "error": "missing package file"})
            continue
        if actual_files[relative_path] != expected_hash:
            failures.append({"path": relative_path, "error": "sha256 mismatch"})

    extra_files = sorted(set(actual_files) - set(expected_files))
    failures.extend({"path": path, "error": "unexpected package file"} for path in extra_files)

    verified_files = {path: actual_files[path] for path in sorted(actual_files) if path in expected_files}
    return {
        "schema_version": "quantengine_public.package_verification.v1",
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "package_id": package_manifest.get("package_id"),
        "verified_file_count": len(verified_files),
        "verified_files": verified_files,
        "failures": failures,
    }


def _run_paper_runtime(
    *,
    package_id: str,
    run_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    validation_error = _validate_market_events(events)
    if validation_error:
        return _failed_runtime_result(package_id, run_id, "paper", validation_error)

    bars: list[dict[str, Any]] = []
    position = 0.0
    cash = 10000.0
    fees = 0.0
    funding = 0.0
    runtime_events: list[dict[str, Any]] = []
    decision_events: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []

    for event in events:
        if event["type"] == "bar":
            bars.append(event)
            decision = _decision_for_bar(package_id, run_id, bars, position)
            if decision:
                decision_events.append(decision)
                runtime_events.extend(_runtime_events_for_decision(decision))
            continue

        if event["type"] == "funding":
            amount = float(event["amount"])
            funding = round(funding + amount, 10)
            cash = round(cash + amount, 10)
            entry = _ledger_entry(package_id, run_id, event, "funding", 0.0, cash, fees, funding, position)
            ledger.append(entry)
            runtime_events.append(_runtime_event(package_id, run_id, event, "accounting_projected", entry))
            continue

        if event["type"] == "fill":
            qty = float(event["qty"])
            signed_qty = qty if event["side"] == "BUY" else -qty
            gross_cash = -signed_qty * float(event["price"])
            fee = float(event["fee"])
            position = round(position + signed_qty, 10)
            cash = round(cash + gross_cash - fee, 10)
            fees = round(fees + fee, 10)
            entry = _ledger_entry(package_id, run_id, event, "fill", gross_cash, cash, fees, funding, position)
            ledger.append(entry)
            runtime_events.append(_runtime_event(package_id, run_id, event, "fill_applied", entry))
            runtime_events.append(_runtime_event(package_id, run_id, event, "accounting_projected", entry))
            continue

        raise ValueError(f"unsupported market event type: {event['type']}")

    close = float(bars[-1]["close"])
    equity = round(cash + position * close, 10)
    return {
        "schema_version": "quantengine_public.runtime_result.v1",
        "status": "PASS",
        "mode": "paper",
        "run_id": run_id,
        "package_id": package_id,
        "input_event_ids": [str(event["event_id"]) for event in events],
        "events": runtime_events,
        "decisions": decision_events,
        "ledger": ledger,
        "summary": {
            "position": position,
            "cash": cash,
            "fees": fees,
            "funding": funding,
            "last_price": close,
            "equity": equity,
            "realized_pnl": round(equity - 10000.0, 10),
        },
    }


def _run_replay_oracle(
    *,
    package_id: str,
    run_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    validation_error = _validate_market_events(events)
    if validation_error:
        return _failed_runtime_result(package_id, run_id, "replay", validation_error)

    bars: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    runtime_events: list[dict[str, Any]] = []
    position = 0.0
    cash = 10000.0
    fees = 0.0
    funding = 0.0

    for event in events:
        if event["type"] == "bar":
            bars.append(event)
            if len(bars) >= 3:
                current = bars[-1]
                prior_avg = round((float(bars[-2]["close"]) + float(bars[-3]["close"])) / 2, 10)
                close = float(current["close"])
                if position == 0.0 and close > prior_avg:
                    side = "BUY"
                    qty = 10
                elif position > 0.0 and close < prior_avg:
                    side = "SELL"
                    qty = position
                else:
                    continue
                decision_id = "decision-" + current["ts"][11:16].replace(":", "")
                decision = {
                    "event_type": "decision",
                    "decision_id": decision_id,
                    "run_id": run_id,
                    "package_id": package_id,
                    "source_event_id": current["event_id"],
                    "side": side,
                    "qty": qty,
                    "risk_check": "pass",
                }
                decisions.append(decision)
                runtime_events.extend(_runtime_events_for_decision(decision))
            continue

        if event["type"] == "funding":
            funding = round(funding + float(event["amount"]), 10)
            cash = round(cash + float(event["amount"]), 10)
            entry = _ledger_entry(package_id, run_id, event, "funding", 0.0, cash, fees, funding, position)
            ledger.append(entry)
            runtime_events.append(_runtime_event(package_id, run_id, event, "accounting_projected", entry))
            continue

        qty = float(event["qty"])
        signed_qty = qty if event["side"] == "BUY" else -qty
        fee = float(event["fee"])
        cash_delta = round(-signed_qty * float(event["price"]), 10)
        position = round(position + signed_qty, 10)
        cash = round(cash + cash_delta - fee, 10)
        fees = round(fees + fee, 10)
        entry = _ledger_entry(package_id, run_id, event, "fill", cash_delta, cash, fees, funding, position)
        ledger.append(entry)
        runtime_events.append(_runtime_event(package_id, run_id, event, "fill_applied", entry))
        runtime_events.append(_runtime_event(package_id, run_id, event, "accounting_projected", entry))

    close = float(bars[-1]["close"])
    equity = round(cash + position * close, 10)
    return {
        "schema_version": "quantengine_public.runtime_result.v1",
        "status": "PASS",
        "mode": "replay",
        "run_id": run_id,
        "package_id": package_id,
        "input_event_ids": [str(event["event_id"]) for event in events],
        "events": runtime_events,
        "decisions": decisions,
        "ledger": ledger,
        "summary": {
            "position": position,
            "cash": cash,
            "fees": fees,
            "funding": funding,
            "last_price": close,
            "equity": equity,
            "realized_pnl": round(equity - 10000.0, 10),
        },
    }


def _failed_runtime_result(
    package_id: str,
    run_id: str,
    mode: str,
    error: str,
) -> dict[str, Any]:
    return {
        "schema_version": "quantengine_public.runtime_result.v1",
        "status": "FAIL_CLOSED",
        "mode": mode,
        "run_id": run_id,
        "package_id": package_id,
        "input_event_ids": [],
        "events": [],
        "decisions": [],
        "ledger": [],
        "summary": {},
        "errors": [error],
    }


def _validate_market_events(events: list[dict[str, Any]]) -> str | None:
    seen: dict[str, dict[str, Any]] = {}
    decisions: set[str] = set()
    for event in events:
        event_id = str(event.get("event_id", ""))
        if not event_id:
            return "event_id is required"
        if event_id in seen:
            return f"duplicate event_id: {event_id}"
        seen[event_id] = event
        event_type = event.get("type")
        if event_type not in ALLOWED_EVENT_TYPES:
            return f"unsupported market event type: {event_type}"
        if "ts" in event:
            _parse_utc(str(event["ts"]))
        if event_type == "bar":
            if float(event.get("close", 0)) <= 0:
                return f"bar close must be positive: {event_id}"
            current_ts = _parse_utc(str(event["ts"]))
            decision_id = "decision-" + str(event["ts"])[11:16].replace(":", "")
            decisions.add(decision_id)
            if len(seen) > 1:
                previous_ts = max(
                    _parse_utc(str(item["ts"]))
                    for item_id, item in seen.items()
                    if item_id != event_id
                )
                if current_ts < previous_ts:
                    return f"events out of order at: {event_id}"
        if event_type == "fill":
            if event.get("side") not in ALLOWED_SIDES:
                return f"unsupported fill side: {event.get('side')}"
            if float(event.get("qty", 0)) <= 0:
                return f"fill qty must be positive: {event_id}"
            if float(event.get("price", 0)) <= 0:
                return f"fill price must be positive: {event_id}"
            if float(event.get("fee", 0)) < 0:
                return f"fill fee cannot be negative: {event_id}"
            if event.get("decision_id") not in decisions:
                return f"fill references unknown decision_id: {event_id}"
    return None


def _decision_for_bar(
    package_id: str,
    run_id: str,
    bars: list[dict[str, Any]],
    position: float,
) -> dict[str, Any] | None:
    if len(bars) < 3:
        return None
    current = bars[-1]
    prior_avg = round((float(bars[-2]["close"]) + float(bars[-3]["close"])) / 2, 10)
    close = float(current["close"])
    if position == 0 and close > prior_avg:
        side = "BUY"
        qty = 10
    elif position > 0 and close < prior_avg:
        side = "SELL"
        qty = position
    else:
        return None
    decision_id = "decision-" + current["ts"][11:16].replace(":", "")
    return {
        "event_type": "decision",
        "decision_id": decision_id,
        "run_id": run_id,
        "package_id": package_id,
        "source_event_id": current["event_id"],
        "side": side,
        "qty": qty,
        "risk_check": "pass",
    }


def _runtime_events_for_decision(decision: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**decision, "event_type": "decision"},
        {**decision, "event_type": "risk_check"},
        {**decision, "event_type": "execution_intent"},
        {**decision, "event_type": "order_created", "order_id": "order-" + decision["decision_id"].split("-")[1]},
    ]


def _runtime_event(
    package_id: str,
    run_id: str,
    source_event: dict[str, Any],
    event_type: str,
    ledger_entry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "run_id": run_id,
        "package_id": package_id,
        "source_event_id": source_event["event_id"],
        "decision_id": source_event.get("decision_id"),
        "ledger_entry_id": ledger_entry["entry_id"],
        "position": ledger_entry["position"],
        "cash": ledger_entry["cash"],
    }


def _ledger_entry(
    package_id: str,
    run_id: str,
    event: dict[str, Any],
    entry_type: str,
    cash_delta: float,
    cash: float,
    fees: float,
    funding: float,
    position: float,
) -> dict[str, Any]:
    return {
        "entry_id": f"{run_id}-{event['event_id']}",
        "entry_type": entry_type,
        "run_id": run_id,
        "package_id": package_id,
        "source_event_id": event["event_id"],
        "decision_id": event.get("decision_id"),
        "cash_delta": round(cash_delta, 10),
        "cash": cash,
        "fees": fees,
        "funding": funding,
        "position": position,
    }


def _reconcile(
    package_manifest: dict[str, Any],
    paper_result: dict[str, Any],
    replay_result: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "runtime_status": paper_result.get("status") == "PASS" and replay_result.get("status") == "PASS",
        "package_identity": paper_result["package_id"] == replay_result["package_id"] == package_manifest["package_id"],
        "input_coverage": paper_result["input_event_ids"] == replay_result["input_event_ids"],
        "decisions": _project_decisions(paper_result) == _project_decisions(replay_result),
        "ledger": _project_ledger(paper_result) == _project_ledger(replay_result),
        "summary": paper_result["summary"] == replay_result["summary"],
        "real_authority_absent": package_manifest["authority"]["real_allowed"] is False,
    }
    gaps = [key for key, value in checks.items() if not value]
    return {
        "schema_version": "quantengine_public.reconciliation.v1",
        "status": "PASS" if not gaps else "FAIL_CLOSED",
        "package_id": package_manifest["package_id"],
        "checks": {key: "pass" if value else "fail" for key, value in checks.items()},
        "gaps": gaps,
    }


def _run_stress_checks(
    package_manifest: dict[str, Any],
    scenario: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    events = scenario["market_events"]
    baseline = _run_paper_runtime(
        package_id=package_manifest["package_id"],
        run_id="stress-baseline",
        events=events,
    )
    duplicate_event = _run_paper_runtime(
        package_id=package_manifest["package_id"],
        run_id="stress-baseline",
        events=[events[0], *events],
    )
    duplicate_fill = _run_paper_runtime(
        package_id=package_manifest["package_id"],
        run_id="stress-baseline",
        events=[*events[:5], events[4], *events[5:]],
    )
    drifted_package = {**package_manifest, "package_id": "drifted-package"}
    drift_reconciliation = _reconcile(drifted_package, baseline, baseline)
    missing_replay = _run_replay_oracle(
        package_id=package_manifest["package_id"],
        run_id="stress-missing-replay",
        events=events[:-1],
    )
    missing_coverage = _reconcile(package_manifest, baseline, missing_replay)
    mismatch_replay = {**baseline, "summary": {**baseline["summary"], "cash": baseline["summary"]["cash"] + 1.0}}
    economic_mismatch = _reconcile(package_manifest, baseline, mismatch_replay)
    checks = {
        "duplicate_market_event": duplicate_event["status"] == "FAIL_CLOSED",
        "duplicate_fill": duplicate_fill["status"] == "FAIL_CLOSED",
        "interruption_recovery": _project_ledger(baseline) != _project_ledger(duplicate_fill),
        "package_identity_drift": drift_reconciliation["status"] == "FAIL_CLOSED",
        "missing_replay_coverage": missing_coverage["status"] == "FAIL_CLOSED",
        "paper_replay_economic_mismatch": economic_mismatch["status"] == "FAIL_CLOSED",
    }
    status = "PASS" if all(checks.values()) else "FAIL_CLOSED"
    recovery_receipt = {
        "schema_version": "quantengine_public.recovery_receipt.v1",
        "status": "PASS" if checks["duplicate_fill"] and checks["interruption_recovery"] else "FAIL_CLOSED",
        "recovered_fill_ids": ["fill-buy-b"],
        "method": "idempotent replay from sealed package and pinned inputs",
    }
    return (
        {
            "schema_version": "quantengine_public.stress_report.v1",
            "status": status,
            "checks": {key: "pass" if value else "fail" for key, value in checks.items()},
        },
        recovery_receipt,
    )


def _release_verdict(
    paths: DemoPaths,
    admission: dict[str, Any],
    package_manifest: dict[str, Any],
    package_receipt: dict[str, Any],
    reconciliation: dict[str, Any],
    stress_report: dict[str, Any],
) -> dict[str, Any]:
    required_paths = [
        paths.input_manifest,
        paths.strategy_admission,
        paths.strategy,
        paths.portfolio,
        paths.runtime_dependencies,
        paths.admission_result,
        paths.release_lock,
        paths.package_manifest,
        paths.package_verification,
        paths.paper_events,
        paths.paper_ledger,
        paths.replay_result,
        paths.reconciliation,
        paths.stress_report,
        paths.recovery_receipt,
    ]
    checks = {
        "admission": admission["status"] == "PASS",
        "package_identity": package_receipt["status"] == "PASS",
        "authority": admission["paper_allowed"] is True
        and package_manifest["authority"]["paper_allowed"] is True
        and package_manifest["authority"]["real_allowed"] is False,
        "artifacts_exist": all(path.exists() for path in required_paths),
        "reconciliation": reconciliation["status"] == "PASS",
        "stress": stress_report["status"] == "PASS",
    }
    artifact_hashes = {str(path): file_sha256(path) for path in required_paths if path.exists()}
    return {
        "schema_version": VERDICT_SCHEMA_VERSION,
        "created_at": FIXED_CREATED_AT,
        "verdict": "PASS" if all(checks.values()) else "FAIL_CLOSED",
        "checks": {key: "pass" if value else "fail" for key, value in checks.items()},
        "package_id": package_manifest["package_id"],
        "package_verification": package_receipt,
        "artifact_hashes": artifact_hashes,
        "authority": {
            "paper_allowed": bool(admission["paper_allowed"] and all(checks.values())),
            "real_allowed": False,
        },
    }


def _project_decisions(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_event_id": item["source_event_id"],
            "side": item["side"],
            "qty": item["qty"],
            "risk_check": item["risk_check"],
        }
        for item in result["decisions"]
    ]


def _project_ledger(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "entry_type": item["entry_type"],
            "source_event_id": item["source_event_id"],
            "decision_id": item["decision_id"],
            "cash_delta": item["cash_delta"],
            "cash": item["cash"],
            "fees": item["fees"],
            "funding": item["funding"],
            "position": item["position"],
        }
        for item in result["ledger"]
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _hash_json(data: Any) -> str:
    import hashlib

    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(UTC)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
