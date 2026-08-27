"""Red contracts for the Owner-approved hosted Phase 2 gates."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from quantengine_public.agent_platform.hosted_phase2 import (
    MODEL_ID,
    OWNER_DECISION,
    DevelopmentLoopReceipt,
    DurableRunClaim,
    HostedPhase2Error,
    HostedPhase2Policy,
    HostedRunAuthority,
    HostedStageObservation,
    HostedStagePlan,
    LocalSourceLookup,
    RoleReceipt,
    authorize_stage as build_stage_authorization,
    derive_development_loop_receipt,
    derive_handoff_receipt,
    estimate_cost_microusd,
    evaluate_stage,
)


def authorize_stage(
    candidate: HostedStagePlan,
    current_policy: HostedPhase2Policy,
    *,
    owner_decision: str,
    predecessor_receipt_digest: str,
    spent_microusd: int,
):
    return build_stage_authorization(
        candidate,
        current_policy,
        owner_decision=owner_decision,
        run_identity="a" * 64,
        sequence=0,
        prompt_digest="b" * 64,
        predecessor_receipt_digest=predecessor_receipt_digest,
        spent_microusd=spent_microusd,
    )


def plan(stage: str = "architecture") -> HostedStagePlan:
    stage_bounds = {
        "architecture": ((), ()),
        "readonly_tool": (("lookup_public_source",), ()),
        "handoff": ((), ("architecture", "test")),
        "development_loop": ((), ("architecture", "test", "development", "quality")),
    }
    tools, route = stage_bounds[stage]
    return HostedStagePlan(
        stage=stage,
        task_id="TASKSYS-1318",
        task_revision="p2-v1",
        source_identity="1" * 64,
        context_digest="2" * 64,
        agent_graph_identity="3" * 64,
        predecessor_receipt_digest="4" * 64,
        model=MODEL_ID,
        max_turns=2,
        max_input_chars=24_000,
        max_output_tokens=1_200,
        timeout_seconds=90,
        trace_mode="disabled",
        evidence_mode="digest_only",
        tool_names=tools,
        handoff_route=route,
    )


def policy() -> HostedPhase2Policy:
    return HostedPhase2Policy()


def observation(**changes: object) -> HostedStageObservation:
    values: dict[str, object] = {
        "stage": "architecture",
        "plan_digest": plan().plan_digest,
        "output": {
            "summary": "Add an explicit hosted execution boundary.",
            "affected_paths": ["src/quantengine_public/agent_platform/hosted_phase2.py"],
            "risks": ["budget drift"],
            "validation": ["run deterministic gates"],
        },
        "requests": 1,
        "input_tokens": 4_000,
        "output_tokens": 600,
        "latency_ms": 1_250,
        "tool_calls": (),
        "last_agent": "architecture",
        "handoff_count": 0,
    }
    values.update(changes)
    return HostedStageObservation(**values)


def test_exact_owner_decision_and_predecessor_are_required() -> None:
    approved = authorize_stage(
        plan(),
        policy(),
        owner_decision=OWNER_DECISION,
        predecessor_receipt_digest="4" * 64,
        spent_microusd=0,
    )

    assert approved.verdict == "AUTHORIZED"
    assert approved.model == MODEL_ID
    assert approved.trace_mode == "disabled"
    assert approved.remaining_budget_microusd < 100_000
    assert len(approved.authorization_digest) == 64

    with pytest.raises(HostedPhase2Error, match="owner_decision_mismatch"):
        authorize_stage(
            plan(),
            policy(),
            owner_decision="DEC-OTHER",
            predecessor_receipt_digest="4" * 64,
            spent_microusd=0,
        )
    with pytest.raises(HostedPhase2Error, match="predecessor_receipt_mismatch"):
        authorize_stage(
            plan(),
            policy(),
            owner_decision=OWNER_DECISION,
            predecessor_receipt_digest="5" * 64,
            spent_microusd=0,
        )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"model": "another-model"}, "model_not_authorized"),
        ({"max_turns": 3}, "max_turns_exceeds_policy"),
        ({"max_input_chars": 24_001}, "max_input_chars_exceeds_policy"),
        ({"max_output_tokens": 1_201}, "max_output_tokens_exceeds_policy"),
        ({"timeout_seconds": 91}, "timeout_exceeds_policy"),
        ({"trace_mode": "hosted"}, "hosted_trace_not_authorized"),
        ({"evidence_mode": "raw"}, "raw_evidence_not_authorized"),
        ({"tool_names": ("shell",)}, "stage_tool_policy_mismatch"),
        ({"handoff_route": ("architecture", "development")}, "stage_handoff_policy_mismatch"),
    ],
)
def test_stage_authorization_fails_closed_outside_exact_bounds(
    change: dict[str, object], reason: str
) -> None:
    with pytest.raises(HostedPhase2Error, match=reason):
        authorize_stage(
            replace(plan(), **change),
            policy(),
            owner_decision=OWNER_DECISION,
            predecessor_receipt_digest="4" * 64,
            spent_microusd=0,
        )


def test_cost_is_integer_bound_and_total_budget_fails_closed() -> None:
    assert estimate_cost_microusd(input_tokens=24_000, output_tokens=1_200) == 6_240
    with pytest.raises(HostedPhase2Error, match="hosted_budget_exceeded"):
        authorize_stage(
            plan(),
            policy(),
            owner_decision=OWNER_DECISION,
            predecessor_receipt_digest="4" * 64,
            spent_microusd=95_000,
        )

    development = authorize_stage(
        plan("development_loop"),
        policy(),
        owner_decision=OWNER_DECISION,
        predecessor_receipt_digest="4" * 64,
        spent_microusd=0,
    )
    assert development.reserved_cost_microusd == 24_960


def test_observation_becomes_digest_only_public_receipt() -> None:
    receipt = evaluate_stage(observation(), plan(), policy(), spent_microusd=0)
    public = receipt.to_dict()
    serialized = str(public).lower()

    assert receipt.verdict == "PASS"
    assert receipt.actual_cost_microusd == 1_520
    assert receipt.output_digest
    assert "summary" not in public
    assert "affected_paths" not in public
    assert "add an explicit" not in serialized
    assert "prompt" not in public
    assert "output" not in public
    assert "api_key" not in serialized
    assert "trace_id" not in public
    with pytest.raises(HostedPhase2Error, match="receipt_verdict_invalid"):
        replace(receipt, verdict="FAIL")
    with pytest.raises(HostedPhase2Error, match="receipt_tool_count_invalid"):
        replace(receipt, tool_call_count=1)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"output": {"summary": "missing fields"}}, "output_schema_invalid"),
        ({"output": {"summary": "bad path", "affected_paths": ["../private.py"], "risks": ["scope"], "validation": ["tests"]}}, "affected_paths_outside_public_scope"),
        ({"output": {"summary": "no risk", "affected_paths": ["src/public.py"], "risks": [], "validation": ["tests"]}}, "risks_required"),
        ({"output": {"summary": "sk-secret", "affected_paths": ["src/public.py"], "risks": ["scope"], "validation": ["tests"]}}, "sensitive_output_detected"),
        ({"tool_calls": ("lookup_public_source",)}, "unexpected_tool_call"),
        ({"handoff_count": 1}, "unexpected_handoff"),
        ({"last_agent": "test"}, "last_agent_mismatch"),
        ({"output_tokens": 1_201}, "output_tokens_exceed_plan"),
        ({"latency_ms": 90_001}, "timeout_exceeded"),
    ],
)
def test_observation_rejects_quality_authority_and_leakage_failures(
    changes: dict[str, object], reason: str
) -> None:
    with pytest.raises(HostedPhase2Error, match=reason):
        evaluate_stage(observation(**changes), plan(), policy(), spent_microusd=0)


def test_local_source_lookup_is_exact_allowlist_read_only(tmp_path: Path) -> None:
    allowed = tmp_path / "src" / "allowed.py"
    denied = tmp_path / "src" / "denied.py"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("SAFE = True\n", encoding="utf-8")
    denied.write_text("SECRET = True\n", encoding="utf-8")
    lookup = LocalSourceLookup(tmp_path, allowed_paths=("src/allowed.py",), max_chars=100)

    assert lookup.lookup("src/allowed.py") == "SAFE = True\n"
    assert lookup.calls == ("src/allowed.py",)
    for path in ("src/denied.py", "../outside", str(allowed)):
        with pytest.raises(HostedPhase2Error, match="source_path_not_allowed"):
            lookup.lookup(path)


def test_local_source_lookup_is_immutable_content_bound_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "src" / "allowed.py"
    source.parent.mkdir(parents=True)
    source.write_text("PUBLIC = 1\n", encoding="utf-8")
    lookup = LocalSourceLookup(
        tmp_path,
        allowed_paths=("src/allowed.py",),
        max_chars=100,
    )
    original_capability = lookup.capability_digest

    source.write_text("PRIVATE = 2\n", encoding="utf-8")
    assert lookup.lookup("src/allowed.py") == "PUBLIC = 1\n"
    assert lookup.capability_digest == original_capability
    with pytest.raises(FrozenInstanceError):
        lookup._root = source  # type: ignore[misc]

    changed = LocalSourceLookup(
        tmp_path,
        allowed_paths=("src/allowed.py",),
        max_chars=100,
    )
    assert changed.capability_digest != original_capability


def role(role: str, input_digest: str, output_digit: str) -> RoleReceipt:
    return RoleReceipt(
        role=role,
        task_id="TASKSYS-1318",
        source_identity="1" * 64,
        context_digest="2" * 64,
        agent_graph_identity="3" * 64,
        model=MODEL_ID,
        authorization_digest="a" * 64,
        input_digest=input_digest,
        output_digest=output_digit * 64,
        verdict="PASS",
    )


def test_handoff_binds_architecture_and_test_receipts() -> None:
    architecture = role("architecture", "4" * 64, "5")
    test = role("test", architecture.output_digest, "6")
    receipt = derive_handoff_receipt(architecture, test)

    assert receipt.from_role == "architecture"
    assert receipt.to_role == "test"
    assert receipt.accepted is True
    assert len(receipt.receipt_digest) == 64
    with pytest.raises(HostedPhase2Error, match="handoff_input_mismatch"):
        derive_handoff_receipt(architecture, replace(test, input_digest="7" * 64))


def test_development_loop_requires_exact_four_role_topology() -> None:
    architecture = role("architecture", "4" * 64, "5")
    test = role("test", architecture.output_digest, "6")
    development = role("development", test.output_digest, "7")
    quality = role("quality", development.output_digest, "8")
    receipt = derive_development_loop_receipt(
        (architecture, test, development, quality)
    )

    assert isinstance(receipt, DevelopmentLoopReceipt)
    assert receipt.verdict == "PASS"
    assert receipt.roles == ("architecture", "test", "development", "quality")
    with pytest.raises(HostedPhase2Error, match="development_loop_topology_invalid"):
        derive_development_loop_receipt((architecture, development, quality))
    with pytest.raises(HostedPhase2Error, match="development_loop_lineage_invalid"):
        derive_development_loop_receipt(
            (architecture, test, replace(development, input_digest="9" * 64), quality)
        )


def test_run_authority_is_single_use_sequential_and_accounts_failed_reservation() -> None:
    authority = HostedRunAuthority(
        policy=policy(),
        run_identity="a" * 64,
        initial_predecessor_receipt_digest="4" * 64,
    )
    candidate = plan()
    lease = authority.authorize(candidate, prompt="review")
    authority.consume(candidate, lease, prompt="review")

    with pytest.raises(HostedPhase2Error, match="already_consumed"):
        authority.consume(candidate, lease, prompt="review")
    with pytest.raises(HostedPhase2Error, match="prompt_mismatch"):
        forged_authority = HostedRunAuthority(
            policy=policy(),
            run_identity="a" * 64,
            initial_predecessor_receipt_digest="4" * 64,
        )
        forged_lease = forged_authority.authorize(candidate, prompt="review")
        forged_authority.consume(candidate, forged_lease, prompt="different")

    charged = authority.block(lease)
    assert charged == lease.reserved_cost_microusd
    with pytest.raises(HostedPhase2Error, match="blocked"):
        authority.authorize(candidate, prompt="review")


def test_run_authority_settlement_requires_exact_evaluated_receipt() -> None:
    authority = HostedRunAuthority(
        policy=policy(),
        run_identity="a" * 64,
        initial_predecessor_receipt_digest="4" * 64,
    )
    candidate = plan()
    lease = authority.authorize(candidate, prompt="review")
    authority.consume(candidate, lease, prompt="review")
    receipt = evaluate_stage(observation(), candidate, policy(), spent_microusd=0)

    with pytest.raises(HostedPhase2Error, match="settlement_receipt_invalid"):
        authority.settle(lease, receipt="f" * 64)  # type: ignore[arg-type]
    with pytest.raises(HostedPhase2Error, match="settlement_receipt_identity_mismatch"):
        authority.settle(lease, receipt=replace(receipt, plan_digest="f" * 64))

    authority.settle(lease, receipt=receipt)
    assert authority.accounted_cost_microusd == receipt.actual_cost_microusd


def test_durable_run_claim_rejects_cross_process_style_duplicate(tmp_path: Path) -> None:
    first = DurableRunClaim(
        tmp_path,
        approval_scope_digest="c" * 64,
        run_identity="d" * 64,
    )
    duplicate = DurableRunClaim(
        tmp_path,
        approval_scope_digest="c" * 64,
        run_identity="d" * 64,
    )

    first.claim()
    assert first.claimed is True
    first.claim()
    with pytest.raises(HostedPhase2Error, match="already_consumed"):
        duplicate.claim()
    payload = next(tmp_path.iterdir()).read_text(encoding="utf-8").lower()
    assert "api_key" not in payload
    assert "/users/" not in payload


def test_production_prompt_manifest_rejects_caller_selected_packet() -> None:
    manifest = {
        "architecture": "approved architecture",
        "readonly_tool": "approved readonly",
        "handoff": "approved handoff",
        "development_loop": "e" * 64,
    }
    authority = HostedRunAuthority(
        policy=policy(),
        run_identity="a" * 64,
        initial_predecessor_receipt_digest="4" * 64,
        prompt_manifest=manifest,
    )

    assert authority.prompt_manifest_bound is True
    assert len(authority.prompt_manifest_digest) == 64
    with pytest.raises(HostedPhase2Error, match="prompt_manifest_mismatch"):
        authority.authorize(plan(), prompt="caller selected prompt")
