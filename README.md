# QuantEngine Public Edition

[![CI](https://github.com/Derrickxxm/quantengine-public/actions/workflows/ci.yml/badge.svg)](https://github.com/Derrickxxm/quantengine-public/actions/workflows/ci.yml)

QuantEngine Public Edition is a sanitized backend platform inspired by a private production-style verification system. It demonstrates deterministic replay, order lifecycle simulation, risk-control boundaries, reconciliation, artifact manifests, and release gates using synthetic data only.

This repository does not contain trading strategies, exchange adapters, real orders, account data, production configuration, or private deployment logic.

## Quick Start

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/quantengine-public --version
.venv/bin/quantengine-public demo
.venv/bin/quantengine-public validate --artifact-dir artifacts/demo
```

Expected demo output:

```json
{
  "checks": {
    "artifact_hashes": "pass",
    "expected_outputs": "pass",
    "manifest": "pass",
    "reconcile": "pass",
    "replay": "pass"
  },
  "release_gate": "pass"
}
```

## Project Goals

- Demonstrate backend verification patterns with small, readable code.
- Keep runtime behavior deterministic and testable.
- Produce structured artifacts that can support release gates.
- Use only synthetic events and synthetic configuration.

## MVP Scope

The first version implements this closed loop:

```text
synthetic events -> replay -> order lifecycle -> risk check -> reconciliation -> manifest -> release gate
```

The demo writes these artifacts under `artifacts/demo/`:

- `actual_state.json`
- `replay_errors.json`
- `reconcile.json`
- `release_gate.json`
- `run_manifest.json`

## CLI

Replay synthetic events:

```bash
quantengine-public replay \
  --events examples/synthetic_events.jsonl \
  --out artifacts/manual/actual_state.json
```

Compare expected and actual state:

```bash
quantengine-public reconcile \
  --expected examples/expected_state.json \
  --actual artifacts/manual/actual_state.json \
  --out artifacts/manual/reconcile.json
```

Evaluate a release gate from artifacts:

```bash
quantengine-public gate \
  --manifest artifacts/demo/run_manifest.json \
  --reconcile artifacts/demo/reconcile.json \
  --replay-errors artifacts/demo/replay_errors.json \
  --out artifacts/demo/release_gate_from_cli.json
```

Validate a complete artifact directory:

```bash
quantengine-public validate --artifact-dir artifacts/demo
```

Run the complete verification loop:

```bash
quantengine-public demo --artifact-dir artifacts/demo
```

## Release Gate Checks

The release gate fails closed when:

- replay produced errors
- reconciliation found mismatches
- expected artifacts are missing
- artifact hashes are incomplete
- the manifest is structurally incomplete

## Documentation

- [Architecture](docs/architecture.md)
- [Design Decisions](docs/design_decisions.md)
- [Example Manifest](docs/example_manifest.md)
- [Release Gate Examples](docs/release_gate_examples.md)
- [Roadmap](ROADMAP.md)

## Repository Hygiene

- `CONTRIBUTING.md` describes local development.
- `SECURITY.md` defines what must never be submitted.
- GitHub Actions runs tests and the demo command.

## What This Project Does Not Include

- Real trading strategies or parameters.
- Exchange connectivity.
- Real orders, positions, balances, or account data.
- Production deployment scripts.
- Private paths, hosts, credentials, or environment names.
