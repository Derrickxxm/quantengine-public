# QuantEngine Public Edition

[![CI](https://github.com/Derrickxxm/quantengine-public/actions/workflows/ci.yml/badge.svg)](https://github.com/Derrickxxm/quantengine-public/actions/workflows/ci.yml)

QuantEngine Public Edition is a sanitized public edition derived from the architecture and verification patterns of a private quantitative trading platform. It is not a mirror of the private codebase. The implementation uses synthetic data and public-safe examples to demonstrate strategy admission, immutable package identity, Paper runtime semantics, deterministic replay, reconciliation, artifact manifests, and fail-closed release gates.

This repository does not contain trading strategies, exchange adapters, real orders, account data, production configuration, or private deployment logic.

## Relationship to Private Work

This project is a public-safe edition derived from real backend architecture and verification patterns developed in a private system. It intentionally does not copy private strategies, production configuration, exchange connectivity, account data, or deployment logic.

The goal is to make the engineering patterns reviewable in public: deterministic replay, lifecycle validation, reconciliation, artifact manifests, and release gates.

## What This Shows

Many backend systems need to answer a simple question before a change is trusted:

```text
Given the same input events, does the system produce the expected state, and can we prove how that result was produced?
```

This project demonstrates that workflow with a small synthetic quantitative trading domain:

1. Admit a synthetic strategy candidate.
2. Materialize an immutable Paper package.
3. Run a bounded Paper scenario with decisions, fills, positions and accounting.
4. Replay the same window from pinned inputs.
5. Reconcile Paper and replay evidence.
6. Emit stress evidence and a fail-closed release verdict.

The point is not alpha. The point is backend verification for a trading system: identity, authority, replay, state transitions, reconciliation, artifacts, and release evidence.

## v2 Architecture

```mermaid
flowchart LR
    A["Research Candidate<br/>Synthetic strategy and research evidence"]
    B["Strategy Admission<br/>Independent validation and leakage guards"]
    C["Immutable Release Package<br/>Code, config, data and policy identity"]
    D["Paper Runtime<br/>Decision, risk, order, fill and accounting"]
    E["Same-Window Replay<br/>Pinned inputs and deterministic reconstruction"]
    F["Reconciliation<br/>Decision, fill, position and equity comparison"]
    G["Release Evidence<br/>Manifest, stress result and fail-closed verdict"]
    H["Synthetic Market Data<br/>Bars, funding and execution facts"]
    I["Authority Boundary<br/>Research / Paper / Real"]

    A --> B --> C --> D --> F --> G
    C --> E --> F
    H --> D
    H --> E
    I --> B
    I --> C
    I --> D
    I --> G
```

The diagram maps to the runnable v2 demo:

- Research Candidate: built-in candidate contract in `src/quantengine_public/demo.py`, written into `input_manifest.json`.
- Strategy Admission: independent checks written into `strategy_admission.json`.
- Immutable Release Package: `release-package/` files plus `package.manifest.json` SHA-256 identity.
- Paper Runtime: `paper_events.jsonl` and `paper_ledger.jsonl`.
- Same-Window Replay: independent replay evidence in `replay_result.json`.
- Reconciliation: semantic checks in `reconciliation.json`.
- Release Evidence: `stress_report.json`, `recovery_receipt.json` and `release_verdict.json`.
- Synthetic Market Data: built-in `QEP-USD` bars, funding and execution facts.
- Authority Boundary: Research and Paper are allowed; Real authority is always false.

For the full v2 design, see [QuantEngine Public v2 Design](docs/v2_public_architecture_design.md).

## Quick Start

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/quantengine-public --version
.venv/bin/quantengine-public demo
.venv/bin/quantengine-public validate --artifact-dir artifacts/demo
.venv/bin/python -m quantengine_public.demo --artifact-dir artifacts/demo-v2
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

Expected v2 demo output:

```json
{
  "checks": {
    "admission": "pass",
    "artifacts_exist": "pass",
    "package_identity": "pass",
    "reconciliation": "pass",
    "stress": "pass"
  },
  "verdict": "PASS"
}
```

In plain English, this means:

- `replay`: the synthetic events were processed without errors.
- `reconcile`: actual state matched expected state.
- `expected_outputs`: required artifact files were produced.
- `artifact_hashes`: output files were hashable and recorded.
- `manifest`: the run produced a structured evidence record.
- `release_gate`: all checks passed.

## Project Goals

- Demonstrate backend verification patterns with small, readable code.
- Keep runtime behavior deterministic and testable.
- Produce structured artifacts that can support release gates.
- Use only synthetic events and synthetic configuration.

## Five-Minute Walkthrough

See [Walkthrough](docs/walkthrough.md) for a plain-language explanation of the demo input, output, artifacts, and release gate.

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

`validate` recomputes artifact integrity from files on disk and fails if an artifact was edited after the manifest was generated.

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

- [Walkthrough](docs/walkthrough.md)
- [Synthetic Event Examples](docs/synthetic_events.md)
- [Architecture](docs/architecture.md)
- [Design Decisions](docs/design_decisions.md)
- [Example Manifest](docs/example_manifest.md)
- [Release Gate Examples](docs/release_gate_examples.md)
- [Security And P0 Bug Hunt](docs/security_bug_hunt_2026-05-04.md)
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
