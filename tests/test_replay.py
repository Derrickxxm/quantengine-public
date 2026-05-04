from __future__ import annotations

from pathlib import Path

from quantengine_public.replay import replay_events_file
from quantengine_public.risk import RiskPolicy


def test_replay_closes_order_and_deduplicates_payment():
    result = replay_events_file(Path("examples/synthetic_events.jsonl"), RiskPolicy())

    assert result.ok
    assert result.state["orders"]["order-001"]["status"] == "closed"
    assert result.state["orders"]["order-001"]["paid_amount"] == 100.0
    assert result.state["orders"]["order-001"]["payments"] == ["payment-001"]


def test_risk_rejects_oversized_order():
    result = replay_events_file(Path("examples/synthetic_events.jsonl"), RiskPolicy())

    assert result.state["orders"]["order-002"]["status"] == "rejected"
    assert result.state["orders"]["order-002"]["reject_reason"] == "max_order_amount"
