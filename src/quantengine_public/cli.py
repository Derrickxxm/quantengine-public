from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import strftime

from quantengine_public import __version__
from quantengine_public.artifacts import build_manifest, verify_manifest_artifacts, write_json
from quantengine_public.demo import run_demo as run_demo_v2
from quantengine_public.gates import evaluate_gate
from quantengine_public.reconcile import reconcile_states
from quantengine_public.replay import replay_events_file
from quantengine_public.risk import RiskPolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantengine-public",
        description="Synthetic backend verification toolkit.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the package version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")
    replay = subparsers.add_parser("replay", help="Replay synthetic events.")
    replay.add_argument("--events", required=True, type=Path)
    replay.add_argument("--out", required=True, type=Path)

    reconcile = subparsers.add_parser("reconcile", help="Compare expected and actual state.")
    reconcile.add_argument("--expected", required=True, type=Path)
    reconcile.add_argument("--actual", required=True, type=Path)
    reconcile.add_argument("--out", required=True, type=Path)

    gate = subparsers.add_parser("gate", help="Evaluate a release gate from artifacts.")
    gate.add_argument("--manifest", required=True, type=Path)
    gate.add_argument("--reconcile", required=True, type=Path)
    gate.add_argument("--replay-errors", required=True, type=Path)
    gate.add_argument("--out", type=Path)

    validate = subparsers.add_parser("validate", help="Validate a demo artifact directory.")
    validate.add_argument("--artifact-dir", required=True, type=Path)

    demo = subparsers.add_parser("demo", help="Run the synthetic verification demo.")
    demo.add_argument("--artifact-dir", type=Path, default=Path("artifacts/demo"))

    demo_v2 = subparsers.add_parser("demo-v2", help="Run the QuantEngine Public v2 Paper/replay demo.")
    demo_v2.add_argument("--artifact-dir", type=Path, default=Path("artifacts/demo-v2"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command == "replay":
        result = replay_events_file(args.events)
        write_json(args.out, result.state)
        if result.errors:
            write_json(args.out.with_suffix(".errors.json"), {"errors": result.errors})
        return 0 if result.ok else 1

    if args.command == "reconcile":
        expected = _read_json(args.expected)
        actual = _read_json(args.actual)
        result = reconcile_states(expected, actual)
        write_json(
            args.out,
            {"status": "pass" if result.ok else "fail", "mismatches": result.mismatches},
        )
        return 0 if result.ok else 1

    if args.command == "gate":
        manifest = _read_json(args.manifest)
        reconcile = _read_json(args.reconcile)
        replay_errors = _read_json(args.replay_errors)
        gate = _evaluate_gate_from_reports(manifest, reconcile, replay_errors)
        artifact_mismatches = verify_manifest_artifacts(manifest)
        if artifact_mismatches:
            gate["release_gate"] = "fail"
            gate["checks"]["artifact_integrity"] = "fail"
            gate["artifact_mismatches"] = artifact_mismatches
        else:
            gate["checks"]["artifact_integrity"] = "pass"
        if args.out:
            write_json(args.out, gate)
        print(json.dumps(gate, indent=2, sort_keys=True))
        return 0 if gate["release_gate"] == "pass" else 1

    if args.command == "validate":
        return _validate_artifact_dir(args.artifact_dir)

    if args.command == "demo":
        return _run_demo(args.artifact_dir)

    if args.command == "demo-v2":
        result = run_demo_v2(args.artifact_dir)
        print(json.dumps(result["release_verdict"], indent=2, sort_keys=True))
        return 0 if result["release_verdict"]["verdict"] == "PASS" else 1

    parser.print_help()
    return 0


def _validate_artifact_dir(artifact_dir: Path) -> int:
    manifest_path = artifact_dir / "run_manifest.json"
    reconcile_path = artifact_dir / "reconcile.json"
    replay_errors_path = artifact_dir / "replay_errors.json"
    gate_path = artifact_dir / "release_gate.json"

    missing = [
        path
        for path in [manifest_path, reconcile_path, replay_errors_path]
        if not path.exists()
    ]
    if missing:
        gate = {
            "release_gate": "fail",
            "checks": {
                "artifact_dir": "fail",
            },
            "missing": [str(path) for path in missing],
        }
        write_json(gate_path, gate)
        print(json.dumps(gate, indent=2, sort_keys=True))
        return 1

    gate = _evaluate_gate_from_reports(
        _read_json(manifest_path),
        _read_json(reconcile_path),
        _read_json(replay_errors_path),
    )
    artifact_mismatches = verify_manifest_artifacts(_read_json(manifest_path))
    if artifact_mismatches:
        gate["release_gate"] = "fail"
        gate["checks"]["artifact_integrity"] = "fail"
        gate["artifact_mismatches"] = artifact_mismatches
    else:
        gate["checks"]["artifact_integrity"] = "pass"
    write_json(gate_path, gate)
    print(json.dumps(gate, indent=2, sort_keys=True))
    return 0 if gate["release_gate"] == "pass" else 1


def _run_demo(artifact_dir: Path) -> int:
    root = Path.cwd()
    events_path = root / "examples" / "synthetic_events.jsonl"
    expected_path = root / "examples" / "expected_state.json"
    config_path = root / "examples" / "config.yaml"

    artifact_dir.mkdir(parents=True, exist_ok=True)
    actual_path = artifact_dir / "actual_state.json"
    replay_errors_path = artifact_dir / "replay_errors.json"
    reconcile_path = artifact_dir / "reconcile.json"
    manifest_path = artifact_dir / "run_manifest.json"
    gate_path = artifact_dir / "release_gate.json"

    policy = RiskPolicy.from_mapping(_load_yaml_mapping(config_path).get("risk"))
    replay_result = replay_events_file(events_path, policy)
    write_json(actual_path, replay_result.state)
    write_json(replay_errors_path, {"errors": replay_result.errors})

    expected = json.loads(expected_path.read_text())
    reconcile_result = reconcile_states(expected, replay_result.state)
    write_json(
        reconcile_path,
        {
            "status": "pass" if reconcile_result.ok else "fail",
            "mismatches": reconcile_result.mismatches,
        },
    )

    command = ["quantengine-public", "demo", "--artifact-dir", str(artifact_dir)]
    manifest = build_manifest(
        run_id=f"demo-{strftime('%Y%m%d%H%M%S')}",
        command=command,
        artifact_dir=artifact_dir,
        inputs=[events_path, expected_path, config_path],
        outputs=[actual_path, replay_errors_path, reconcile_path],
        status="completed" if replay_result.ok and reconcile_result.ok else "failed",
    )
    gate = evaluate_gate(
        replay_ok=replay_result.ok,
        reconcile_ok=reconcile_result.ok,
        manifest=manifest,
    )
    write_json(gate_path, gate)

    manifest = build_manifest(
        run_id=manifest["run_id"],
        command=command,
        artifact_dir=artifact_dir,
        inputs=[events_path, expected_path, config_path],
        outputs=[actual_path, replay_errors_path, reconcile_path, gate_path],
        status="completed" if gate["release_gate"] == "pass" else "failed",
    )
    write_json(manifest_path, manifest)

    print(json.dumps(gate, indent=2, sort_keys=True))
    return 0 if gate["release_gate"] == "pass" else 1


def _load_yaml_mapping(path: Path) -> dict:
    import yaml

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _read_json(path: Path):
    return json.loads(path.read_text())


def _evaluate_gate_from_reports(
    manifest: dict,
    reconcile: dict,
    replay_errors: dict,
) -> dict:
    return evaluate_gate(
        replay_ok=not replay_errors.get("errors"),
        reconcile_ok=reconcile.get("status") == "pass",
        manifest=manifest,
    )


if __name__ == "__main__":
    raise SystemExit(main())
