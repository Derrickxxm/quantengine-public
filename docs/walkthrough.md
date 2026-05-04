# Five-Minute Walkthrough

This walkthrough explains the demo without assuming prior knowledge of the private system that inspired it.

## The Problem

Backend systems often process events:

- an order is created
- the order is accepted
- a payment is captured
- the order is closed

In a real system, bugs often happen when state changes are not verified end to end. A service may report success, but a file may be missing, a state transition may be wrong, or the result may not match the expected state.

This project shows a small verification loop for that problem.

## The Demo Input

The demo reads synthetic events from:

```text
examples/synthetic_events.jsonl
```

Example:

```json
{"type": "order_created", "order_id": "order-001", "amount": 100, "currency": "USD"}
{"type": "order_accepted", "order_id": "order-001"}
{"type": "payment_captured", "order_id": "order-001", "payment_id": "payment-001", "amount": 100}
{"type": "order_closed", "order_id": "order-001"}
```

These are not real orders. They are synthetic examples designed to show backend state verification.

## What Replay Does

Replay rebuilds state from the event stream.

For `order-001`, replay should produce:

```json
{
  "status": "closed",
  "paid_amount": 100.0
}
```

Replay also enforces lifecycle rules:

- an order must be created before it is accepted
- an order must be accepted before payment can be captured
- an order must be filled before it can be closed
- unsupported events fail closed

## What Risk Policy Does

The demo includes a synthetic risk policy:

```yaml
risk:
  max_order_amount: 1000
  max_open_orders: 5
  allowed_currencies:
    - USD
```

An oversized synthetic order is rejected. This demonstrates how a backend can keep policy checks separate from event replay.

## What Reconciliation Does

Reconciliation compares:

```text
expected_state.json vs actual_state.json
```

If they differ, the tool reports an exact path:

```text
$.orders.order-001.status
```

That makes failures easier to diagnose than a vague "test failed" message.

## What Artifacts Are Produced

The demo writes:

```text
artifacts/demo/
  actual_state.json
  replay_errors.json
  reconcile.json
  release_gate.json
  run_manifest.json
```

These files are evidence. They show what happened during the run and whether the run can be trusted.

## What The Manifest Proves

`run_manifest.json` records:

- command
- git branch and commit
- Python version
- input hashes
- artifact hashes
- expected output paths
- run status

This means the result is not just a console message. It has a structured evidence record.

## What The Release Gate Means

A passing gate looks like this:

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

In plain English:

- events replayed successfully
- actual state matched expected state
- expected artifacts exist
- artifacts were hashed
- manifest is valid

If any check fails, the gate fails.

## Why This Matters

This is the same class of engineering problem found in payment systems, workflow engines, data pipelines, order systems, and other backend platforms:

```text
Can we replay inputs, verify state, produce artifacts, and decide whether a change is safe?
```

This public edition keeps the domain synthetic while demonstrating the backend verification pattern clearly.
