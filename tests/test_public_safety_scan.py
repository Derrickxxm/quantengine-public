from __future__ import annotations

from scripts.public_safety_scan import RULES


def test_public_architecture_names_are_allowed_but_private_locators_are_not():
    rule = RULES["private_repository_locator"]

    assert rule.search("QuantLab produces a synthetic trial ledger") is None
    assert rule.search("QuantStrategies owns candidate lineage") is None
    private_lab_locator = "git@github.com:" + "Derrickxxm/" + "Quant" + "Lab.git"
    private_strategy_locator = (
        "https://github.com/" + "Derrickxxm/" + "Quant" + "Strategies/private"
    )
    assert rule.search(private_lab_locator) is not None
    assert rule.search(private_strategy_locator) is not None
