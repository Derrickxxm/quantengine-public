# Example Manifest

`run_manifest.json` is the durable evidence record for a verification run. It records what was executed, which inputs were used, which artifacts were expected, and whether those artifacts can be hashed.

Example shape:

```json
{
  "schema_version": "quantengine_public.run_manifest.v1",
  "run_id": "demo-20260504160000",
  "created_at": "2026-05-04T16:00:00+00:00",
  "command": [
    "quantengine-public",
    "demo",
    "--artifact-dir",
    "artifacts/demo"
  ],
  "git": {
    "branch": "main",
    "commit": "abc1234",
    "dirty": false
  },
  "python": "3.11.9",
  "artifact_dir": "artifacts/demo",
  "input_hashes": {
    "examples/synthetic_events.jsonl": "sha256...",
    "examples/expected_state.json": "sha256...",
    "examples/config.yaml": "sha256..."
  },
  "artifact_hashes": {
    "artifacts/demo/actual_state.json": "sha256...",
    "artifacts/demo/replay_errors.json": "sha256...",
    "artifacts/demo/reconcile.json": "sha256...",
    "artifacts/demo/release_gate.json": "sha256..."
  },
  "expected_outputs": [
    {
      "path": "artifacts/demo/actual_state.json",
      "exists": true
    }
  ],
  "status": "completed"
}
```

## Field Reference

| Field | Purpose |
|---|---|
| `schema_version` | Identifies the manifest contract. |
| `run_id` | Unique run identifier for the verification run. |
| `created_at` | UTC timestamp for manifest creation. |
| `command` | Command shape used to produce the artifacts. |
| `git` | Local repository evidence: branch, commit, and dirty flag. |
| `python` | Python runtime version. |
| `artifact_dir` | Directory containing run outputs. |
| `input_hashes` | SHA256 hashes for input files that existed at run time. |
| `artifact_hashes` | SHA256 hashes for generated output files. |
| `expected_outputs` | Required artifacts and whether each exists. |
| `status` | High-level run status. |

## Why It Matters

The manifest is not a log. It is an evidence record that a release gate can inspect. Missing artifacts, incomplete hashes, or malformed manifest fields should cause the gate to fail.
