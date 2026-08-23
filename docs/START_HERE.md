# QuantEngine Public Edition: 60-Second Walkthrough

This repository shows a small, public-safe part of a larger trading-system architecture: how a system can prove that a Paper run and an independent Replay agree on the same economic result.

If you arrived here from a resume or portfolio, start with the idea that this
is not a strategy showcase. It is a public evidence slice for AI-assisted
engineering control: the system binds intent, package identity, runtime facts,
Replay facts, reconciliation, and release authority into a reviewable chain.

## What To Look At First

1. Open [release_verdict.json](../examples/showcase/release_verdict.json).
   The verdict is `PASS`, Paper authority is `true`, and Real authority is `false`.

2. Open [package_verification.json](../examples/showcase/package_verification.json).
   The package contains five declared files. Each file is verified by SHA-256. Changed, missing, extra, symlinked, or out-of-root files fail closed.

3. Open [reconciliation.json](../examples/showcase/reconciliation.json).
   Paper and Replay agree on package identity, input coverage, decisions, ledger, summary state, and authority boundary.

4. Open [stress_report.json](../examples/showcase/stress_report.json).
   The demo intentionally tests duplicate events, package drift, missing replay coverage, and economic mismatch.

## Why This Matters

In a trading system, the hard part is not only placing orders. The hard part is proving what happened after a change:

- which candidate was admitted;
- which input data was used;
- which package was executed;
- whether Paper and Replay computed the same state;
- whether Real authority was withheld unless every gate passed.

This public edition uses synthetic `QEP-USD` events only. The same engineering pattern can be reviewed without exposing strategy logic, account data, exchange connectivity, or production configuration.

## Code Pointers

- Paper runtime: `src/quantengine_public/demo.py::_run_paper_runtime`
- Replay oracle: `src/quantengine_public/demo.py::_run_replay_oracle`
- Package verification: `src/quantengine_public/demo.py::verify_package`
- Reconciliation: `src/quantengine_public/demo.py::_reconcile`
- Release verdict: `src/quantengine_public/demo.py::_release_verdict`
- Tests: `tests/test_demo_v2.py`
