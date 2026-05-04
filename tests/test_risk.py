from __future__ import annotations

import pytest

from quantengine_public.risk import RiskPolicy


def test_risk_policy_rejects_negative_max_amount():
    with pytest.raises(ValueError, match="max_order_amount must be positive"):
        RiskPolicy.from_mapping({"max_order_amount": -1})


def test_risk_policy_rejects_empty_currency_list():
    with pytest.raises(ValueError, match="allowed_currencies must not be empty"):
        RiskPolicy.from_mapping({"allowed_currencies": []})
