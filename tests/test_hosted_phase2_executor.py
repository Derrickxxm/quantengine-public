"""Red contracts for the credential-isolated hosted Agents SDK executor."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quantengine_public.agent_platform.contracts import canonical_json, content_digest
from quantengine_public.agent_platform.hosted_phase2 import (
    MODEL_ID,
    DurableRunClaim,
    HostedPhase2Error,
    HostedPhase2Policy,
    HostedRunAuthority,
    HostedStageObservation,
    HostedStagePlan,
    LocalSourceLookup,
    derive_development_loop_receipt,
    derive_handoff_receipt,
    evaluate_stage,
)
from quantengine_public.agent_platform.hosted_phase2_executor import (
    ArchitectureOutput,
    DevelopmentRoleOutput,
    HandoffExecution,
    HandoffTestOutput,
    HostedAgentsExecutor,
    ReadonlyToolOutput,
)


def plan() -> HostedStagePlan:
    return HostedStagePlan(
        stage="architecture",
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
        tool_names=(),
        handoff_route=(),
    )


def bound_plan(executor: HostedAgentsExecutor) -> HostedStagePlan:
    candidate = plan()
    return replace(
        candidate,
        agent_graph_identity=executor.preview_agent_graph_identity(candidate),
    )


def authority() -> HostedRunAuthority:
    return HostedRunAuthority(
        policy=HostedPhase2Policy(),
        run_identity="a" * 64,
        initial_predecessor_receipt_digest="4" * 64,
    )


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, agent: Any, prompt: str, **kwargs: Any) -> Any:
        self.calls.append({"agent": agent, "prompt": prompt, **kwargs})
        usage = SimpleNamespace(requests=1, input_tokens=350, output_tokens=120)
        return SimpleNamespace(
            final_output=ArchitectureOutput(
                summary="Bound the hosted run.",
                affected_paths=[
                    "src/quantengine_public/agent_platform/hosted_phase2.py"
                ],
                risks=["budget drift"],
                validation=["deterministic receipt"],
            ),
            context_wrapper=SimpleNamespace(usage=usage),
            last_agent=agent,
            new_items=[],
        )


def test_executor_does_not_read_key_before_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_getenv = os.getenv

    def guarded_getenv(name: str, *args: object) -> str | None:
        if name == "OPENAI_API_KEY":
            raise AssertionError("key read too early")
        return real_getenv(name, *args)

    monkeypatch.setattr("os.getenv", guarded_getenv)
    run_authority = authority()
    executor = HostedAgentsExecutor.for_test(
        authority=run_authority, runner=FakeRunner()
    )
    candidate = bound_plan(executor)
    approved = run_authority.authorize(candidate, prompt="review")

    with pytest.raises(HostedPhase2Error, match="authorization_not_issued_by_run"):
        asyncio.run(
            executor.execute_architecture(
                candidate,
                authorization=replace(
                    approved,
                    plan_digest="5" * 64,
                ),
                prompt="review",
            )
        )


def test_executor_requires_key_only_at_authorized_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    run_authority = authority()
    executor = HostedAgentsExecutor.for_test(
        authority=run_authority, runner=FakeRunner()
    )
    candidate = bound_plan(executor)
    approved = run_authority.authorize(candidate, prompt="review")

    with pytest.raises(HostedPhase2Error, match="hosted_api_key_missing"):
        asyncio.run(
            executor.execute_architecture(
                candidate, authorization=approved, prompt="review"
            )
        )


def test_executor_binds_model_limits_disabled_trace_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "present-for-fake-runner")
    runner = FakeRunner()
    run_authority = authority()
    executor = HostedAgentsExecutor.for_test(
        authority=run_authority,
        runner=runner,
        monotonic=lambda: 10.0,
    )
    candidate = bound_plan(executor)
    approved = run_authority.authorize(candidate, prompt="review public source")

    observed = asyncio.run(
        executor.execute_architecture(
            candidate,
            authorization=approved,
            prompt="review public source",
        )
    )

    assert observed.stage == "architecture"
    assert observed.output["summary"] == "Bound the hosted run."
    assert observed.requests == 1
    assert observed.input_tokens == 350
    assert observed.output_tokens == 120
    assert observed.tool_calls == ()
    assert observed.handoff_count == 0
    assert runner.calls[0]["agent"].model == MODEL_ID
    assert runner.calls[0]["agent"].model_settings.max_tokens == 1_200
    assert runner.calls[0]["agent"].model_settings.store is False
    assert runner.calls[0]["max_turns"] == 2
    assert runner.calls[0]["run_config"].tracing_disabled is True
    assert runner.calls[0]["run_config"].trace_include_sensitive_data is False


def test_executor_rejects_prompt_and_wrong_stage_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "present-for-fake-runner")
    runner = FakeRunner()
    run_authority = authority()
    executor = HostedAgentsExecutor.for_test(authority=run_authority, runner=runner)
    candidate = bound_plan(executor)
    approved = run_authority.authorize(candidate, prompt="x" * 24_000)

    with pytest.raises(HostedPhase2Error, match="authorization_prompt_mismatch"):
        asyncio.run(
            executor.execute_architecture(
                candidate, authorization=approved, prompt="x" * 24_001
            )
        )
    second_authority = authority()
    second_executor = HostedAgentsExecutor.for_test(
        authority=second_authority, runner=runner
    )
    second_candidate = bound_plan(second_executor)
    second_approved = second_authority.authorize(second_candidate, prompt="review")
    with pytest.raises(HostedPhase2Error, match="architecture_stage_required"):
        asyncio.run(
            second_executor.execute_architecture(
                replace(
                    second_candidate,
                    stage="readonly_tool",
                    tool_names=("lookup_public_source",),
                ),
                authorization=second_approved,
                prompt="review",
            )
        )
    assert runner.calls == []


def test_forged_lease_and_expanded_plan_never_reach_key_or_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    run_authority = authority()
    executor = HostedAgentsExecutor.for_test(authority=run_authority, runner=runner)
    candidate = bound_plan(executor)
    approved = run_authority.authorize(candidate, prompt="review")

    real_getenv = os.getenv

    def forbidden_key_read(name: str, *args: Any, **kwargs: Any) -> str | None:
        if name == "OPENAI_API_KEY":
            raise AssertionError("forged authorization reached key boundary")
        return real_getenv(name, *args, **kwargs)

    monkeypatch.setattr("os.getenv", forbidden_key_read)
    forged = replace(approved, reserved_cost_microusd=0)
    expanded = replace(candidate, max_turns=100_000, max_output_tokens=1_000_000)
    with pytest.raises(HostedPhase2Error, match="authorization_not_issued_by_run"):
        asyncio.run(
            executor.execute_architecture(
                expanded,
                authorization=forged,
                prompt="review",
            )
        )
    assert runner.calls == []


def test_production_network_boundary_claims_once_after_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompt_manifest = {
        "architecture": "architecture",
        "readonly_tool": "readonly",
        "handoff": "handoff",
        "development_loop": "e" * 64,
    }
    run_authority = HostedRunAuthority(
        policy=HostedPhase2Policy(),
        run_identity="a" * 64,
        initial_predecessor_receipt_digest="4" * 64,
        prompt_manifest=prompt_manifest,
    )
    claim = DurableRunClaim(
        tmp_path,
        approval_scope_digest="c" * 64,
        run_identity="a" * 64,
    )
    executor = HostedAgentsExecutor._for_production(
        authority=run_authority,
        run_claim=claim,
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HostedPhase2Error, match="hosted_api_key_missing"):
        executor._authorize_network()
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setenv("OPENAI_API_KEY", "offline-boundary-test")
    executor._authorize_network()
    assert claim.claimed is True
    duplicate = DurableRunClaim(
        tmp_path,
        approval_scope_digest="c" * 64,
        run_identity="a" * 64,
    )
    other = HostedAgentsExecutor._for_production(
        authority=run_authority,
        run_claim=duplicate,
    )
    with pytest.raises(HostedPhase2Error, match="already_consumed"):
        other._authorize_network()


def test_production_executor_rejects_durable_claim_for_another_run(
    tmp_path: Path,
) -> None:
    run_authority = HostedRunAuthority(
        policy=HostedPhase2Policy(),
        run_identity="a" * 64,
        initial_predecessor_receipt_digest="4" * 64,
        prompt_manifest={
            "architecture": "architecture",
            "readonly_tool": "readonly",
            "handoff": "handoff",
            "development_loop": "development",
        },
    )
    forged_claim = DurableRunClaim(
        tmp_path,
        approval_scope_digest="c" * 64,
        run_identity="b" * 64,
    )

    with pytest.raises(HostedPhase2Error, match="durable_run_claim_identity_mismatch"):
        HostedAgentsExecutor._for_production(
            authority=run_authority,
            run_claim=forged_claim,
        )


def _stage_plan(
    executor: HostedAgentsExecutor,
    stage: str,
    predecessor: str,
    *,
    lookup: LocalSourceLookup | None = None,
) -> HostedStagePlan:
    tools = ("lookup_public_source",) if stage == "readonly_tool" else ()
    route: tuple[str, ...] = ()
    if stage == "handoff":
        route = ("architecture", "test")
    elif stage == "development_loop":
        route = ("architecture", "test", "development", "quality")
    candidate = HostedStagePlan(
        stage=stage,
        task_id="TASKSYS-1318",
        task_revision="p2-v1",
        source_identity="1" * 64,
        context_digest="2" * 64,
        agent_graph_identity="3" * 64,
        predecessor_receipt_digest=predecessor,
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
    if stage == "readonly_tool" and lookup is None:
        lookup = LocalSourceLookup(
            Path.cwd(),
            allowed_paths=("src/quantengine_public/agent_platform/hosted_canary.py",),
            max_chars=24_000,
        )
    return replace(
        candidate,
        agent_graph_identity=executor.preview_agent_graph_identity(
            candidate, lookup=lookup
        ),
    )


def _target_authorization(
    executor: HostedAgentsExecutor,
    target_stage: str,
    *,
    lookup: LocalSourceLookup | None = None,
    target_prompt: str | None = None,
) -> tuple[HostedRunAuthority, HostedStagePlan, Any, str]:
    """Advance a fresh run ledger through earlier stages without network calls."""

    ledger = executor._authority
    assert ledger is not None
    predecessor = "4" * 64
    order = ("architecture", "readonly_tool", "handoff", "development_loop")
    prompts: dict[str, str] = {
        "architecture": "architecture preflight",
        "readonly_tool": "readonly preflight",
        "handoff": "handoff preflight",
        "development_loop": canonical_json(
            {
                role: f"{role} preflight"
                for role in ("architecture", "test", "development", "quality")
            }
        ),
    }
    if target_prompt is not None:
        prompts[target_stage] = target_prompt
    for stage in order[: order.index(target_stage)]:
        prior = _stage_plan(executor, stage, predecessor, lookup=lookup)
        prior_auth = ledger.authorize(prior, prompt=prompts[stage])
        ledger.consume(prior, prior_auth, prompt=prompts[stage])
        output_by_stage = {
            "architecture": {
                "summary": "prior",
                "affected_paths": ["src/public.py"],
                "risks": ["scope"],
                "validation": ["contract"],
            },
            "readonly_tool": {
                "summary": "prior",
                "source_facts": ["fact"],
                "risks": [],
                "validation": ["source digest"],
            },
            "handoff": {
                "summary": "prior",
                "test_cases": ["case"],
                "risks": [],
                "verdict": "PASS",
            },
        }
        route = prior.handoff_route
        observation = HostedStageObservation(
            stage=stage,
            plan_digest=prior.plan_digest,
            output=output_by_stage[stage],
            requests=1,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            tool_calls=prior.tool_names,
            last_agent=route[-1] if route else "architecture",
            handoff_count=max(0, len(route) - 1),
        )
        prior_receipt = evaluate_stage(
            observation,
            prior,
            HostedPhase2Policy(),
            spent_microusd=ledger.accounted_cost_microusd,
        )
        ledger.settle(prior_auth, receipt=prior_receipt)
        predecessor = prior_receipt.receipt_digest
    target = _stage_plan(executor, target_stage, predecessor, lookup=lookup)
    target_auth = ledger.authorize(target, prompt=prompts[target_stage])
    return ledger, target, target_auth, prompts[target_stage]


class SdkGraphRunner:
    """Offline Runner seam that exercises real SDK Agent/FunctionTool graphs."""

    def __init__(
        self,
        *,
        source_path: str = "src/quantengine_public/agent_platform/hosted_canary.py",
    ) -> None:
        self.source_path = source_path
        self.calls: list[dict[str, Any]] = []
        self.tool_calls: list[str] = []

    async def __call__(self, agent: Any, prompt: str, **kwargs: Any) -> Any:
        self.calls.append({"agent": agent, "prompt": prompt, **kwargs})
        from agents import Agent, FunctionTool

        assert isinstance(agent, Agent)
        assert agent.model == MODEL_ID
        assert agent.model_settings.max_tokens == 1_200
        assert agent.model_settings.store is False
        assert kwargs["max_turns"] == 2
        assert kwargs["run_config"].tracing_disabled is True
        assert kwargs["run_config"].trace_include_sensitive_data is False

        last_agent = agent
        if agent.tools:
            assert len(agent.tools) == 1
            tool = agent.tools[0]
            assert isinstance(tool, FunctionTool)
            assert tool.name == "lookup_public_source"
            from agents.tool_context import ToolContext

            tool_context = ToolContext(
                context=None,
                tool_name=tool.name,
                tool_call_id="offline-tool-call",
                tool_arguments=json.dumps({"path": self.source_path}),
            )
            await tool.on_invoke_tool(
                tool_context, json.dumps({"path": self.source_path})
            )
            self.tool_calls.append(tool.name)
            output: Any = ReadonlyToolOutput(
                summary="source-grounded result",
                source_facts=["public source was read"],
                risks=[],
                validation=["exact allowlist"],
            )
        elif agent.handoffs:
            assert agent.name == "architecture"
            assert len(agent.handoffs) == 1
            assert isinstance(agent.handoffs[0], Agent)
            assert agent.handoffs[0].name == "test"
            last_agent = agent.handoffs[0]
            output = HandoffTestOutput(
                summary="test accepted handoff",
                test_cases=["bounded handoff"],
                risks=[],
                verdict="PASS",
            )
        elif agent.output_type is DevelopmentRoleOutput:
            output = DevelopmentRoleOutput(
                summary=f"{agent.name} accepted packet",
                findings=[],
                next_actions=[f"{agent.name} evidence"],
                verdict="PASS",
            )
        elif agent.name == "architecture":
            output = ArchitectureOutput(
                summary="bounded architecture",
                affected_paths=["public.py"],
                risks=[],
                validation=["contract"],
            )
        else:  # pragma: no cover - the graph tests above cover every allowed role
            raise AssertionError(f"unexpected SDK agent: {agent.name}")
        usage = SimpleNamespace(requests=1, input_tokens=500, output_tokens=100)
        return SimpleNamespace(
            final_output=output,
            context_wrapper=SimpleNamespace(usage=usage),
            last_agent=last_agent,
            new_items=[],
        )


def test_readonly_tool_uses_real_sdk_function_tool_once_and_preserves_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-only")
    source = (
        tmp_path / "src" / "quantengine_public" / "agent_platform" / "hosted_canary.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text("PUBLIC = True\n", encoding="utf-8")
    lookup = LocalSourceLookup(
        tmp_path,
        allowed_paths=("src/quantengine_public/agent_platform/hosted_canary.py",),
        max_chars=24_000,
    )
    runner = SdkGraphRunner()
    executor = HostedAgentsExecutor.for_test(authority=authority(), runner=runner)
    _ledger, target, approved, prompt = _target_authorization(
        executor, "readonly_tool", lookup=lookup
    )
    observed = asyncio.run(
        executor.execute_readonly_tool(
            target, authorization=approved, prompt=prompt, lookup=lookup
        )
    )

    assert target.agent_graph_identity == executor.preview_agent_graph_identity(
        target, lookup=lookup
    )
    assert lookup.calls == ("src/quantengine_public/agent_platform/hosted_canary.py",)
    assert runner.tool_calls == ["lookup_public_source"]
    assert observed.tool_calls == ("lookup_public_source",)
    assert len(runner.calls) == 1
    assert runner.calls[0]["run_config"].tracing_disabled is True
    assert runner.calls[0]["run_config"].trace_include_sensitive_data is False


def test_handoff_uses_real_sdk_handoff_graph_and_identity_bound_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-only")
    runner = SdkGraphRunner()
    executor = HostedAgentsExecutor.for_test(authority=authority(), runner=runner)
    _ledger, target, approved, prompt = _target_authorization(executor, "handoff")
    result = asyncio.run(
        executor.execute_handoff(target, authorization=approved, prompt=prompt)
    )

    assert isinstance(result, HandoffExecution)
    assert result.observation.last_agent == "test"
    assert result.observation.handoff_count == 1
    assert result.handoff_receipt.accepted is True
    assert result.role_receipts[0].role == "architecture"
    assert result.role_receipts[1].role == "test"
    assert result.role_receipts[1].input_digest == result.role_receipts[0].output_digest
    assert (
        result.handoff_receipt.receipt_digest
        == derive_handoff_receipt(*result.role_receipts).receipt_digest
    )
    assert target.agent_graph_identity == executor.preview_agent_graph_identity(target)
    assert runner.calls[0]["agent"].handoffs[0].name == "test"


def test_development_loop_uses_four_real_sdk_agents_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-only")
    runner = SdkGraphRunner()
    prompts = {
        role: f"{role} bounded packet"
        for role in ("architecture", "test", "development", "quality")
    }
    prompt_packet = content_digest({"prompts": prompts})
    executor = HostedAgentsExecutor.for_test(authority=authority(), runner=runner)
    _ledger, target, approved, _ = _target_authorization(
        executor, "development_loop", target_prompt=prompt_packet
    )
    result = asyncio.run(
        executor.execute_development_loop(
            target, authorization=approved, prompts=prompts
        )
    )

    assert target.agent_graph_identity == executor.preview_agent_graph_identity(target)
    assert [call["agent"].name for call in runner.calls] == list(target.handoff_route)
    assert len(result.role_receipts) == 4
    assert (
        tuple(receipt.role for receipt in result.role_receipts) == target.handoff_route
    )
    assert all(call["run_config"].tracing_disabled for call in runner.calls)
    assert all(
        not call["agent"].tools and not call["agent"].handoffs for call in runner.calls
    )
    assert all(
        current.input_digest == previous.output_digest
        for previous, current in zip(result.role_receipts, result.role_receipts[1:])
    )
    loop_receipt = derive_development_loop_receipt(result.role_receipts)
    assert loop_receipt.verdict == "PASS"
    assert result.observation.last_agent == "quality"
    assert result.observation.handoff_count == 3


def test_development_loop_rejects_runner_last_agent_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WrongLastAgentRunner(SdkGraphRunner):
        async def __call__(self, agent: Any, prompt: str, **kwargs: Any) -> Any:
            result = await super().__call__(agent, prompt, **kwargs)
            result.last_agent = SimpleNamespace(name="quality")
            return result

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-only")
    prompts = {
        role: f"{role} bounded packet"
        for role in ("architecture", "test", "development", "quality")
    }
    prompt_packet = content_digest({"prompts": prompts})
    runner = WrongLastAgentRunner()
    executor = HostedAgentsExecutor.for_test(authority=authority(), runner=runner)
    _, target, approved, _ = _target_authorization(
        executor,
        "development_loop",
        target_prompt=prompt_packet,
    )

    with pytest.raises(HostedPhase2Error, match="development_role_identity_mismatch"):
        asyncio.run(
            executor.execute_development_loop(
                target,
                authorization=approved,
                prompts=prompts,
            )
        )
