"""Studio-local Qwen simulation contracts for Native-Agent Phase 2.

This module is deliberately separate from the hosted ``gpt-5.6-luna`` path.
It never constructs or consumes :class:`DurableRunClaim` and its receipt cannot
be admitted as hosted Luna, cost, Release, deployment, or QuantEngine runtime
evidence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from collections.abc import Callable, Mapping
from typing import Any, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from .contracts import canonical_json, content_digest
from .hosted_phase2 import LocalSourceLookup
from .hosted_phase2_executor import (
    ArchitectureOutput,
    DevelopmentRoleOutput,
    HandoffTestOutput,
    ReadonlyToolOutput,
)
from .runtime import AgentsSdkRuntime


QWEN_SIMULATION_MODEL = "qwen3.8:27b-mxfp8"
QWEN_SIMULATION_PROVIDER = "ollama-openai-compatible"
QWEN_SIMULATION_DECISION = "DEC-0018"
SIMULATION_STAGES = (
    "architecture",
    "readonly_tool",
    "handoff",
    "development_loop",
)


class QwenSimulationError(ValueError):
    """Raised when local-simulation identity or evidence is invalid."""


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class QwenSimulationConfig:
    """Exact loopback-only endpoint configuration; no credential is accepted."""

    base_url: str
    model: str = QWEN_SIMULATION_MODEL
    provider: str = QWEN_SIMULATION_PROVIDER
    owner_decision: str = QWEN_SIMULATION_DECISION
    timeout_seconds: int = 300
    max_turns: int = 4
    max_output_tokens: int = 1_600

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/v1"
            or parsed.port is None
        ):
            raise QwenSimulationError("simulation_base_url_invalid")
        if (
            self.model != QWEN_SIMULATION_MODEL
            or self.provider != QWEN_SIMULATION_PROVIDER
            or self.owner_decision != QWEN_SIMULATION_DECISION
        ):
            raise QwenSimulationError("simulation_identity_invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or not 1 <= self.timeout_seconds <= 300
            or isinstance(self.max_turns, bool)
            or not isinstance(self.max_turns, int)
            or not 1 <= self.max_turns <= 4
            or isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= 1_600
        ):
            raise QwenSimulationError("simulation_limits_invalid")


@dataclass(frozen=True, slots=True)
class SimulationStageReceipt:
    """Digest-only local stage evidence."""

    stage: str
    status: str
    plan_digest: str
    predecessor_receipt_digest: str
    agent_graph_identity: str
    output_digest: str
    requests: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_call_count: int
    handoff_count: int
    role_count: int

    def __post_init__(self) -> None:
        expected = {
            "architecture": (0, 0, 1),
            "readonly_tool": (1, 0, 1),
            "handoff": (0, 1, 2),
            "development_loop": (0, 3, 4),
        }
        metrics = (
            self.requests,
            self.input_tokens,
            self.output_tokens,
            self.latency_ms,
            self.tool_call_count,
            self.handoff_count,
            self.role_count,
        )
        if (
            self.stage not in expected
            or self.status != "PASS"
            or not _is_digest(self.plan_digest)
            or not _is_digest(self.predecessor_receipt_digest)
            or not _is_digest(self.agent_graph_identity)
            or not _is_digest(self.output_digest)
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in metrics)
            or self.requests <= 0
            or self.input_tokens <= 0
            or self.output_tokens <= 0
            or (self.tool_call_count, self.handoff_count, self.role_count) != expected[self.stage]
        ):
            raise QwenSimulationError("simulation_stage_receipt_invalid")

    @property
    def receipt_digest(self) -> str:
        return content_digest(self.to_dict(include_receipt=False))

    def to_dict(self, *, include_receipt: bool = True) -> dict[str, Any]:
        body = {
            "stage": self.stage,
            "status": self.status,
            "plan_digest": self.plan_digest,
            "predecessor_receipt_digest": self.predecessor_receipt_digest,
            "agent_graph_identity": self.agent_graph_identity,
            "output_digest": self.output_digest,
            "usage": {
                "requests": self.requests,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            },
            "latency_ms": self.latency_ms,
            "tool_call_count": self.tool_call_count,
            "handoff_count": self.handoff_count,
            "role_count": self.role_count,
        }
        if include_receipt:
            body["receipt_digest"] = self.receipt_digest
        return body


def build_simulation_receipt(
    *,
    source_identity: str,
    stages: Sequence[SimulationStageReceipt],
) -> dict[str, Any]:
    """Build a strict public-safe receipt that denies hosted authority."""

    rows = tuple(stages)
    if (
        not _is_digest(source_identity)
        or tuple(row.stage for row in rows) != SIMULATION_STAGES
        or any(type(row) is not SimulationStageReceipt for row in rows)
    ):
        raise QwenSimulationError("simulation_stage_topology_invalid")
    predecessor = content_digest(
        {
            "source_identity": source_identity,
            "owner_decision": QWEN_SIMULATION_DECISION,
            "track": "qwen-local-simulation",
        }
    )
    for row in rows:
        if row.predecessor_receipt_digest != predecessor:
            raise QwenSimulationError("simulation_stage_lineage_invalid")
        predecessor = row.receipt_digest
    body: dict[str, Any] = {
        "schema_version": "quantengine_public.qwen_phase2_simulation.receipt.v1",
        "execution_mode": "local_simulation",
        "owner_decision": QWEN_SIMULATION_DECISION,
        "source_identity": source_identity,
        "provider": {
            "kind": QWEN_SIMULATION_PROVIDER,
            "model": QWEN_SIMULATION_MODEL,
            "transport_scope": "loopback",
        },
        "verdict": "PASS",
        "stages": [row.to_dict() for row in rows],
        "total": {
            "usage": {
                name: sum(getattr(row, name) for row in rows)
                for name in ("requests", "input_tokens", "output_tokens")
            },
            "latency_ms": sum(row.latency_ms for row in rows),
            "accounted_cost_microusd": 0,
        },
        "claims": {
            "hosted_luna_proof": False,
            "actual_hosted_cost": False,
            "hosted_trace_enabled": False,
            "persistent_service_created": False,
            "durable_hosted_claim_consumed": False,
            "write_authority_granted": False,
            "release_authority_granted": False,
            "deployment_authority_granted": False,
            "quantengine_runtime_authority_granted": False,
        },
    }
    body["receipt_digest"] = content_digest(body)
    return body


@dataclass(frozen=True, slots=True)
class _RunData:
    output: dict[str, Any]
    requests: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    last_agent: str


class QwenLocalSimulationExecutor:
    """One in-memory Agents SDK run against a loopback Ollama endpoint."""

    def __init__(
        self,
        config: QwenSimulationConfig,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(config) is not QwenSimulationConfig:
            raise QwenSimulationError("simulation_config_invalid")
        from agents import OpenAIChatCompletionsModel, Runner
        from openai import AsyncOpenAI, DefaultAsyncHttpx2Client

        self._config = config
        self._monotonic = monotonic
        self._runtime = AgentsSdkRuntime()
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key="ollama-local-simulation",
            max_retries=0,
            http_client=DefaultAsyncHttpx2Client(
                trust_env=False,
                follow_redirects=False,
            ),
        )
        self._model = OpenAIChatCompletionsModel(
            model=config.model,
            openai_client=self._client,
            strict_feature_validation=True,
            buffer_streamed_tool_calls=True,
        )
        self._runner = Runner.run

    async def close(self) -> None:
        await self._client.close()

    async def execute(
        self,
        *,
        source_identity: str,
        architecture_prompt: str,
        readonly_prompt: str,
        handoff_prompt: str,
        development_prompt: str,
        lookup: LocalSourceLookup,
    ) -> dict[str, Any]:
        if not _is_digest(source_identity):
            raise QwenSimulationError("simulation_source_identity_invalid")
        if type(lookup) is not LocalSourceLookup:
            raise QwenSimulationError("simulation_lookup_invalid")
        models = await self._client.models.list()
        if self._config.model not in {item.id for item in models.data}:
            raise QwenSimulationError("simulation_model_not_served")
        prompts = (architecture_prompt, readonly_prompt, handoff_prompt, development_prompt)
        if any(not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 24_000 for prompt in prompts):
            raise QwenSimulationError("simulation_prompt_invalid")

        predecessor = content_digest(
            {
                "source_identity": source_identity,
                "owner_decision": QWEN_SIMULATION_DECISION,
                "track": "qwen-local-simulation",
            }
        )
        receipts: list[SimulationStageReceipt] = []

        architecture = self._json_agent(
            "architecture",
            "Use only the supplied public packet. Return bounded architecture findings.",
            ArchitectureOutput,
        )
        data = await self._run(architecture, architecture_prompt, ArchitectureOutput, "architecture")
        receipt = self._stage_receipt(
            "architecture", source_identity, predecessor, architecture, data,
            tool_call_count=0, handoff_count=0, role_count=1,
        )
        receipts.append(receipt)
        predecessor = receipt.receipt_digest

        before_calls = len(lookup.calls)

        def lookup_public_source(path: str) -> str:
            """Return one exact allowlisted public source snapshot."""

            return lookup.lookup(path)

        tool = self._runtime.approved_function_tool(
            lookup_public_source,
            name="lookup_public_source",
        )
        readonly = self._json_agent(
            "architecture",
            "Call lookup_public_source exactly once for the requested path, then return source-grounded facts.",
            ReadonlyToolOutput,
            tools=(tool,),
        )
        data = await self._run(readonly, readonly_prompt, ReadonlyToolOutput, "readonly_tool")
        call_count = len(lookup.calls) - before_calls
        if call_count != 1:
            raise QwenSimulationError("simulation_readonly_tool_count_invalid")
        receipt = self._stage_receipt(
            "readonly_tool", source_identity, predecessor, readonly, data,
            tool_call_count=call_count, handoff_count=0, role_count=1,
            capability_digest=lookup.capability_digest,
        )
        receipts.append(receipt)
        predecessor = receipt.receipt_digest

        test_agent = self._json_agent(
            "test",
            "Return concrete negative tests for the supplied public Architecture packet.",
            HandoffTestOutput,
        )
        handoff = self._agent(
            "architecture",
            "Immediately hand off this bounded public request to the test specialist. Do not answer it yourself.",
            handoffs=(test_agent,),
        )
        data = await self._run(handoff, handoff_prompt, HandoffTestOutput, "handoff")
        if data.last_agent != "test":
            raise QwenSimulationError("simulation_handoff_identity_invalid")
        receipt = self._stage_receipt(
            "handoff", source_identity, predecessor, handoff, data,
            tool_call_count=0, handoff_count=1, role_count=2,
        )
        receipts.append(receipt)
        predecessor = receipt.receipt_digest

        role_outputs: list[dict[str, Any]] = []
        requests = input_tokens = output_tokens = latency_ms = 0
        role_agents = []
        prior_output: dict[str, Any] | None = None
        for role in ("architecture", "test", "development", "quality"):
            role_agent = self._json_agent(
                role,
                (
                    f"Act only as the {role} specialist. Return PASS only for evidence-backed, "
                    "bounded public-repository work. Grant no write, Release, deployment, or runtime authority."
                ),
                DevelopmentRoleOutput,
            )
            role_agents.append(role_agent)
            prompt = development_prompt
            if prior_output is not None:
                prompt += "\nUpstream public packet:\n" + canonical_json(prior_output)
            role_data = await self._run(
                role_agent,
                prompt,
                DevelopmentRoleOutput,
                f"development_{role}",
            )
            if role_data.last_agent != role or role_data.output.get("verdict") != "PASS":
                raise QwenSimulationError("simulation_development_role_invalid")
            role_outputs.append(role_data.output)
            prior_output = role_data.output
            requests += role_data.requests
            input_tokens += role_data.input_tokens
            output_tokens += role_data.output_tokens
            latency_ms += role_data.latency_ms
        development_data = _RunData(
            output={"roles": role_outputs},
            requests=requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            last_agent="quality",
        )
        graph_identity = content_digest(
            [self._runtime.agent_graph_identity(agent) for agent in role_agents]
        )
        receipts.append(
            self._stage_receipt(
                "development_loop", source_identity, predecessor, None, development_data,
                tool_call_count=0, handoff_count=3, role_count=4,
                graph_identity=graph_identity,
            )
        )
        return build_simulation_receipt(source_identity=source_identity, stages=tuple(receipts))

    def _agent(
        self,
        name: str,
        instructions: str,
        *,
        tools: tuple[Any, ...] = (),
        handoffs: tuple[Any, ...] = (),
    ) -> Any:
        from agents import ModelSettings
        from openai.types.shared import Reasoning

        agent = self._runtime.agent(
            name,
            instructions,
            model=self._model,
            tools=tools,
            handoffs=handoffs,
        )
        agent.model_settings = ModelSettings(
            max_tokens=self._config.max_output_tokens,
            timeout=float(self._config.timeout_seconds),
            temperature=0,
            reasoning=Reasoning(effort="none"),
            include_usage=True,
            extra_body={"response_format": {"type": "json_object"}},
        )
        return agent

    def _json_agent(
        self,
        name: str,
        instructions: str,
        schema: type[BaseModel],
        *,
        tools: tuple[Any, ...] = (),
    ) -> Any:
        fields = ", ".join(schema.model_fields)
        return self._agent(
            name,
            instructions
            + f" Return ONLY one valid JSON object with exactly these fields: {fields}. "
            "No markdown, prefix, or reasoning text. Keep summary under 240 characters; "
            "every declared list must contain 1 to 3 concise strings only.",
            tools=tools,
        )

    async def _run(
        self,
        agent: Any,
        prompt: str,
        schema: type[BaseModel],
        label: str,
    ) -> _RunData:
        from agents import RunConfig

        started = self._monotonic()
        run_config = RunConfig(
            tracing_disabled=True,
            trace_include_sensitive_data=False,
            workflow_name="quantengine-public-qwen-local-simulation",
        )
        try:
            result = await asyncio.wait_for(
                self._runner(
                    agent,
                    prompt,
                    max_turns=self._config.max_turns,
                    run_config=run_config,
                ),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise QwenSimulationError("simulation_timeout") from exc
        if not isinstance(result.final_output, str):
            raise QwenSimulationError(f"simulation_{label}_output_invalid")
        results = [result]
        try:
            output = schema.model_validate_json(result.final_output).model_dump(mode="json")
        except ValidationError as exc:
            if not label.startswith("development_"):
                raise QwenSimulationError(f"simulation_{label}_output_invalid") from exc
            repair_prompt = (
                prompt
                + "\nThe previous candidate failed the exact JSON schema. Return one corrected "
                "JSON object only, preserving only public facts from this candidate:\n"
                + result.final_output[:4_000]
            )
            try:
                repaired = await asyncio.wait_for(
                    self._runner(
                        agent,
                        repair_prompt,
                        max_turns=self._config.max_turns,
                        run_config=run_config,
                    ),
                    timeout=self._config.timeout_seconds,
                )
            except TimeoutError as retry_exc:
                raise QwenSimulationError("simulation_timeout") from retry_exc
            if not isinstance(repaired.final_output, str):
                raise QwenSimulationError(f"simulation_{label}_output_invalid") from exc
            try:
                output = schema.model_validate_json(repaired.final_output).model_dump(mode="json")
            except ValidationError as retry_exc:
                raise QwenSimulationError(f"simulation_{label}_output_invalid") from retry_exc
            result = repaired
            results.append(repaired)
        usages = [item.context_wrapper.usage for item in results]
        requests = sum(item.requests for item in usages)
        input_tokens = sum(item.input_tokens for item in usages)
        output_tokens = sum(item.output_tokens for item in usages)
        metrics = (requests, input_tokens, output_tokens)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in metrics):
            raise QwenSimulationError("simulation_usage_invalid")
        elapsed_ms = max(0, int((self._monotonic() - started) * 1_000))
        return _RunData(
            output=output,
            requests=requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            last_agent=str(getattr(result.last_agent, "name", "")),
        )

    def _stage_receipt(
        self,
        stage: str,
        source_identity: str,
        predecessor: str,
        agent: Any | None,
        data: _RunData,
        *,
        tool_call_count: int,
        handoff_count: int,
        role_count: int,
        capability_digest: str | None = None,
        graph_identity: str | None = None,
    ) -> SimulationStageReceipt:
        if graph_identity is None:
            graph_identity = self._runtime.agent_graph_identity(agent)
        plan_digest = content_digest(
            {
                "owner_decision": QWEN_SIMULATION_DECISION,
                "track": "qwen-local-simulation",
                "provider": self._config.provider,
                "model": self._config.model,
                "stage": stage,
                "source_identity": source_identity,
                "predecessor_receipt_digest": predecessor,
                "agent_graph_identity": graph_identity,
                "capability_digest": capability_digest,
                "limits": {
                    "timeout_seconds": self._config.timeout_seconds,
                    "max_turns": self._config.max_turns,
                    "max_output_tokens": self._config.max_output_tokens,
                },
            }
        )
        return SimulationStageReceipt(
            stage=stage,
            status="PASS",
            plan_digest=plan_digest,
            predecessor_receipt_digest=predecessor,
            agent_graph_identity=graph_identity,
            output_digest=content_digest(data.output),
            requests=data.requests,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            latency_ms=data.latency_ms,
            tool_call_count=tool_call_count,
            handoff_count=handoff_count,
            role_count=role_count,
        )
