"""DEC-0042 M6A public-presentation contract tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DESIGN = (ROOT / "docs" / "public_ogsm_v2_goal_control_slice_design_20260827.md").read_text(
    encoding="utf-8"
)
PROOF_DIGEST = "f06df976a6b5ce850f55c1d3660ee9369832f35fefebf7e6b6a265a63738c123"


def test_readme_distinguishes_v1_from_the_local_objective_bound_v2_proof():
    required = (
        "## Public OGSM V2: Objective-Bound Golden Path",
        "Golden Path v1",
        "Golden Path V2",
        "examples/golden_path_v2/proof.json",
        PROOF_DIGEST,
        "16 logical sections",
        "14 typed attacks",
        "deterministic-domain-neutral-fixture",
    )
    for phrase in required:
        assert phrase in README


def test_readme_shows_the_accepted_objective_control_and_revision_loops():
    required = (
        "Accepted Objective Contract",
        "Objective Contract digest",
        "Task / context / run / handoff / evidence",
        "Measure verdicts + AAR",
        "Owner decision",
        "Accepted revision",
        "Invalidate dependent work",
    )
    for phrase in required:
        assert phrase in README


def test_public_presentation_labels_local_evidence_and_unexecuted_boundaries():
    for document in (README, DESIGN):
        assert "Remote CI" in document
        assert "NOT RUN" in document
        assert "M6B" in document
        assert "M6C" in document
        assert "network model" in document
        assert "Research, Paper, Replay, or Real" in document
        assert "zero authority" in document


def test_design_records_completed_local_milestones_without_claiming_release():
    required = (
        "### M4 — Thin Control binding and invalidation (`COMPLETE_LOCAL`)",
        "### M5 — Golden Path V2 and adversarial proof (`COMPLETE_LOCAL`)",
        "### M6A — local public presentation (`COMPLETE_LOCAL`)",
        "`M6A_LOCAL_PRESENTATION_COMPLETE / WAIT_FOR_M6B_AUTHORIZATION`",
        PROOF_DIGEST,
    )
    for phrase in required:
        assert phrase in DESIGN
