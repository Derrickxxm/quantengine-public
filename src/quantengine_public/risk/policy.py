from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class RiskPolicy:
    max_order_amount: float = 1000.0
    max_open_orders: int = 10
    allowed_currencies: tuple[str, ...] = ("USD",)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "RiskPolicy":
        if not data:
            return cls()
        currencies = data.get("allowed_currencies", ["USD"])
        if not isinstance(currencies, list) or not all(
            isinstance(item, str) for item in currencies
        ):
            raise ValueError("allowed_currencies must be a list of strings")
        return cls(
            max_order_amount=float(data.get("max_order_amount", 1000.0)),
            max_open_orders=int(data.get("max_open_orders", 10)),
            allowed_currencies=tuple(currencies),
        )

    def check_create(self, state: dict[str, Any], event: dict[str, Any]) -> RiskDecision:
        amount = float(event.get("amount", 0))
        if amount > self.max_order_amount:
            return RiskDecision(False, "max_order_amount")

        currency = str(event.get("currency", "USD"))
        if currency not in self.allowed_currencies:
            return RiskDecision(False, "currency_not_allowed")

        orders = state.get("orders", {})
        open_count = sum(
            1
            for order in orders.values()
            if order.get("status") in {"created", "accepted", "filled"}
        )
        if open_count >= self.max_open_orders:
            return RiskDecision(False, "max_open_orders")

        return RiskDecision(True)
