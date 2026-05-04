# Synthetic Event Examples

The demo uses a small order/payment event stream. It is intentionally generic and synthetic.

Source file:

```text
examples/synthetic_events.jsonl
```

## Event Stream

```json
{"type": "order_created", "order_id": "order-001", "amount": 100, "currency": "USD"}
{"type": "order_accepted", "order_id": "order-001"}
{"type": "payment_captured", "order_id": "order-001", "payment_id": "payment-001", "amount": 100}
{"type": "payment_captured", "order_id": "order-001", "payment_id": "payment-001", "amount": 100}
{"type": "order_closed", "order_id": "order-001"}
{"type": "order_created", "order_id": "order-002", "amount": 2500, "currency": "USD"}
```

## What Each Event Shows

| Event | Purpose |
|---|---|
| `order_created` for `order-001` | Creates a synthetic order. |
| `order_accepted` | Moves the order into an accepted state. |
| first `payment_captured` | Pays the order and fills it. |
| duplicate `payment_captured` | Demonstrates idempotency by payment id. |
| `order_closed` | Closes the filled order. |
| `order_created` for `order-002` | Demonstrates a risk rejection because the amount is above the configured maximum. |

## Expected Final State

`order-001` should be closed:

```json
{
  "status": "closed",
  "paid_amount": 100.0
}
```

`order-002` should be rejected:

```json
{
  "status": "rejected",
  "reject_reason": "max_order_amount"
}
```

The complete expected state is stored in:

```text
examples/expected_state.json
```

## Why The Duplicate Payment Exists

Distributed systems often receive duplicate messages. The demo treats repeated `payment_id` values as idempotent, so the order is not paid twice.
