# Release Gate Examples

The release gate converts replay, reconciliation, artifact, and manifest checks into a single pass/fail result.

## Passing Gate

```json
{
  "checks": {
    "artifact_integrity": "pass",
    "artifact_hashes": "pass",
    "expected_outputs": "pass",
    "manifest": "pass",
    "reconcile": "pass",
    "replay": "pass"
  },
  "release_gate": "pass"
}
```

This means:

- replay completed without errors
- reconciliation found no mismatches
- all expected artifacts exist
- generated artifacts are hashable
- the manifest has the required structure

## Failing Gate: Reconciliation Mismatch

```json
{
  "checks": {
    "artifact_integrity": "pass",
    "artifact_hashes": "pass",
    "expected_outputs": "pass",
    "manifest": "pass",
    "reconcile": "fail",
    "replay": "pass"
  },
  "release_gate": "fail"
}
```

The corresponding `reconcile.json` should explain the exact mismatch:

```json
{
  "mismatches": [
    {
      "actual": "accepted",
      "expected": "closed",
      "path": "$.orders.order-001.status",
      "severity": "error"
    }
  ],
  "status": "fail"
}
```

## Failing Gate: Missing Artifact

```json
{
  "checks": {
    "artifact_integrity": "fail",
    "artifact_hashes": "fail",
    "expected_outputs": "fail",
    "manifest": "pass",
    "reconcile": "pass",
    "replay": "pass"
  },
  "release_gate": "fail"
}
```

The gate fails even if the process exited successfully, because expected artifacts are part of the verification contract.

## Failing Gate: Tampered Artifact

```json
{
  "artifact_mismatches": [
    {
      "actual_sha256": "new-sha256",
      "error": "sha256 mismatch",
      "expected_sha256": "old-sha256",
      "path": "artifacts/demo/actual_state.json"
    }
  ],
  "checks": {
    "artifact_integrity": "fail",
    "artifact_hashes": "pass",
    "expected_outputs": "pass",
    "manifest": "pass",
    "reconcile": "pass",
    "replay": "pass"
  },
  "release_gate": "fail"
}
```

`validate` and `gate` recompute artifact hashes from files on disk. If a report is edited after the manifest is written, the gate fails.

## CLI Exit Codes

| Command Result | Exit Code |
|---|---:|
| Gate pass | `0` |
| Gate fail | `1` |
| Invalid CLI usage | argparse default non-zero exit |
