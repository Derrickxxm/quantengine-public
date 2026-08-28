from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

from quantengine_public import __version__
from quantengine_public.demo import _scenario

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DESCRIPTION = (
    "Evidence-controlled AI software delivery with a QuantEngine reference runtime."
)
PINNED_ACTIONS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
}
CI_CONSTRAINTS = {
    "coverage==7.15.4",
    "jsonschema==4.26.0",
    "openai-agents==0.22.0",
    "pip==26.2.1",
    "pytest==9.1.1",
    "pyyaml==6.0.3",
    "setuptools==84.0.0",
    "wheel==0.48.0",
}


def test_package_identity_and_python_support_are_bounded() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert project["description"] == CANONICAL_DESCRIPTION
    assert project["requires-python"] == ">=3.11,<3.15"
    assert __version__ == "0.6.0"


def test_published_qwen_acceptance_stays_local_and_zero_authority() -> None:
    evidence = json.loads(
        (
            ROOT / "docs/evidence/qwen_phase2_overnight_acceptance_20260827.json"
        ).read_text()
    )

    assert evidence["verdict"] == "PASS"
    assert evidence["happy_path_runs"] == {"attempted": 24, "passed": 24}
    assert evidence["adversarial_suites"] == {"attempted": 3, "passed": 3}
    assert all(value is False for value in evidence["claims"].values())


def test_runtime_dependency_evidence_matches_python_support_bound() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert _scenario()["runtime_dependencies"]["python"] == project["requires-python"]


def test_ci_uses_reviewed_immutable_action_identities() -> None:
    workflow_text = (ROOT / ".github/workflows/ci.yml").read_text()
    observed = {
        name: (digest, version)
        for name, digest, version in re.findall(
            r"uses:\s+([^@\s]+)@([0-9a-f]{40})\s+#\s+(v[^\s]+)",
            workflow_text,
        )
    }

    assert observed == PINNED_ACTIONS
    assert re.search(r"uses:\s+[^\s]+@v\d", workflow_text) is None


def test_ci_proves_supported_python_and_quality_contracts() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["test"]
    commands = [step["run"] for step in job["steps"] if "run" in step]

    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.14"]
    install_commands = [command for command in commands if "pip install" in command]
    assert all(
        "--constraint constraints/ci.txt" in command for command in install_commands
    )
    assert any(
        '--no-build-isolation -e ".[dev]"' in command for command in install_commands
    )
    assert (
        "python -m coverage run --branch --source=src/quantengine_public -m pytest"
        in commands
    )
    assert "python -m coverage report --skip-covered --fail-under=82" in commands
    assert "python scripts/run_hosted_phase2.py" in commands
    assert all("run_hosted_phase2.py --execute" not in command for command in commands)
    assert (
        "python scripts/native_agent_public_proof.py --artifact-dir artifacts/native-agent-public-proof"
        in commands
    )


def test_ci_top_level_toolchain_is_explicitly_constrained() -> None:
    constraints = ROOT / "constraints/ci.txt"

    assert constraints.is_file()
    observed = {
        line.strip().lower()
        for line in constraints.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert observed == CI_CONSTRAINTS


def test_historical_m8_review_is_not_labeled_as_current_release() -> None:
    review = (ROOT / "docs/interviewer_review_backlog_20260826.md").read_text()

    assert "Current release re-reviewed: `v0.5.0`" not in review
    assert "M8 release re-reviewed: `v0.5.0`" in review
    assert "M9 subsequently published `v0.5.1`" in review
