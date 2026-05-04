# Design Decisions

## Synthetic Domain Only

The public edition uses synthetic order and payment events. It intentionally excludes real trading data, exchange adapters, private paths, and production deployment logic.

## Public-Safe Edition

The project is derived from private backend architecture and verification patterns, not copied as a private source mirror. Public code, examples, and docs must remain synthetic and reviewable.

## Deterministic Outputs

Generated state and reports should be stable across runs when inputs are unchanged.

## Release Gate Scope

This project gates synthetic replay and reconciliation artifacts. It does not enforce dirty-worktree or deployment policies. Those controls belong in a separate agent workflow control-plane project.
