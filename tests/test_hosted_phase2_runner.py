"""Contract tests for the bounded hosted Phase 2 command runner."""

from __future__ import annotations

import json
from typing import Any

import pytest

import scripts.run_hosted_phase2 as runner_module
from quantengine_public.agent_platform.hosted_phase2 import (
    HostedPhase2Error,
    HostedPhase2Policy,
    HostedRunAuthority,
    HostedStageObservation,
    HostedStagePlan,
    RoleReceipt,
    derive_handoff_receipt,
)
from scripts.run_hosted_phase2 import (
    MAX_TOTAL_BUDGET_MICROUSD,
    PHASE2_STAGES,
    _run_phase2_for_test,
    build_public_receipt,
    run_phase2,
)


def _observation(plan: HostedStagePlan) -> HostedStageObservation:
    if plan.stage == "architecture":
        output = {
            "summary": "bounded architecture review",
            "affected_paths": ["src/public.py"],
            "risks": ["scope"],
            "validation": ["tests"],
        }
        return HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output=output,
            requests=1,
            input_tokens=400,
            output_tokens=100,
            latency_ms=12,
            tool_calls=(),
            last_agent="architecture",
            handoff_count=0,
        )
    if plan.stage == "readonly_tool":
        output = {
            "summary": "bounded source lookup",
            "source_facts": ["public fact"],
            "risks": [],
            "validation": ["source digest"],
        }
        return HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output=output,
            requests=1,
            input_tokens=400,
            output_tokens=100,
            latency_ms=12,
            tool_calls=("lookup_public_source",),
            last_agent="architecture",
            handoff_count=0,
        )
    if plan.stage == "handoff":
        output = {
            "summary": "test specialist accepted the packet",
            "test_cases": ["bounded case"],
            "risks": [],
            "verdict": "PASS",
        }
        return HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output=output,
            requests=1,
            input_tokens=400,
            output_tokens=100,
            latency_ms=12,
            tool_calls=(),
            last_agent="test",
            handoff_count=1,
        )
    output = {
        "summary": "quality accepted the loop",
        "changed_paths": ["src/quantengine_public/agent_platform/hosted_canary.py"],
        "tests": ["bounded case"],
        "verdict": "PASS",
    }
    return HostedStageObservation(
        stage=plan.stage,
        plan_digest=plan.plan_digest,
        output=output,
        requests=4,
        input_tokens=1_600,
        output_tokens=400,
        latency_ms=48,
        tool_calls=(),
        last_agent="quality",
        handoff_count=3,
    )


