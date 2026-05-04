# Architecture

The MVP is intentionally small:

```mermaid
flowchart LR
    A[Synthetic JSONL Events] --> B[Deterministic Replay]
    B --> C[Order Lifecycle]
    C --> D[Risk Policy]
    D --> E[Actual State]
    F[Expected State] --> G[Reconciliation]
    E --> G
    G --> H[Artifacts + Manifest]
    H --> I[Release Gate]
```

Each module is designed to be testable in isolation and runnable from the CLI.

## Modules

- `replay`: reads synthetic JSONL events and builds deterministic state.
- `orders`: enforces the synthetic order lifecycle.
- `risk`: applies public, synthetic policy checks.
- `reconcile`: compares expected and actual state.
- `artifacts`: writes JSON artifacts and SHA256-backed manifests.
- `gates`: turns replay, reconciliation, and artifact checks into pass/fail.

## Gate Contract

The gate is intentionally strict about artifacts. A process exit code alone is not enough. The expected JSON files must exist, be hashable, and be referenced from the manifest.
