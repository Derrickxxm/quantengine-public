from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantengine_public.orders import OrderLifecycleError, apply_event
from quantengine_public.risk import RiskPolicy


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    state: dict[str, Any]
    errors: list[dict[str, Any]]


def replay_events_file(events_path: Path, policy: RiskPolicy | None = None) -> ReplayResult:
    state: dict[str, Any] = {"orders": {}}
    errors: list[dict[str, Any]] = []
    active_policy = policy or RiskPolicy()

    for line_no, raw_line in enumerate(events_path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("event must be a JSON object")
            if event.get("type") == "order_created":
                decision = active_policy.check_create(state, event)
                if not decision.allowed:
                    order_id = str(event.get("order_id"))
                    state.setdefault("orders", {})[order_id] = {
                        "status": "rejected",
                        "amount": float(event.get("amount", 0)),
                        "currency": str(event.get("currency", "USD")),
                        "paid_amount": 0,
                        "payments": [],
                        "reject_reason": decision.reason,
                    }
                    continue
            _safe_apply(state, event, line_no, errors)
        except Exception as exc:  # noqa: BLE001 - report all replay failures.
            errors.append({"line": line_no, "error": str(exc), "raw": raw_line})

    return ReplayResult(ok=not errors, state=_sorted_state(state), errors=errors)


def _safe_apply(
    state: dict[str, Any],
    event: dict[str, Any],
    line_no: int,
    errors: list[dict[str, Any]],
) -> None:
    try:
        apply_event(state, event)
    except OrderLifecycleError as exc:
        errors.append({"line": line_no, "error": str(exc), "event": event})


def _sorted_state(state: dict[str, Any]) -> dict[str, Any]:
    orders = state.get("orders", {})
    return {
        "orders": {
            order_id: orders[order_id]
            for order_id in sorted(orders)
        }
    }
