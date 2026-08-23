# Public Showcase Guide

This repository is a public-safe capability slice from a larger AI-assisted
engineering control system.

The public demo does not try to prove trading alpha. It proves a narrower
backend control problem:

```text
Can a candidate move through admission, packaging, Paper execution,
independent Replay, reconciliation, and a fail-closed verdict with evidence
that can be inspected after the run?
```

## What This Repository Demonstrates

| Capability | Public evidence |
| --- | --- |
| Candidate admission | `examples/showcase/strategy_admission.json` |
| Package identity | `examples/showcase/package.manifest.json` |
| Package tamper detection | `examples/showcase/package_verification.json` and `tests/test_demo_v2.py` |
| Paper runtime evidence | `examples/showcase/paper_events.jsonl` and `examples/showcase/paper_ledger.jsonl` |
| Independent Replay | `examples/showcase/replay_result.json` |
| Paper / Replay reconciliation | `examples/showcase/reconciliation.json` |
| Fault and recovery behavior | `examples/showcase/stress_report.json` and `examples/showcase/recovery_receipt.json` |
| Final bounded authority | `examples/showcase/release_verdict.json` |

## What Makes The Slice Useful

The implementation is intentionally small, but the invariants are the important
part:

- every stage names the upstream identity it consumed;
- package content is verified by digest, not by filename or trust;
- Paper and Replay are separate implementations;
- reconciliation checks input coverage, decisions, fills, positions, cash,
  fees, funding, equity, and authority;
- missing or inconsistent evidence produces a fail-closed verdict;
- the public demo grants Paper authority but withholds Real authority.

This is the same shape required for larger AI-assisted delivery: generated work
must be bound to reviewed intent, executable artifacts, independent checks, and
readable evidence.

## How To Review It In Five Minutes

1. Open `examples/showcase/release_verdict.json`.
   Confirm `release_gate` is `PASS`, `paper_authority` is `true`, and
   `real_authority` is `false`.

2. Open `examples/showcase/package.manifest.json`.
   Confirm the package is content-addressed and every material file has a
   digest.

3. Open `examples/showcase/reconciliation.json`.
   Confirm Paper and Replay agree on package identity, input coverage, ledger,
   positions, cash, and final equity.

4. Open `tests/test_demo_v2.py`.
   Look for negative tests covering package tampering, event duplication,
   missing replay input, and economic mismatch.

5. Run the project locally:

   ```bash
   python -m venv .venv
   .venv/bin/python -m pip install -e ".[dev]"
   .venv/bin/python -m pytest
   .venv/bin/quantengine-public demo-v2 --artifact-dir artifacts/demo-v2
   ```

## Relationship To The Larger System

The private system contains research workspaces, task control, quality tools,
provider runbooks, runtime environments, and evidence storage. Those pieces are
not published here.

This repository publishes the reviewable core pattern:

```text
research candidate
  -> admission result
  -> lineage-bound release package
  -> Paper runtime evidence
  -> independent Replay evidence
  -> reconciliation evidence
  -> bounded release verdict
```

For the surrounding system context, see
[`docs/ai_control_system_context.md`](ai_control_system_context.md).