class FakeExecutor:
    """No-network executor used to prove runner topology and receipt shaping."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}
        self.authority: HostedRunAuthority | None = None

    def bind_test_authority(self, authority: HostedRunAuthority) -> None:
        self.authority = authority

    def _consume(
        self, plan: HostedStagePlan, kwargs: dict[str, Any], prompt: str
    ) -> None:
        assert self.authority is not None
        self.authority.consume(plan, kwargs["authorization"], prompt=prompt)

    def preview_agent_graph_identity(self, plan: HostedStagePlan, **_: Any) -> str:
        return "a" * 64

    async def execute_architecture(
        self, plan: HostedStagePlan, **kwargs: Any
    ) -> HostedStageObservation:
        self.calls.append("architecture")
        self.prompts["architecture"] = kwargs["prompt"]
        self._consume(plan, kwargs, kwargs["prompt"])
        return _observation(plan)

    async def execute_readonly_tool(
        self, plan: HostedStagePlan, **kwargs: Any
    ) -> HostedStageObservation:
        self.calls.append("readonly_tool")
        self.prompts["readonly_tool"] = kwargs["prompt"]
        self._consume(plan, kwargs, kwargs["prompt"])
        return _observation(plan)

    async def execute_handoff(self, plan: HostedStagePlan, **kwargs: Any) -> Any:
        self.calls.append("handoff")
        self.prompts["handoff"] = kwargs["prompt"]
        self._consume(plan, kwargs, kwargs["prompt"])
        from quantengine_public.agent_platform.hosted_phase2_executor import (
            HandoffExecution,
        )

        authorization_digest = kwargs["authorization"].authorization_digest
        architecture = RoleReceipt(
            role="architecture",
            task_id=plan.task_id,
            source_identity=plan.source_identity,
            context_digest=plan.context_digest,
            agent_graph_identity=plan.agent_graph_identity,
            model=plan.model,
            authorization_digest=authorization_digest,
            input_digest=plan.predecessor_receipt_digest,
            output_digest="5" * 64,
            verdict="PASS",
        )
        test = RoleReceipt(
            role="test",
            task_id=plan.task_id,
            source_identity=plan.source_identity,
            context_digest=plan.context_digest,
            agent_graph_identity=plan.agent_graph_identity,
            model=plan.model,
            authorization_digest=authorization_digest,
            input_digest=architecture.output_digest,
            output_digest="6" * 64,
            verdict="PASS",
        )
        return HandoffExecution(
            _observation(plan),
            (architecture, test),
            derive_handoff_receipt(architecture, test),
        )

    async def execute_development_loop(
        self, plan: HostedStagePlan, **kwargs: Any
    ) -> Any:
        self.calls.append("development_loop")
        from quantengine_public.agent_platform.contracts import canonical_json
        from quantengine_public.agent_platform.hosted_phase2_executor import (
            DevelopmentExecution,
        )

        self.prompts["development_loop"] = canonical_json(dict(kwargs["prompts"]))
        self._consume(
            plan,
            kwargs,
            runner_module.content_digest({"prompts": dict(kwargs["prompts"])}),
        )

        digests = ("5" * 64, "6" * 64, "7" * 64, "8" * 64)
        input_digests = (plan.predecessor_receipt_digest, *digests[:-1])
        receipts = tuple(
            RoleReceipt(
                role=role,
                task_id=plan.task_id,
                source_identity=plan.source_identity,
                context_digest=plan.context_digest,
                agent_graph_identity=plan.agent_graph_identity,
                model=plan.model,
                authorization_digest=kwargs["authorization"].authorization_digest,
                input_digest=input_digest,
                output_digest=output_digest,
                verdict="PASS",
            )
            for role, input_digest, output_digest in zip(
                plan.handoff_route, input_digests, digests
            )
        )
        return DevelopmentExecution(_observation(plan), receipts)


def test_default_run_is_dry_run_and_never_reads_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_key_read(*_: Any, **__: Any) -> str:
        raise AssertionError("OPENAI_API_KEY must not be read by dry-run")

    monkeypatch.setattr("os.getenv", forbidden_key_read)
    receipt = _run_phase2_for_test(execute=False, executor=FakeExecutor())

    assert receipt["execution_mode"] == "dry_run"
    assert receipt["verdict"] == "PLANNED"
    assert [row["stage"] for row in receipt["stages"]] == list(PHASE2_STAGES)
    assert all(
        row["usage"] == {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        for row in receipt["stages"]
    )
    assert all(
        row["authority_flags"]
        == {
            "authorized": False,
            "execution_allowed": False,
            "tool_authority_granted": False,
            "handoff_authority_granted": False,
            "write_authority_granted": False,
            "release_authority_granted": False,
            "hosted_trace_enabled": False,
        }
        for row in receipt["stages"]
    )


def test_execute_runs_all_gated_stages_and_emits_only_public_safe_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = FakeExecutor()
    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-clean", False)
    )
    receipt = _run_phase2_for_test(execute=True, executor=executor)
    encoded = json.dumps(receipt, sort_keys=True).lower()

    assert executor.calls == list(PHASE2_STAGES)
    assert receipt["execution_mode"] == "execute"
    assert receipt["verdict"] == "PASS"
    assert receipt["total"]["accounted_cost_microusd"] < MAX_TOTAL_BUDGET_MICROUSD
    assert receipt["authority_flags"]["release_authority_granted"] is False
    assert receipt["authority_flags"]["write_authority_granted"] is False
    assert receipt["authority_flags"]["hosted_trace_enabled"] is False
    assert "bounded architecture review" not in encoded
    assert "prompt" not in receipt
    assert "output" not in receipt
    assert "api_key" not in encoded
    assert "trace_id" not in encoded


def test_source_path_is_small_real_public_source() -> None:
    source = (
        runner_module.Path(runner_module.__file__).resolve().parents[1]
        / runner_module.SOURCE_PATH
    )

    assert runner_module.SOURCE_PATH.endswith("agent_platform/hosted_canary.py")
    assert source.is_file()
    assert source.stat().st_size < 24_000


def test_dry_run_source_identity_binds_head_file_digest_and_dirty_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-clean", False)
    )
    clean = _run_phase2_for_test(execute=False, executor=FakeExecutor())
    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-dirty", True)
    )
    dirty = _run_phase2_for_test(execute=False, executor=FakeExecutor())

    assert clean["stages"][0]["plan_digest"] != dirty["stages"][0]["plan_digest"]
    assert "/users/" not in json.dumps(dirty).lower()


def test_execute_rejects_dirty_worktree_before_any_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = FakeExecutor()
    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-dirty", True)
    )

    with pytest.raises(HostedPhase2Error, match="clean_worktree"):
        _run_phase2_for_test(execute=True, executor=executor)
    assert executor.calls == []


def test_architecture_prompt_contains_bounded_real_public_source_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-clean", False)
    )
    executor = FakeExecutor()
    _run_phase2_for_test(execute=True, executor=executor)
    prompt = executor.prompts["architecture"]

    assert runner_module.SOURCE_PATH in prompt
    assert "Fail-closed preflight" in prompt
    assert "PUBLIC SOURCE PACKET" in prompt
    assert len(prompt) <= 24_000
    assert "/Users/" not in prompt
    assert runner_module.SOURCE_PATH in executor.prompts["handoff"]
    assert runner_module.SOURCE_PATH in executor.prompts["development_loop"]


def test_execute_fake_loop_has_identity_bound_four_role_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = FakeExecutor()
    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-clean", False)
    )
    receipt = _run_phase2_for_test(execute=True, executor=executor)

    assert receipt["stages"][-1]["authority_flags"]["handoff_authority_granted"] is True


def test_development_loop_empty_role_receipts_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyLoopExecutor(FakeExecutor):
        async def execute_development_loop(
            self, plan: HostedStagePlan, **kwargs: Any
        ) -> Any:
            self.calls.append("development_loop")
            from quantengine_public.agent_platform.hosted_phase2_executor import (
                DevelopmentExecution,
            )

            self._consume(
                plan,
                kwargs,
                runner_module.content_digest({"prompts": dict(kwargs["prompts"])}),
            )
            return DevelopmentExecution(_observation(plan), ())

    monkeypatch.setattr(
        runner_module, "_git_snapshot", lambda _root: ("head-clean", False)
    )
    receipt = _run_phase2_for_test(execute=True, executor=EmptyLoopExecutor())
    assert receipt["verdict"] == "BLOCKED"
    assert receipt["stages"][-1]["status"] == "BLOCKED"
    assert receipt["stages"][-1]["accounted_cost_microusd"] > 0


def test_public_receipt_builder_rejects_budget_overrun() -> None:
    row = {
        "stage": "architecture",
        "status": "BLOCKED",
        "plan_digest": "1" * 64,
        "receipt_digest": "2" * 64,
        "output_digest": "0" * 64,
        "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0},
        "accounted_cost_microusd": MAX_TOTAL_BUDGET_MICROUSD + 1,
        "latency_ms": 0,
        "authority_flags": runner_module._authority_flags("architecture", execute=True),
    }
    with pytest.raises(ValueError, match="budget"):
        build_public_receipt(
            execution_mode="execute",
            stages=(row,),
            failure_digest="f" * 64,
        )


def test_runner_cannot_raise_the_owner_budget_cap() -> None:
    with pytest.raises(HostedPhase2Error, match="hosted_budget_cap_exceeded"):
        HostedPhase2Policy(total_budget_microusd=MAX_TOTAL_BUDGET_MICROUSD + 1)


def test_public_receipt_rejects_nested_secret_and_cannot_override_total() -> None:
    planned = _run_phase2_for_test(execute=False, executor=FakeExecutor())["stages"][0]
    poisoned = dict(planned)
    poisoned["usage"] = {**planned["usage"], "prompt": "secret"}
    with pytest.raises(ValueError, match="usage_invalid"):
        build_public_receipt(execution_mode="dry_run", stages=(poisoned,))


def test_public_execute_entry_rejects_root_override() -> None:
    with pytest.raises(HostedPhase2Error, match="root_override_forbidden"):
        run_phase2(execute=True, root="/tmp/not-the-repository")
