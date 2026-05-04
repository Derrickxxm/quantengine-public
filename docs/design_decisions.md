# Design Decisions

## Synthetic Domain Only

The public edition uses synthetic order and payment events. It intentionally excludes real trading data, exchange adapters, private paths, and production deployment logic.

## Deterministic Outputs

Generated state and reports should be stable across runs when inputs are unchanged.

## Release Gate Scope

This project gates synthetic replay and reconciliation artifacts. It does not enforce dirty-worktree or deployment policies. Those controls belong in a separate agent workflow control-plane project.
