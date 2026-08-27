from __future__ import annotations

from scripts import public_safety_scan
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


def test_public_model_name_is_allowed_but_private_machine_name_is_not():
    rule = RULES["local_model_runtime"]

    assert rule.search("Local Qwen acceptance evidence") is None
    private_machine_name = "Stu" + "dio"
    assert rule.search(f"Executed on {private_machine_name}") is not None


def test_current_tree_scan_skips_tracked_files_deleted_from_worktree(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        public_safety_scan, "tracked_files", lambda root: ["deleted.json"]
    )

    assert public_safety_scan.scan_current_tree(tmp_path) == []
