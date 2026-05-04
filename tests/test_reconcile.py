from __future__ import annotations

from quantengine_public.reconcile import reconcile_states


def test_reconcile_passes_matching_state():
    result = reconcile_states({"a": {"b": 1}}, {"a": {"b": 1}})

    assert result.ok
    assert result.mismatches == []


def test_reconcile_reports_path_for_mismatch():
    result = reconcile_states({"a": {"b": 1}}, {"a": {"b": 2}})

    assert not result.ok
    assert result.mismatches[0]["path"] == "$.a.b"
