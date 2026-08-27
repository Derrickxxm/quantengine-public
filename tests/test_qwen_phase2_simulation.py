"""Red contracts for the local OpenAI-compatible Phase 2 simulation."""

from __future__ import annotations

from dataclasses import replace
import asyncio
import json
import os
from pathlib import Path

import pytest

from quantengine_public.agent_platform.contracts import content_digest

from quantengine_public.agent_platform.qwen_phase2_simulation import (
    LOCAL_SIMULATION_MODEL,
    SIMULATION_STAGES,
    LocalSimulationConfig,
    LocalSimulationError,
    LocalModelSimulationExecutor,
    SimulationHandoffReceipt,
    SimulationRoleReceipt,
    SimulationStageReceipt,
    build_simulation_receipt,
)


def _identity_rows(
    name: str,
    predecessor: str,
    run_identity: str,
    endpoint_identity: str,
) -> tuple[tuple[SimulationRoleReceipt, ...], tuple[SimulationHandoffReceipt, ...]]:
    identity_predecessor = content_digest(
        {
            "run_identity": run_identity,
            "stage": name,
            "predecessor_receipt_digest": predecessor,
            "kind": "identity-lineage",
        }
    )
    roles: list[SimulationRoleReceipt] = []
    handoffs: list[SimulationHandoffReceipt] = []
    role_names = {
        "architecture": ("architecture",),
        "readonly_tool": ("architecture",),
        "handoff": ("test",),
        "development_loop": ("architecture", "test", "development", "quality"),
    }[name]
    sequence = 0
    prior_role: str | None = "architecture" if name == "handoff" else None
    prior_agent = "1" * 64 if name == "handoff" else None
    for role in role_names:
        agent_identity = str((sequence + 2) % 10) * 64
        if prior_role is not None:
            kind = "sdk" if name == "handoff" else "ordered"
            handoff = SimulationHandoffReceipt(
                run_identity=run_identity,
                endpoint_identity_digest=endpoint_identity,
                stage=name,
                handoff_kind=kind,
                sequence=sequence,
                from_role=prior_role,
                to_role=role,
                producer_agent_identity=prior_agent or "1" * 64,
                consumer_agent_identity=agent_identity,
                predecessor_identity_receipt_digest=identity_predecessor,
                packet_digest="3" * 64,
                accepted=True,
            )
            handoffs.append(handoff)
            identity_predecessor = handoff.receipt_digest
            sequence += 1
        role_receipt = SimulationRoleReceipt(
            run_identity=run_identity,
            endpoint_identity_digest=endpoint_identity,
            stage=name,
            role=role,
            sequence=sequence,
            agent_graph_identity=agent_identity,
            predecessor_identity_receipt_digest=identity_predecessor,
            input_digest=(handoffs[-1].packet_digest if handoffs else "4" * 64),
            output_digest="5" * 64,
            verdict="PASS",
        )
        roles.append(role_receipt)
        identity_predecessor = role_receipt.receipt_digest
        sequence += 1
        prior_role = role
        prior_agent = agent_identity
    return tuple(roles), tuple(handoffs)


def stage(
    name: str,
    predecessor: str,
    run_identity: str,
    endpoint_identity: str,
    input_tokens: int = 100,
) -> SimulationStageReceipt:
    role_receipts, handoff_receipts = _identity_rows(
        name,
        predecessor,
        run_identity,
        endpoint_identity,
    )
    if name in {"architecture", "readonly_tool"}:
        graph_identity = role_receipts[0].agent_graph_identity
        output_digest = role_receipts[0].output_digest
    elif name == "handoff":
        graph_identity = handoff_receipts[0].producer_agent_identity
        output_digest = role_receipts[0].output_digest
    else:
        graph_identity = content_digest(
            [row.agent_graph_identity for row in role_receipts]
        )
        output_digest = "a" * 64
    return SimulationStageReceipt(
        stage=name,
        status="PASS",
        plan_digest="c" * 64,
        predecessor_receipt_digest=predecessor,
        agent_graph_identity=graph_identity,
        output_digest=output_digest,
        run_identity=run_identity,
        endpoint_identity_digest=endpoint_identity,
        role_receipts=role_receipts,
        handoff_receipts=handoff_receipts,
        requests=1,
        input_tokens=input_tokens,
        output_tokens=20,
        latency_ms=25,
        tool_call_count=1 if name == "readonly_tool" else 0,
        handoff_count=1 if name == "handoff" else (3 if name == "development_loop" else 0),
        role_count=4 if name == "development_loop" else (2 if name == "handoff" else 1),
    )


