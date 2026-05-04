from __future__ import annotations

import json

from quantengine_public.cli import main


def test_replay_unknown_event_fails_closed(tmp_path):
    events = tmp_path / "events.jsonl"
    out = tmp_path / "state.json"
    events.write_text('{"type": "unknown_event", "order_id": "order-001"}\n')

    assert main(["replay", "--events", str(events), "--out", str(out)]) == 1

    errors = json.loads((tmp_path / "state.errors.json").read_text())
    assert errors["errors"][0]["error"] == "unsupported event type: unknown_event"


def test_replay_missing_order_id_fails_closed_even_when_risk_rejects(tmp_path):
    events = tmp_path / "events.jsonl"
    out = tmp_path / "state.json"
    events.write_text('{"type": "order_created", "amount": 2500, "currency": "USD"}\n')

    assert main(["replay", "--events", str(events), "--out", str(out)]) == 1

    state = json.loads(out.read_text())
    errors = json.loads((tmp_path / "state.errors.json").read_text())
    assert state["orders"] == {}
    assert errors["errors"][0]["error"] == "event must include a non-empty order_id"


def test_replay_duplicate_order_id_fails_closed(tmp_path):
    events = tmp_path / "events.jsonl"
    out = tmp_path / "state.json"
    events.write_text(
        "\n".join(
            [
                '{"type": "order_created", "order_id": "order-001", "amount": 100, "currency": "USD"}',
                '{"type": "order_created", "order_id": "order-001", "amount": 200, "currency": "USD"}',
            ]
        )
        + "\n"
    )

    assert main(["replay", "--events", str(events), "--out", str(out)]) == 1

    errors = json.loads((tmp_path / "state.errors.json").read_text())
    assert errors["errors"][0]["error"] == "duplicate order_id: order-001"
