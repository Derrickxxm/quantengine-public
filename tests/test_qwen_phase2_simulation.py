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
    SimulationStageReceipt,
    build_simulation_receipt,
)


def stage(name: str, predecessor: str) -> SimulationStageReceipt:
    return SimulationStageReceipt(
        stage=name,
        status="PASS",
        plan_digest="c" * 64,
        predecessor_receipt_digest=predecessor,
        agent_graph_identity="d" * 64,
        output_digest="a" * 64,
        requests=1,
        input_tokens=100,
        output_tokens=20,
        latency_ms=25,
        tool_call_count=1 if name == "readonly_tool" else 0,
        handoff_count=1 if name == "handoff" else (3 if name == "development_loop" else 0),
        role_count=4 if name == "development_loop" else (2 if name == "handoff" else 1),
    )


def stages(source_identity: str = "b" * 64) -> tuple[SimulationStageReceipt, ...]:
    predecessor = content_digest(
        {
            "source_identity": source_identity,
            "owner_decision": "DEC-0018",
            "track": "qwen-local-simulation",
        }
    )
    rows = []
    for name in SIMULATION_STAGES:
        row = stage(name, predecessor)
        rows.append(row)
        predecessor = row.receipt_digest
    return tuple(rows)


def test_config_is_exact_qwen_and_loopback_only() -> None:
    config = LocalSimulationConfig(base_url="http://127.0.0.1:21434/v1")

    assert config.model == LOCAL_SIMULATION_MODEL == "qwen3.8:27b-mxfp8"
    assert config.provider == "ollama-openai-compatible"
    assert config.owner_decision == "DEC-0018"
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
        build_simulation_receipt(source_identity="b" * 64, stages=rows[:-1])
    with pytest.raises(LocalSimulationError, match="simulation_stage_topology_invalid"):
        build_simulation_receipt(
            source_identity="b" * 64,
            stages=(rows[1], rows[0], rows[2], rows[3]),
        )
    with pytest.raises(LocalSimulationError, match="simulation_stage_lineage_invalid"):
        build_simulation_receipt(
            source_identity="b" * 64,
            stages=(rows[0], replace(rows[1], predecessor_receipt_digest="e" * 64), rows[2], rows[3]),
        )
    with pytest.raises(LocalSimulationError, match="simulation_stage_receipt_invalid"):
        replace(rows[0], requests=0)
    with pytest.raises(LocalSimulationError, match="simulation_stage_receipt_invalid"):
        replace(rows[1], tool_call_count=0)
    with pytest.raises(LocalSimulationError, match="simulation_stage_receipt_invalid"):
        replace(rows[2], handoff_count=0)
    with pytest.raises(LocalSimulationError, match="simulation_stage_receipt_invalid"):
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