def stages(
    source_identity: str = "b" * 64,
    endpoint_identity: str = "6" * 64,
    input_tokens: tuple[int, int, int, int] = (100, 100, 100, 100),
) -> tuple[SimulationStageReceipt, ...]:
    run_identity = content_digest(
        {
            "source_identity": source_identity,
            "owner_decision": "DEC-0019",
            "track": "qwen-local-simulation",
            "provider": "ollama-openai-compatible",
            "model": LOCAL_SIMULATION_MODEL,
            "endpoint_identity_digest": endpoint_identity,
        }
    )
    predecessor = content_digest(
        {
            "source_identity": source_identity,
            "run_identity": run_identity,
            "owner_decision": "DEC-0019",
            "track": "qwen-local-simulation",
        }
    )
    rows = []
    for name, stage_input_tokens in zip(SIMULATION_STAGES, input_tokens, strict=True):
        row = stage(
            name,
            predecessor,
            run_identity,
            endpoint_identity,
            input_tokens=stage_input_tokens,
        )
        rows.append(row)
        predecessor = row.receipt_digest
    return tuple(rows)


def test_config_is_exact_qwen_and_loopback_only() -> None:
    config = LocalSimulationConfig(base_url="http://127.0.0.1:21434/v1")

    assert config.model == LOCAL_SIMULATION_MODEL == "qwen3.8:27b-mxfp8"
    assert config.provider == "ollama-openai-compatible"
    assert config.owner_decision == "DEC-0019"
    for url in (
        "http://0.0.0.0:11434/v1",
        "https://127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/api",
        "http://user:secret@127.0.0.1:11434/v1",
    ):
        with pytest.raises(LocalSimulationError, match="simulation_base_url_invalid"):
            LocalSimulationConfig(base_url=url)


def test_executor_uses_concrete_qwen_model_without_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_getenv = os.getenv

    def guarded_getenv(name: str, *args: object) -> str | None:
        if name == "OPENAI_API_KEY":
            raise AssertionError("local simulation read the hosted API key")
        return real_getenv(name, *args)

    monkeypatch.setattr(os, "getenv", guarded_getenv)
    executor = LocalModelSimulationExecutor(
        LocalSimulationConfig(base_url="http://127.0.0.1:21434/v1")
    )
    assert type(executor._model).__name__ == "OpenAIChatCompletionsModel"
    assert executor._model.model == LOCAL_SIMULATION_MODEL
    asyncio.run(executor.close())


def test_public_receipt_cannot_claim_luna_hosting_cost_or_authority() -> None:
    receipt = build_simulation_receipt(
        source_identity="b" * 64,
        endpoint_identity_digest="6" * 64,
        stages=stages(),
    )
    serialized = str(receipt).lower()

    assert receipt["verdict"] == "PASS"
    assert receipt["provider"]["model"] == LOCAL_SIMULATION_MODEL
    assert receipt["provider"]["transport_scope"] == "loopback"
    assert receipt["claims"] == {
        "hosted_luna_proof": False,
        "actual_hosted_cost": False,
        "hosted_trace_enabled": False,
        "persistent_service_created": False,
        "durable_hosted_claim_consumed": False,
        "write_authority_granted": False,
        "release_authority_granted": False,
        "deployment_authority_granted": False,
        "quantengine_runtime_authority_granted": False,
    }
    assert "gpt-5.6-luna" not in serialized
    assert "api_key" not in serialized
    assert "prompt" not in serialized
    assert "base_url" not in serialized
    assert len(receipt["receipt_digest"]) == 64


def test_receipt_requires_exact_topology_and_stage_metrics() -> None:
    rows = stages()
    with pytest.raises(LocalSimulationError, match="simulation_stage_topology_invalid"):
        build_simulation_receipt(
            source_identity="b" * 64,
            endpoint_identity_digest="6" * 64,
            stages=rows[:-1],
        )
    with pytest.raises(LocalSimulationError, match="simulation_stage_topology_invalid"):
        build_simulation_receipt(
            source_identity="b" * 64,
            endpoint_identity_digest="6" * 64,
            stages=(rows[1], rows[0], rows[2], rows[3]),
        )
    with pytest.raises(LocalSimulationError, match="simulation_stage_identity_lineage_invalid"):
        build_simulation_receipt(
            source_identity="b" * 64,
            endpoint_identity_digest="6" * 64,
            stages=(rows[0], replace(rows[1], predecessor_receipt_digest="e" * 64), rows[2], rows[3]),
        )
    with pytest.raises(LocalSimulationError, match="simulation_stage_receipt_invalid"):
        replace(rows[0], requests=0)
    with pytest.raises(LocalSimulationError, match="simulation_stage_identity_topology_invalid"):
        replace(rows[1], tool_call_count=0)
    with pytest.raises(LocalSimulationError, match="simulation_stage_identity_topology_invalid"):
        replace(rows[2], handoff_count=0)
    with pytest.raises(LocalSimulationError, match="simulation_stage_identity_topology_invalid"):
        replace(rows[3], role_count=3)


def test_committed_simulation_receipt_rederives_without_hosted_claims() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/evidence/qwen_phase2_local_simulation_receipt_20260827.json"
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))
    supplied = receipt.pop("receipt_digest")

    assert content_digest(receipt) == supplied
    assert receipt["verdict"] == "PASS"
    assert tuple(row["stage"] for row in receipt["stages"]) == SIMULATION_STAGES
    assert receipt["claims"]["hosted_luna_proof"] is False
    assert receipt["claims"]["durable_hosted_claim_consumed"] is False
    assert receipt["claims"]["release_authority_granted"] is False
