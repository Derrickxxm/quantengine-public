"""DEC-0019 red contracts for the local-model simulation boundary."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantengine_public.agent_platform.contracts import content_digest
from quantengine_public.agent_platform.hosted_phase2 import DurableRunClaim, LocalSourceLookup
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


def _result(
    output: str,
    *,
    requests: int = 1,
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> object:
    usage = SimpleNamespace(
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
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
    assert LocalSimulationConfig(
        base_url="http://[0:0:0:0:0:0:0:1]:21434/v1"
    ).endpoint_identity_digest == LocalSimulationConfig(
        base_url="http://[::1]:21434/v1"
    ).endpoint_identity_digest
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


def test_stage_rejects_rechained_handoff_identity_and_packet_tampering() -> None:
    from test_qwen_phase2_simulation import stages

    handoff_stage = stages()[2]
    original_handoff = handoff_stage.handoff_receipts[0]
    original_consumer = handoff_stage.role_receipts[0]
    forged_handoff = replace(
        original_handoff,
        consumer_agent_identity="9" * 64,
        packet_digest="8" * 64,
    )
    rechained_consumer = replace(
        original_consumer,
        predecessor_identity_receipt_digest=forged_handoff.receipt_digest,
    )

    with pytest.raises(
        LocalSimulationError,
        match="simulation_stage_handoff_binding_invalid",
    ):
        replace(
            handoff_stage,
            handoff_receipts=(forged_handoff,),
            role_receipts=(rechained_consumer,),
        )

    development_stage = stages()[3]
    identities = sorted(
        (*development_stage.role_receipts, *development_stage.handoff_receipts),
        key=lambda row: row.sequence,
    )
    forged_rows = []
    predecessor = identities[0].predecessor_identity_receipt_digest
    for row in identities:
        candidate = replace(row, predecessor_identity_receipt_digest=predecessor)
        if row.sequence == 3:
            candidate = replace(candidate, producer_agent_identity="9" * 64)
        forged_rows.append(candidate)
        predecessor = candidate.receipt_digest
    forged_roles = tuple(row for row in forged_rows if isinstance(row, SimulationRoleReceipt))
    forged_handoffs = tuple(
        row for row in forged_rows if isinstance(row, SimulationHandoffReceipt)
    )
    with pytest.raises(
        LocalSimulationError,
        match="simulation_stage_handoff_binding_invalid",
    ):
        replace(
            development_stage,
            role_receipts=forged_roles,
            handoff_receipts=forged_handoffs,
        )


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


@pytest.mark.parametrize(
    ("usage", "error"),
    [
        ({"requests": 3}, "simulation_usage_limit_exceeded"),
        ({"input_tokens": 100_001}, "simulation_usage_limit_exceeded"),
    ],
)
def test_request_and_input_usage_ceilings_block(
    usage: dict[str, int],
    error: str,
) -> None:
    executor = _executor()
    valid = ArchitectureOutput(
        summary="bounded",
        affected_paths=["README.md"],
        risks=["none"],
        validation=["test"],
    ).model_dump_json()

    async def runner(*args: object, **kwargs: object) -> object:
        return _result(valid, **usage)

    executor._runner = runner
    with pytest.raises(LocalSimulationError, match=error):
        asyncio.run(
            executor._run(
                SimpleNamespace(name="architecture"),
                "prompt",
                ArchitectureOutput,
                "architecture",
            )
        )
    asyncio.run(executor.close())


def test_repair_usage_is_accumulated_and_request_timeout_is_bounded() -> None:
    executor = _executor(request_timeout_seconds=0.01)
    valid = DevelopmentRoleOutput(
        summary="bounded",
        findings=["fact"],
        next_actions=["test"],
        verdict="PASS",
    ).model_dump_json()
    calls = 0

    async def repair_runner(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return _result("not-json" if calls == 1 else valid, output_tokens=30)

    executor._runner = repair_runner
    data = asyncio.run(
        executor._run(
            SimpleNamespace(name="architecture"),
            "prompt",
            DevelopmentRoleOutput,
            "development_architecture",
            repair_allowed=True,
        )
    )
    assert data.requests == 2
    assert data.output_tokens == 60
    assert data.repair_count == 1

    async def slow_runner(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(0.05)
        return _result(valid)

    executor._runner = slow_runner
    with pytest.raises(LocalSimulationError, match="simulation_timeout"):
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


def test_full_local_orchestration_spends_one_repair_and_never_claims_hosted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden_claim(self: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("hosted claim consumed")

    monkeypatch.setattr(DurableRunClaim, "claim", forbidden_claim)
    executor = _executor()
    root = Path(__file__).resolve().parents[1]
    source_path = "src/quantengine_public/agent_platform/hosted_canary.py"
    lookup = LocalSourceLookup(root, allowed_paths=(source_path,), max_chars=16_000)
    repair_flags: list[bool] = []

    async def discover() -> None:
        return None

    async def fake_run(
        agent: object,
        prompt: str,
        schema: object,
        label: str,
        *,
        repair_allowed: bool = False,
    ) -> object:
        if label == "readonly_tool":
            lookup.lookup(source_path)
        repair_count = int(label == "development_architecture")
        requests = 1 + repair_count
        if label.startswith("development_"):
            repair_flags.append(repair_allowed)
            role = label.removeprefix("development_")
            output = {
                "summary": "bounded",
                "findings": ["fact"],
                "next_actions": ["test"],
                "verdict": "PASS",
            }
            last_agent = role
        elif label == "handoff":
            output = {
                "summary": "bounded",
                "test_cases": ["negative"],
                "risks": ["none"],
                "verdict": "PASS",
            }
            last_agent = "test"
            requests = 2
        elif label == "readonly_tool":
            output = {
                "summary": "bounded",
                "source_facts": ["fact"],
                "risks": ["none"],
                "validation": ["test"],
            }
            last_agent = "architecture"
            requests = 2
        else:
            output = {
                "summary": "bounded",
                "affected_paths": ["README.md"],
                "risks": ["none"],
                "validation": ["test"],
            }
            last_agent = "architecture"
        return SimpleNamespace(
            output=output,
            requests=requests,
            input_tokens=100 * requests,
            output_tokens=20 * requests,
            latency_ms=1,
            last_agent=last_agent,
            repair_count=repair_count,
        )

    executor._discover_model = discover
    executor._run = fake_run
    receipt = asyncio.run(
        executor.execute(
            source_identity="a" * 64,
            architecture_prompt="architecture",
            readonly_prompt="readonly",
            handoff_prompt="handoff",
            development_prompt="development",
            lookup=lookup,
        )
    )

    assert repair_flags == [True, False, False, False]
    assert receipt["total"]["usage"]["requests"] == 10
    assert receipt["claims"]["durable_hosted_claim_consumed"] is False
    assert called is False
    asyncio.run(executor.close())


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
    supplied_top = receipt.pop("receipt_digest")

    assert receipt["owner_decision"] == "DEC-0019"
    assert len(receipt["provider"]["endpoint_identity_digest"]) == 64
    assert content_digest(receipt) == supplied_top
    expected_run = content_digest(
        {
            "source_identity": receipt["source_identity"],
            "owner_decision": "DEC-0019",
            "track": "qwen-local-simulation",
            "provider": receipt["provider"]["kind"],
            "model": receipt["provider"]["model"],
            "endpoint_identity_digest": receipt["provider"]["endpoint_identity_digest"],
        }
    )
    assert receipt["run_identity"] == expected_run
    stage_predecessor = content_digest(
        {
            "source_identity": receipt["source_identity"],
            "run_identity": expected_run,
            "owner_decision": "DEC-0019",
            "track": "qwen-local-simulation",
        }
    )
    for stage in receipt["stages"]:
        assert stage["predecessor_receipt_digest"] == stage_predecessor
        identities = sorted(
            (*stage["role_receipts"], *stage["handoff_receipts"]),
            key=lambda row: row["sequence"],
        )
        assert stage["identity_receipts"] == [row["receipt_digest"] for row in identities]
        identity_predecessor = content_digest(
            {
                "run_identity": expected_run,
                "stage": stage["stage"],
                "predecessor_receipt_digest": stage_predecessor,
                "kind": "identity-lineage",
            }
        )
        for identity in identities:
            assert identity["predecessor_identity_receipt_digest"] == identity_predecessor
            identity_body = dict(identity)
            identity_digest = identity_body.pop("receipt_digest")
            assert content_digest(identity_body) == identity_digest
            identity_predecessor = identity_digest
        stage_body = dict(stage)
        stage_digest = stage_body.pop("receipt_digest")
        assert content_digest(stage_body) == stage_digest
        stage_predecessor = stage_digest
    assert all(stage["identity_receipts"] for stage in receipt["stages"])
    assert len(receipt["stages"][2]["handoff_receipts"]) == 1
    assert len(receipt["stages"][3]["role_receipts"]) == 4
    assert len(receipt["stages"][3]["handoff_receipts"]) == 3
