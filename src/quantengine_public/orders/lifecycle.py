from __future__ import annotations

from typing import Any


class OrderLifecycleError(ValueError):
    """Raised when a synthetic event violates the order lifecycle."""


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = event.get("type")
    supported_types = {
        "order_created",
        "order_accepted",
        "order_rejected",
        "payment_captured",
        "order_closed",
    }
    if event_type not in supported_types:
        raise OrderLifecycleError(f"unsupported event type: {event_type}")

    order_id = event.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise OrderLifecycleError("event must include a non-empty order_id")

    orders = state.setdefault("orders", {})

    if event_type == "order_created":
        if order_id in orders:
            raise OrderLifecycleError(f"duplicate order_id: {order_id}")
        amount = _positive_number(event, "amount")
        currency = _string_value(event, "currency", default="USD")
        orders[order_id] = {
            "status": "created",
            "amount": amount,
            "currency": currency,
            "paid_amount": 0,
            "payments": [],
            "reject_reason": None,
        }
        return

    order = orders.get(order_id)
    if order is None:
        raise OrderLifecycleError(f"unknown order_id: {order_id}")

    if event_type == "order_accepted":
        _require_status(order, order_id, {"created"})
        order["status"] = "accepted"
        return

    if event_type == "order_rejected":
        _require_status(order, order_id, {"created", "accepted"})
        order["status"] = "rejected"
        order["reject_reason"] = str(event.get("reason") or "unspecified")
        return

    if event_type == "payment_captured":
        _require_status(order, order_id, {"accepted", "filled"})
        payment_id = _string_value(event, "payment_id")
        if payment_id in order["payments"]:
            return
        amount = _positive_number(event, "amount")
        order["payments"].append(payment_id)
        order["paid_amount"] = round(float(order["paid_amount"]) + amount, 10)
        if float(order["paid_amount"]) >= float(order["amount"]):
            order["status"] = "filled"
        return

    if event_type == "order_closed":
        _require_status(order, order_id, {"filled"})
        order["status"] = "closed"
        return

    raise OrderLifecycleError(f"unsupported event type: {event_type}")


def _require_status(order: dict[str, Any], order_id: str, allowed: set[str]) -> None:
    status = str(order.get("status"))
    if status not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise OrderLifecycleError(
            f"order {order_id} has status {status}; expected one of: {allowed_text}"
        )


def _positive_number(event: dict[str, Any], key: str) -> float:
    value = event.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise OrderLifecycleError(f"{key} must be a positive number")
    return float(value)


def _string_value(
    event: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
) -> str:
    value = event.get(key, default)
    if not isinstance(value, str) or not value:
        raise OrderLifecycleError(f"{key} must be a non-empty string")
    return value
