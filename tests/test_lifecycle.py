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
