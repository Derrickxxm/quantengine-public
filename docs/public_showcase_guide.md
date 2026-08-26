# Public Showcase Guide

This repository demonstrates an evidence-controlled AI software delivery
architecture through two connected public-safe slices:

1. a 14-artifact software-delivery Golden Path; and
2. a synthetic QuantEngine Paper / Replay runtime used as the reference domain.

The first slice proves how evidence moves between delivery roles. The second
proves the runtime facts that independent Quality and Release control consume.

## Five-Minute Review

### 1. Start with final authority

Open
[`examples/golden_path/evidence/13_release_verdict.json`](../examples/golden_path/evidence/13_release_verdict.json).

Confirm:

- producer is `public_release_controller`;
- status is `PASS`;
- Paper authority is `true`;
- Real and deployment authority are `false`;
- upstream includes both runtime evidence and independent Quality.

### 2. Confirm the runtime producer did not authorize itself

Open
[`examples/golden_path/evidence/09_runtime_evidence.json`](../examples/golden_path/evidence/09_runtime_evidence.json).

The artifact contains QuantEngine package, Paper, Replay, reconciliation,
stress, recovery, and engine-verdict evidence. Its delivery-level authority is
entirely false. The nested engine verdict is a runtime recommendation and input
to release control, not the final delivery authority.

### 3. Confirm independent Quality consumed runtime evidence

Open
[`examples/golden_path/evidence/12_quality_verdict.json`](../examples/golden_path/evidence/12_quality_verdict.json).

Its upstream edges must include the exact runtime-evidence digest, QCS receipt,
test result, and Ops plan. Quality itself grants no Paper, Real, or deployment
authority.

### 4. Inspect a negative path

Open
[`examples/golden_path/negative/provenance-mismatch/`](../examples/golden_path/negative/provenance-mismatch/).

The directory preserves:

- the rejected request;
- the valid causal prefix;
- a request-bound blocker;
- zero authority.

The blocker does not erase or rewrite the evidence that preceded failure.

### 5. Inspect the QuantEngine runtime proof

Review:

- [package verification](../examples/showcase/package_verification.json);
- [Paper events](../examples/showcase/paper_events.jsonl);
- [independent Replay](../examples/showcase/replay_result.json);
- [reconciliation](../examples/showcase/reconciliation.json);
- [stress evidence](../examples/showcase/stress_report.json);
- [recovery evidence](../examples/showcase/recovery_receipt.json);
- [runtime verdict](../examples/showcase/release_verdict.json).

The reference runtime checks package tampering, input coverage, decisions,
fills, positions, cash, fees, funding, equity, reconciliation, stress, and
recovery. It does not prove trading alpha.

## What The Golden Path Demonstrates

| Capability | Public evidence |
| --- | --- |
| Frozen outcome | `01_ogsm.json`, `02_plane_task.json` |
| Architecture scope | `03_architecture_packet.json` |
| Test-first validation | `04_validation_plan.json` |
| Bounded implementation | `05_worker_handoff.json`, `06_patch_manifest.json` |
| Deterministic tests and Ops | `07_test_result.json`, `08_ops_delivery_plan.json` |
| Zero-authority runtime proof | `09_runtime_evidence.json` |
| Risk evidence | `10_qcs_manifest.json`, `11_qcs_receipt.json` |
| Independent evidence admission | `12_quality_verdict.json` |
| Deterministic authority | `13_release_verdict.json` |
| Learning index | `14_aar.json` |

## Run It

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m quantengine_public.delivery.golden_path \
  --artifact-dir artifacts/public-golden-path
```

The harness is deterministic and synthetic. It does not dispatch external
Agents. The four Skills under [`skills/`](../skills/) preserve the operating
methods that a Native-Agent runtime must follow.

For the complete architecture, see
[`docs/multi_agent_public_architecture.md`](multi_agent_public_architecture.md).
