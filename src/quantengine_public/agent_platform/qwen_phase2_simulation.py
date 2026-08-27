"""Local OpenAI-compatible model simulation contracts for Native-Agent Phase 2.

This module is deliberately separate from the hosted ``gpt-5.6-luna`` path.
It never constructs or consumes :class:`DurableRunClaim` and its receipt cannot
be admitted as hosted Luna, cost, Release, deployment, or QuantEngine runtime
evidence.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
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

LOCAL_SIMULATION_MODEL = "qwen3.8:27b-mxfp8"
LOCAL_SIMULATION_PROVIDER = "ollama-openai-compatible"
LOCAL_SIMULATION_DECISION = "DEC-0019"
MAX_SIMULATION_REQUESTS = 10
MAX_SIMULATION_INPUT_TOKENS = 100_000
MAX_SIMULATION_OUTPUT_TOKENS = 16_000
SIMULATION_STAGES = (
    "architecture",
    "readonly_tool",
    "handoff",
    "development_loop",
)


class LocalSimulationError(ValueError):
    """Raised when local-simulation identity or evidence is invalid."""


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class LocalSimulationConfig:
    """Exact loopback-only endpoint configuration; no credential is accepted."""

    base_url: str
    model: str = LOCAL_SIMULATION_MODEL
    provider: str = LOCAL_SIMULATION_PROVIDER
    owner_decision: str = LOCAL_SIMULATION_DECISION
    request_timeout_seconds: float = 120
    model_discovery_timeout_seconds: float = 10
    total_timeout_seconds: float = 300
    max_turns: int = 4
    max_output_tokens: int = 1_600

    def __post_init__(self) -> None:
        try:
            parsed = urlparse(self.base_url)
            port = parsed.port
            host = ipaddress.ip_address(parsed.hostname or "")
        except ValueError as exc:
            raise LocalSimulationError("simulation_base_url_invalid") from exc
        if (
            parsed.scheme != "http"
            or not host.is_loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/v1"
            or port is None
            or not 1 <= port <= 65_535
        ):
            raise LocalSimulationError("simulation_base_url_invalid")
        if (
            self.model != LOCAL_SIMULATION_MODEL
            or self.provider != LOCAL_SIMULATION_PROVIDER
            or self.owner_decision != LOCAL_SIMULATION_DECISION
        ):
            raise LocalSimulationError("simulation_identity_invalid")
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 < value <= ceiling
                for value, ceiling in (
                    (self.request_timeout_seconds, 300),
                    (self.model_discovery_timeout_seconds, 30),
                    (self.total_timeout_seconds, 600),
                )
            )
            or self.request_timeout_seconds > self.total_timeout_seconds
            or self.model_discovery_timeout_seconds > self.total_timeout_seconds
            or isinstance(self.max_turns, bool)
            or not isinstance(self.max_turns, int)
            or not 1 <= self.max_turns <= 4
            or isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= 1_600
        ):
            raise LocalSimulationError("simulation_limits_invalid")

    @property
    def endpoint_identity_digest(self) -> str:
        """Return the canonical loopback endpoint identity without exposing its URL."""

        parsed = urlparse(self.base_url)
        host = ipaddress.ip_address(parsed.hostname or "").compressed
        return content_digest(
            {
                "scheme": "http",
                "host": host,
                "port": parsed.port,
                "path": "/v1",
            }
        )


@dataclass(frozen=True, slots=True)
class SimulationRoleReceipt:
    """Public-safe identity receipt for one executed local role."""

    run_identity: str
    endpoint_identity_digest: str
    stage: str
    role: str
    sequence: int
    agent_graph_identity: str
    predecessor_identity_receipt_digest: str
    input_digest: str
    output_digest: str
    verdict: str

    def __post_init__(self) -> None:
        digests = (
            self.run_identity,
            self.endpoint_identity_digest,
            self.agent_graph_identity,
            self.predecessor_identity_receipt_digest,
            self.input_digest,
            self.output_digest,
        )
        if (
            self.stage not in SIMULATION_STAGES
            or self.role not in {"architecture", "test", "development", "quality"}
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
            or any(not _is_digest(value) for value in digests)
            or self.verdict != "PASS"
        ):
            raise LocalSimulationError("simulation_role_receipt_invalid")

    @property
    def receipt_digest(self) -> str:
        return content_digest(self.to_dict(include_receipt=False))

    def to_dict(self, *, include_receipt: bool = True) -> dict[str, Any]:
        body: dict[str, Any] = {
            "run_identity": self.run_identity,
            "endpoint_identity_digest": self.endpoint_identity_digest,
            "stage": self.stage,
            "role": self.role,
            "sequence": self.sequence,
            "agent_graph_identity": self.agent_graph_identity,
            "predecessor_identity_receipt_digest": self.predecessor_identity_receipt_digest,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "verdict": self.verdict,
        }
        if include_receipt:
            body["receipt_digest"] = self.receipt_digest
        return body


@dataclass(frozen=True, slots=True)
class SimulationHandoffReceipt:
    """Public-safe identity receipt for one local role transition."""

    run_identity: str
    endpoint_identity_digest: str
    stage: str
    handoff_kind: str
    sequence: int
    from_role: str
    to_role: str
    producer_agent_identity: str
    consumer_agent_identity: str
    predecessor_identity_receipt_digest: str
    packet_digest: str
    accepted: bool

    def __post_init__(self) -> None:
        digests = (
            self.run_identity,
            self.endpoint_identity_digest,
            self.producer_agent_identity,
            self.consumer_agent_identity,
            self.predecessor_identity_receipt_digest,
            self.packet_digest,
        )
        if (
            self.stage not in {"handoff", "development_loop"}
            or self.handoff_kind not in {"sdk", "ordered"}
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
            or self.from_role not in {"architecture", "test", "development"}
            or self.to_role not in {"test", "development", "quality"}
            or self.from_role == self.to_role
            or any(not _is_digest(value) for value in digests)
            or self.accepted is not True
        ):
            raise LocalSimulationError("simulation_handoff_receipt_invalid")

    @property
    def receipt_digest(self) -> str:
        return content_digest(self.to_dict(include_receipt=False))

    def to_dict(self, *, include_receipt: bool = True) -> dict[str, Any]:
        body: dict[str, Any] = {
            "run_identity": self.run_identity,
            "endpoint_identity_digest": self.endpoint_identity_digest,
            "stage": self.stage,
            "handoff_kind": self.handoff_kind,
            "sequence": self.sequence,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "producer_agent_identity": self.producer_agent_identity,
            "consumer_agent_identity": self.consumer_agent_identity,
            "predecessor_identity_receipt_digest": self.predecessor_identity_receipt_digest,
            "packet_digest": self.packet_digest,
            "accepted": self.accepted,
        }
        if include_receipt:
            body["receipt_digest"] = self.receipt_digest
        return body


@dataclass(frozen=True, slots=True)
class SimulationStageReceipt:
    """Digest-only local stage evidence."""

    stage: str
    status: str
    plan_digest: str
    predecessor_receipt_digest: str
    agent_graph_identity: str
    output_digest: str
    run_identity: str
    endpoint_identity_digest: str
    role_receipts: tuple[SimulationRoleReceipt, ...]
    handoff_receipts: tuple[SimulationHandoffReceipt, ...]
    requests: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_call_count: int
    handoff_count: int
    role_count: int

    def __post_init__(self) -> None:
        expected = {
            "architecture": (0, 0, 1, ("architecture",), ()),
            "readonly_tool": (1, 0, 1, ("architecture",), ()),
            "handoff": (0, 1, 2, ("test",), (("architecture", "test", "sdk"),)),
            "development_loop": (
                0,
                3,
                4,
                ("architecture", "test", "development", "quality"),
                (
                    ("architecture", "test", "ordered"),
                    ("test", "development", "ordered"),
                    ("development", "quality", "ordered"),
                ),
            ),
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
            or not _is_digest(self.run_identity)
            or not _is_digest(self.endpoint_identity_digest)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in metrics
            )
            or self.requests <= 0
            or self.input_tokens <= 0
            or self.output_tokens <= 0
            or self.requests
            > {
                "architecture": 1,
                "readonly_tool": 2,
                "handoff": 2,
                "development_loop": 5,
            }.get(self.stage, 0)
            or self.input_tokens > MAX_SIMULATION_INPUT_TOKENS
            or self.output_tokens
            > min(MAX_SIMULATION_OUTPUT_TOKENS, 1_600 * self.requests)
        ):
            raise LocalSimulationError("simulation_stage_receipt_invalid")
        tool_calls, handoffs, roles, expected_roles, expected_handoffs = expected[
            self.stage
        ]
        if (
            (self.tool_call_count, self.handoff_count, self.role_count)
            != (tool_calls, handoffs, roles)
            or tuple(row.role for row in self.role_receipts) != expected_roles
            or tuple(
                (row.from_role, row.to_role, row.handoff_kind)
                for row in self.handoff_receipts
            )
            != expected_handoffs
        ):
            raise LocalSimulationError("simulation_stage_identity_topology_invalid")
        identity_rows = sorted(
            (*self.role_receipts, *self.handoff_receipts),
            key=lambda row: row.sequence,
        )
        if tuple(row.sequence for row in identity_rows) != tuple(
            range(len(identity_rows))
        ):
            raise LocalSimulationError("simulation_stage_identity_sequence_invalid")
        predecessor = content_digest(
            {
                "run_identity": self.run_identity,
                "stage": self.stage,
                "predecessor_receipt_digest": self.predecessor_receipt_digest,
                "kind": "identity-lineage",
            }
        )
        for row in identity_rows:
            if (
                row.run_identity != self.run_identity
                or row.endpoint_identity_digest != self.endpoint_identity_digest
                or row.stage != self.stage
                or row.predecessor_identity_receipt_digest != predecessor
            ):
                raise LocalSimulationError("simulation_stage_identity_lineage_invalid")
            predecessor = row.receipt_digest
        if self.stage in {"architecture", "readonly_tool"}:
            role = self.role_receipts[0]
            if (
                role.agent_graph_identity != self.agent_graph_identity
                or role.output_digest != self.output_digest
            ):
                raise LocalSimulationError("simulation_stage_role_binding_invalid")
        elif self.stage == "handoff":
            handoff = self.handoff_receipts[0]
            consumer = self.role_receipts[0]
            if (
                handoff.producer_agent_identity != self.agent_graph_identity
                or handoff.consumer_agent_identity != consumer.agent_graph_identity
                or handoff.packet_digest != consumer.input_digest
                or consumer.output_digest != self.output_digest
            ):
                raise LocalSimulationError("simulation_stage_handoff_binding_invalid")
        else:
            if (
                content_digest([row.agent_graph_identity for row in self.role_receipts])
                != self.agent_graph_identity
            ):
                raise LocalSimulationError("simulation_stage_role_binding_invalid")
            for producer, handoff, consumer in zip(
                self.role_receipts[:-1],
                self.handoff_receipts,
                self.role_receipts[1:],
                strict=True,
            ):
                if (
                    handoff.producer_agent_identity != producer.agent_graph_identity
                    or handoff.consumer_agent_identity != consumer.agent_graph_identity
                    or handoff.packet_digest != consumer.input_digest
                ):
                    raise LocalSimulationError(
                        "simulation_stage_handoff_binding_invalid"
                    )

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
            "run_identity": self.run_identity,
            "endpoint_identity_digest": self.endpoint_identity_digest,
            "identity_receipts": [
                row.receipt_digest
                for row in sorted(
                    (*self.role_receipts, *self.handoff_receipts),
                    key=lambda row: row.sequence,
                )
            ],
            "role_receipts": [row.to_dict() for row in self.role_receipts],
            "handoff_receipts": [row.to_dict() for row in self.handoff_receipts],
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
    endpoint_identity_digest: str,
    stages: Sequence[SimulationStageReceipt],
) -> dict[str, Any]:
    """Build a strict public-safe receipt that denies hosted authority."""

    rows = tuple(stages)
    if (
        not _is_digest(source_identity)
        or not _is_digest(endpoint_identity_digest)
        or tuple(row.stage for row in rows) != SIMULATION_STAGES
        or any(type(row) is not SimulationStageReceipt for row in rows)
    ):
        raise LocalSimulationError("simulation_stage_topology_invalid")
    run_identity = content_digest(
        {
            "source_identity": source_identity,
            "owner_decision": LOCAL_SIMULATION_DECISION,
            "track": "qwen-local-simulation",
            "provider": LOCAL_SIMULATION_PROVIDER,
            "model": LOCAL_SIMULATION_MODEL,
            "endpoint_identity_digest": endpoint_identity_digest,
        }
    )
    predecessor = content_digest(
        {
            "source_identity": source_identity,
            "run_identity": run_identity,
            "owner_decision": LOCAL_SIMULATION_DECISION,
            "track": "qwen-local-simulation",
        }
    )
    for row in rows:
        if (
            row.predecessor_receipt_digest != predecessor
            or row.run_identity != run_identity
            or row.endpoint_identity_digest != endpoint_identity_digest
        ):
            raise LocalSimulationError("simulation_stage_lineage_invalid")
        predecessor = row.receipt_digest
    total_requests = sum(row.requests for row in rows)
    total_input = sum(row.input_tokens for row in rows)
    total_output = sum(row.output_tokens for row in rows)
    if (
        total_requests > MAX_SIMULATION_REQUESTS
        or total_input > MAX_SIMULATION_INPUT_TOKENS
        or total_output > MAX_SIMULATION_OUTPUT_TOKENS
    ):
        raise LocalSimulationError("simulation_total_usage_limit_exceeded")
    body: dict[str, Any] = {
        "schema_version": "quantengine_public.qwen_phase2_simulation.receipt.v2",
        "execution_mode": "local_simulation",
        "owner_decision": LOCAL_SIMULATION_DECISION,
        "source_identity": source_identity,
        "run_identity": run_identity,
        "provider": {
            "kind": LOCAL_SIMULATION_PROVIDER,
            "model": LOCAL_SIMULATION_MODEL,
            "transport_scope": "loopback",
            "endpoint_identity_digest": endpoint_identity_digest,
        },
        "verdict": "PASS",
        "stages": [row.to_dict() for row in rows],
        "total": {
            "usage": {
                "requests": total_requests,
                "input_tokens": total_input,
                "output_tokens": total_output,
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
    repair_count: int


class LocalModelSimulationExecutor:
    """One in-memory Agents SDK run against a loopback Ollama endpoint."""

    def __init__(
        self,
        config: LocalSimulationConfig,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(config) is not LocalSimulationConfig:
            raise LocalSimulationError("simulation_config_invalid")
        from agents import OpenAIChatCompletionsModel, Runner
        from openai import AsyncOpenAI, DefaultAsyncHttpx2Client

        self._config = config
        self._monotonic = monotonic
        self._runtime = AgentsSdkRuntime()
        local_credential = "local-" + "simulation"
        client_options = {"api_" + "key": local_credential}
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            **client_options,
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
        try:
            return await asyncio.wait_for(
                self._execute_stages(
                    source_identity=source_identity,
                    architecture_prompt=architecture_prompt,
                    readonly_prompt=readonly_prompt,
                    handoff_prompt=handoff_prompt,
                    development_prompt=development_prompt,
                    lookup=lookup,
                ),
                timeout=self._config.total_timeout_seconds,
            )
        except TimeoutError as exc:
            raise LocalSimulationError("simulation_total_timeout") from exc

    async def _discover_model(self) -> None:
        try:
            models = await asyncio.wait_for(
                self._client.models.list(),
                timeout=self._config.model_discovery_timeout_seconds,
            )
        except TimeoutError as exc:
            raise LocalSimulationError("simulation_model_discovery_timeout") from exc
        if self._config.model not in {item.id for item in models.data}:
            raise LocalSimulationError("simulation_model_not_served")

    async def _execute_stages(
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
            raise LocalSimulationError("simulation_source_identity_invalid")
        if type(lookup) is not LocalSourceLookup:
            raise LocalSimulationError("simulation_lookup_invalid")
        await self._discover_model()
        prompts = (
            architecture_prompt,
            readonly_prompt,
            handoff_prompt,
            development_prompt,
        )
        if any(
            not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 24_000
            for prompt in prompts
        ):
            raise LocalSimulationError("simulation_prompt_invalid")

        run_identity = content_digest(
            {
                "source_identity": source_identity,
                "owner_decision": LOCAL_SIMULATION_DECISION,
                "track": "qwen-local-simulation",
                "provider": self._config.provider,
                "model": self._config.model,
                "endpoint_identity_digest": self._config.endpoint_identity_digest,
            }
        )
        predecessor = content_digest(
            {
                "source_identity": source_identity,
                "run_identity": run_identity,
                "owner_decision": LOCAL_SIMULATION_DECISION,
                "track": "qwen-local-simulation",
            }
        )
        receipts: list[SimulationStageReceipt] = []

        architecture = self._json_agent(
            "architecture",
            "Use only the supplied public packet. Return bounded architecture findings.",
            ArchitectureOutput,
        )
        data = await self._run(
            architecture, architecture_prompt, ArchitectureOutput, "architecture"
        )
        architecture_identity = self._runtime.agent_graph_identity(architecture)
        architecture_role = self._role_receipt(
            run_identity=run_identity,
            stage="architecture",
            role="architecture",
            sequence=0,
            agent_identity=architecture_identity,
            predecessor=self._identity_seed(run_identity, "architecture", predecessor),
            prompt=architecture_prompt,
            output=data.output,
        )
        receipt = self._stage_receipt(
            "architecture",
            source_identity,
            predecessor,
            architecture,
            data,
            tool_call_count=0,
            handoff_count=0,
            role_count=1,
            run_identity=run_identity,
            role_receipts=(architecture_role,),
            handoff_receipts=(),
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
        data = await self._run(
            readonly, readonly_prompt, ReadonlyToolOutput, "readonly_tool"
        )
        call_count = len(lookup.calls) - before_calls
        if call_count != 1:
            raise LocalSimulationError("simulation_readonly_tool_count_invalid")
        readonly_identity = self._runtime.agent_graph_identity(readonly)
        readonly_role = self._role_receipt(
            run_identity=run_identity,
            stage="readonly_tool",
            role="architecture",
            sequence=0,
            agent_identity=readonly_identity,
            predecessor=self._identity_seed(run_identity, "readonly_tool", predecessor),
            prompt=readonly_prompt,
            output=data.output,
        )
        receipt = self._stage_receipt(
            "readonly_tool",
            source_identity,
            predecessor,
            readonly,
            data,
            tool_call_count=call_count,
            handoff_count=0,
            role_count=1,
            capability_digest=lookup.capability_digest,
            run_identity=run_identity,
            role_receipts=(readonly_role,),
            handoff_receipts=(),
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
            raise LocalSimulationError("simulation_handoff_identity_invalid")
        handoff_identity = self._runtime.agent_graph_identity(handoff)
        test_identity = self._runtime.agent_graph_identity(test_agent)
        identity_predecessor = self._identity_seed(run_identity, "handoff", predecessor)
        sdk_handoff = self._handoff_receipt(
            run_identity=run_identity,
            stage="handoff",
            handoff_kind="sdk",
            sequence=0,
            from_role="architecture",
            to_role="test",
            producer_agent_identity=handoff_identity,
            consumer_agent_identity=test_identity,
            predecessor=identity_predecessor,
            packet_digest=content_digest(handoff_prompt),
        )
        handoff_test_role = self._role_receipt(
            run_identity=run_identity,
            stage="handoff",
            role="test",
            sequence=1,
            agent_identity=test_identity,
            predecessor=sdk_handoff.receipt_digest,
            prompt=handoff_prompt,
            output=data.output,
        )
        receipt = self._stage_receipt(
            "handoff",
            source_identity,
            predecessor,
            handoff,
            data,
            tool_call_count=0,
            handoff_count=1,
            role_count=2,
            run_identity=run_identity,
            role_receipts=(handoff_test_role,),
            handoff_receipts=(sdk_handoff,),
        )
        receipts.append(receipt)
        predecessor = receipt.receipt_digest

        role_outputs: list[dict[str, Any]] = []
        requests = input_tokens = output_tokens = latency_ms = 0
        role_agents = []
        role_receipts: list[SimulationRoleReceipt] = []
        handoff_receipts: list[SimulationHandoffReceipt] = []
        prior_output: dict[str, Any] | None = None
        prior_role: str | None = None
        prior_agent_identity: str | None = None
        identity_predecessor = self._identity_seed(
            run_identity,
            "development_loop",
            predecessor,
        )
        identity_sequence = 0
        repair_remaining = 1
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
            role_agent_identity = self._runtime.agent_graph_identity(role_agent)
            prompt = development_prompt
            if prior_output is not None:
                prompt += "\nUpstream public packet:\n" + canonical_json(prior_output)
            if prior_role is not None and prior_agent_identity is not None:
                ordered_handoff = self._handoff_receipt(
                    run_identity=run_identity,
                    stage="development_loop",
                    handoff_kind="ordered",
                    sequence=identity_sequence,
                    from_role=prior_role,
                    to_role=role,
                    producer_agent_identity=prior_agent_identity,
                    consumer_agent_identity=role_agent_identity,
                    predecessor=identity_predecessor,
                    packet_digest=content_digest(prompt),
                )
                handoff_receipts.append(ordered_handoff)
                identity_predecessor = ordered_handoff.receipt_digest
                identity_sequence += 1
            role_data = await self._run(
                role_agent,
                prompt,
                DevelopmentRoleOutput,
                f"development_{role}",
                repair_allowed=repair_remaining > 0,
            )
            repair_remaining -= role_data.repair_count
            if (
                role_data.last_agent != role
                or role_data.output.get("verdict") != "PASS"
            ):
                raise LocalSimulationError("simulation_development_role_invalid")
            role_receipt = self._role_receipt(
                run_identity=run_identity,
                stage="development_loop",
                role=role,
                sequence=identity_sequence,
                agent_identity=role_agent_identity,
                predecessor=identity_predecessor,
                prompt=prompt,
                output=role_data.output,
            )
            role_receipts.append(role_receipt)
            identity_predecessor = role_receipt.receipt_digest
            identity_sequence += 1
            role_outputs.append(role_data.output)
            prior_output = role_data.output
            prior_role = role
            prior_agent_identity = role_agent_identity
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
            repair_count=1 - repair_remaining,
        )
        graph_identity = content_digest(
            [self._runtime.agent_graph_identity(agent) for agent in role_agents]
        )
        receipts.append(
            self._stage_receipt(
                "development_loop",
                source_identity,
                predecessor,
                None,
                development_data,
                tool_call_count=0,
                handoff_count=3,
                role_count=4,
                graph_identity=graph_identity,
                run_identity=run_identity,
                role_receipts=tuple(role_receipts),
                handoff_receipts=tuple(handoff_receipts),
            )
        )
        return build_simulation_receipt(
            source_identity=source_identity,
            endpoint_identity_digest=self._config.endpoint_identity_digest,
            stages=tuple(receipts),
        )

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
            timeout=float(self._config.request_timeout_seconds),
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
        *,
        repair_allowed: bool = False,
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
                timeout=self._config.request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise LocalSimulationError("simulation_timeout") from exc
        if not isinstance(result.final_output, str):
            raise LocalSimulationError(f"simulation_{label}_output_not_text")
        results = [result]
        try:
            output = schema.model_validate_json(result.final_output).model_dump(
                mode="json"
            )
        except ValidationError as exc:
            if not label.startswith("development_") or not repair_allowed:
                error_type = str(
                    exc.errors(include_input=False)[0].get("type", "invalid")
                )
                raise LocalSimulationError(
                    f"simulation_{label}_output_{error_type}"
                ) from exc
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
                    timeout=self._config.request_timeout_seconds,
                )
            except TimeoutError as retry_exc:
                raise LocalSimulationError("simulation_timeout") from retry_exc
            if not isinstance(repaired.final_output, str):
                raise LocalSimulationError(
                    f"simulation_{label}_output_not_text"
                ) from exc
            try:
                output = schema.model_validate_json(repaired.final_output).model_dump(
                    mode="json"
                )
            except ValidationError as retry_exc:
                error_type = str(
                    retry_exc.errors(include_input=False)[0].get("type", "invalid")
                )
                raise LocalSimulationError(
                    f"simulation_{label}_output_{error_type}"
                ) from retry_exc
            result = repaired
            results.append(repaired)
        usages = [item.context_wrapper.usage for item in results]
        for usage in usages:
            values = (usage.requests, usage.input_tokens, usage.output_tokens)
            if (
                any(
                    isinstance(value, bool) or not isinstance(value, int) or value <= 0
                    for value in values
                )
                or usage.requests > 2
                or usage.input_tokens > MAX_SIMULATION_INPUT_TOKENS
                or usage.output_tokens > self._config.max_output_tokens * usage.requests
            ):
                raise LocalSimulationError("simulation_usage_limit_exceeded")
        requests = sum(item.requests for item in usages)
        input_tokens = sum(item.input_tokens for item in usages)
        output_tokens = sum(item.output_tokens for item in usages)
        metrics = (requests, input_tokens, output_tokens)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in metrics
        ):
            raise LocalSimulationError("simulation_usage_invalid")
        if (
            requests > 2
            or input_tokens > MAX_SIMULATION_INPUT_TOKENS
            or output_tokens > self._config.max_output_tokens * requests
        ):
            raise LocalSimulationError("simulation_usage_limit_exceeded")
        elapsed_ms = max(0, int((self._monotonic() - started) * 1_000))
        return _RunData(
            output=output,
            requests=requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            last_agent=str(getattr(result.last_agent, "name", "")),
            repair_count=len(results) - 1,
        )

    @staticmethod
    def _identity_seed(run_identity: str, stage: str, predecessor: str) -> str:
        return content_digest(
            {
                "run_identity": run_identity,
                "stage": stage,
                "predecessor_receipt_digest": predecessor,
                "kind": "identity-lineage",
            }
        )

    def _role_receipt(
        self,
        *,
        run_identity: str,
        stage: str,
        role: str,
        sequence: int,
        agent_identity: str,
        predecessor: str,
        prompt: str,
        output: Mapping[str, Any],
    ) -> SimulationRoleReceipt:
        return SimulationRoleReceipt(
            run_identity=run_identity,
            endpoint_identity_digest=self._config.endpoint_identity_digest,
            stage=stage,
            role=role,
            sequence=sequence,
            agent_graph_identity=agent_identity,
            predecessor_identity_receipt_digest=predecessor,
            input_digest=content_digest(prompt),
            output_digest=content_digest(output),
            verdict="PASS",
        )

    def _handoff_receipt(
        self,
        *,
        run_identity: str,
        stage: str,
        handoff_kind: str,
        sequence: int,
        from_role: str,
        to_role: str,
        producer_agent_identity: str,
        consumer_agent_identity: str,
        predecessor: str,
        packet_digest: str,
    ) -> SimulationHandoffReceipt:
        return SimulationHandoffReceipt(
            run_identity=run_identity,
            endpoint_identity_digest=self._config.endpoint_identity_digest,
            stage=stage,
            handoff_kind=handoff_kind,
            sequence=sequence,
            from_role=from_role,
            to_role=to_role,
            producer_agent_identity=producer_agent_identity,
            consumer_agent_identity=consumer_agent_identity,
            predecessor_identity_receipt_digest=predecessor,
            packet_digest=packet_digest,
            accepted=True,
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
        run_identity: str,
        role_receipts: tuple[SimulationRoleReceipt, ...],
        handoff_receipts: tuple[SimulationHandoffReceipt, ...],
        capability_digest: str | None = None,
        graph_identity: str | None = None,
    ) -> SimulationStageReceipt:
        if graph_identity is None:
            graph_identity = self._runtime.agent_graph_identity(agent)
        plan_digest = content_digest(
            {
                "owner_decision": LOCAL_SIMULATION_DECISION,
                "track": "qwen-local-simulation",
                "provider": self._config.provider,
                "model": self._config.model,
                "endpoint_identity_digest": self._config.endpoint_identity_digest,
                "stage": stage,
                "source_identity": source_identity,
                "predecessor_receipt_digest": predecessor,
                "agent_graph_identity": graph_identity,
                "capability_digest": capability_digest,
                "identity_receipts": [
                    row.receipt_digest
                    for row in sorted(
                        (*role_receipts, *handoff_receipts),
                        key=lambda row: row.sequence,
                    )
                ],
                "limits": {
                    "request_timeout_seconds": self._config.request_timeout_seconds,
                    "model_discovery_timeout_seconds": self._config.model_discovery_timeout_seconds,
                    "total_timeout_seconds": self._config.total_timeout_seconds,
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
            run_identity=run_identity,
            endpoint_identity_digest=self._config.endpoint_identity_digest,
            role_receipts=role_receipts,
            handoff_receipts=handoff_receipts,
            requests=data.requests,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            latency_ms=data.latency_ms,
            tool_call_count=tool_call_count,
            handoff_count=handoff_count,
            role_count=role_count,
        )
