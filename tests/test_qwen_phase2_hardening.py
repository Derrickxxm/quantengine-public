"""DEC-0019 red contracts for the local-model simulation boundary."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantengine_public.agent_platform.contracts import content_digest
from quantengine_public.agent_platform.hosted_phase2 import DurableRunClaim
from quantengine_public.agent_platform.hosted_phase2_executor import (
    ArchitectureOutput,
    DevelopmentRoleOutput,
)
from quantengine_public.agent_platform import qwen_phase2_simulation as local_simulation
from quantengine_public.agent_platform.qwen_phase2_simulation import (
    LOCAL_SIMULATION_DECISION,
    LocalModelSimulationExecutor,
    LocalSimulationConfig,
    LocalSimulationError,
    SimulationHandoffReceipt,
    SimulationRoleReceipt,
)


def _result(output: str, *, input_tokens: int = 100, output_tokens: int = 20) -> object:
    usage = SimpleNamespace(requests=1, input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(
        final_output=output,
        context_wrapper=SimpleNamespace(usage=usage),
        last_agent=SimpleNamespace(name="architecture"),
    )


def _executor(**limits: object) -> LocalModelSimulationExecutor:
    return LocalModelSimulationExecutor(
        LocalSimulationConfig(
            base_url="http://127.0.0.1:21434/v1",
            **limits,
        )
    )


def test_decision_and_endpoint_identity_are_exact_and_public_safe() -> None:
    first = LocalSimulationConfig(base_url="http://127.0.0.1:21434/v1")
    same = LocalSimulationConfig(base_url="http://127.0.0.1:21434/v1/")
    other = LocalSimulationConfig(base_url="http://127.0.0.1:21435/v1")

    assert LOCAL_SIMULATION_DECISION == "DEC-0019"
    assert first.endpoint_identity_digest == same.endpoint_identity_digest
    assert first.endpoint_identity_digest != other.endpoint_identity_digest
    assert len(first.endpoint_identity_digest) == 64
    assert "127.0.0.1" not in first.endpoint_identity_digest
    for invalid in (
        "http://localhost:21434/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:not-a-port/v1",
    ):
        with pytest.raises(LocalSimulationError, match="simulation_base_url_invalid"):
            LocalSimulationConfig(base_url=invalid)


def test_role_and_handoff_receipts_are_digest_only_and_rederivable() -> None:
    run_identity = "a" * 64
    endpoint_identity = "b" * 64
    seed = "c" * 64
    role = SimulationRoleReceipt(
        run_identity=run_identity,
        endpoint_identity_digest=endpoint_identity,
        stage="development_loop",
        role="architecture",
        sequence=0,
        agent_graph_identity="d" * 64,
        predecessor_identity_receipt_digest=seed,
        input_digest="e" * 64,
        output_digest="f" * 64,
        verdict="PASS",
    )
    handoff = SimulationHandoffReceipt(
        run_identity=run_identity,
        endpoint_identity_digest=endpoint_identity,
        stage="development_loop",
        handoff_kind="ordered",
        sequence=1,
        from_role="architecture",
        to_role="test",
        producer_agent_identity="d" * 64,
        consumer_agent_identity="1" * 64,
        predecessor_identity_receipt_digest=role.receipt_digest,
        packet_digest=role.output_digest,
        accepted=True,
    )

    for receipt in (role, handoff):
        body = receipt.to_dict()
        supplied = body.pop("receipt_digest")
        assert content_digest(body) == supplied
        serialized = json.dumps(body, sort_keys=True).lower()
        for forbidden in ("prompt", "raw_output", "base_url", "api_key"):
            assert forbidden not in serialized


def test_non_development_schema_failure_is_never_retried() -> None:
    executor = _executor()
    calls = 0

    async def runner(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return _result("not-json")

    executor._runner = runner
    agent = SimpleNamespace(name="architecture")
    with pytest.raises(LocalSimulationError, match="simulation_architecture_output_"):
        asyncio.run(executor._run(agent, "prompt", ArchitectureOutput, "architecture"))
    assert calls == 1
    asyncio.run(executor.close())


def test_development_repair_budget_is_one_for_the_entire_stage() -> None:
    executor = _executor()
    valid = DevelopmentRoleOutput(
        summary="bounded",
        findings=["fact"],
        next_actions=["test"],
        verdict="PASS",
    ).model_dump_json()
    calls = 0

    async def runner(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return _result("not-json" if calls in {1, 3} else valid)

    executor._runner = runner
    agent = SimpleNamespace(name="architecture")
    first = asyncio.run(
        executor._run(
            agent,
            "prompt",
            DevelopmentRoleOutput,
            "development_architecture",
            repair_allowed=True,
        )
    )
    assert first.repair_count == 1
    with pytest.raises(LocalSimulationError, match="simulation_development_test_output_"):
        asyncio.run(
            executor._run(
                agent,
                "prompt",
                DevelopmentRoleOutput,
                "development_test",
                repair_allowed=False,
            )
        )
    assert calls == 3
    asyncio.run(executor.close())


def test_usage_above_configured_output_limit_blocks() -> None:
    executor = _executor(max_output_tokens=50)
    valid = ArchitectureOutput(
        summary="bounded",
        affected_paths=["README.md"],
        risks=["none"],
        validation=["test"],
    ).model_dump_json()

    async def runner(*args: object, **kwargs: object) -> object:
        return _result(valid, output_tokens=51)

    executor._runner = runner
    with pytest.raises(LocalSimulationError, match="simulation_usage_limit_exceeded"):
        asyncio.run(
            executor._run(
                SimpleNamespace(name="architecture"),
                "prompt",
                ArchitectureOutput,
                "architecture",
            )
        )
    asyncio.run(executor.close())


def test_model_discovery_and_whole_run_share_bounded_deadlines() -> None:
    executor = _executor(
        request_timeout_seconds=0.01,
        model_discovery_timeout_seconds=0.01,
        total_timeout_seconds=0.02,
    )

    class SlowModels:
        async def list(self) -> object:
            await asyncio.sleep(0.05)
            return SimpleNamespace(data=[])

    executor._client = SimpleNamespace(models=SlowModels(), close=lambda: None)
    with pytest.raises(LocalSimulationError, match="simulation_model_discovery_timeout"):
        asyncio.run(executor._discover_model())

    async def slow_stages(**kwargs: object) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {}

    executor._execute_stages = slow_stages
    with pytest.raises(LocalSimulationError, match="simulation_total_timeout"):
        asyncio.run(
            executor.execute(
                source_identity="a" * 64,
                architecture_prompt="a",
                readonly_prompt="b",
                handoff_prompt="c",
                development_prompt="d",
                lookup=object(),
            )
        )


def test_local_executor_has_no_hosted_claim_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_claim(self: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("hosted claim consumed")

    monkeypatch.setattr(DurableRunClaim, "claim", forbidden_claim)
    executor = _executor()
    assert "run_claim" not in inspect.signature(LocalModelSimulationExecutor.__init__).parameters
    assert not hasattr(local_simulation, "DurableRunClaim")
    assert ".claim(" not in inspect.getsource(LocalModelSimulationExecutor)
    assert called is False
    asyncio.run(executor.close())


def test_committed_receipt_retains_new_identity_contract() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/evidence/qwen_phase2_local_simulation_receipt_20260827.json"
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert receipt["owner_decision"] == "DEC-0019"
    assert len(receipt["provider"]["endpoint_identity_digest"]) == 64
    assert all(stage["identity_receipts"] for stage in receipt["stages"])
    assert len(receipt["stages"][2]["handoff_receipts"]) == 1
    assert len(receipt["stages"][3]["role_receipts"]) == 4
    assert len(receipt["stages"][3]["handoff_receipts"]) == 3
