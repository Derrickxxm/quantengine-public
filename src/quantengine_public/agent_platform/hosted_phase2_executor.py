"""Credential-isolated OpenAI Agents SDK executor for hosted Phase 2.

Importing and constructing this module never reads an API key.  Credential
presence is checked only after an exact :class:`StageAuthorization` is bound to
the requested plan.  Raw model output remains in memory for deterministic
evaluation and must not be persisted directly.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from .contracts import canonical_json, content_digest
from .hosted_phase2 import (
    MODEL_ID,
    DurableRunClaim,
    HostedPhase2Error,
    HostedRunAuthority,
    HostedStageObservation,
    HostedStagePlan,
    LocalSourceLookup,
    Phase2HandoffReceipt,
    RoleReceipt,
    StageAuthorization,
    derive_handoff_receipt,
)
from .runtime import AgentsSdkRuntime


class ArchitectureOutput(BaseModel):
    summary: str
    affected_paths: list[str]
    risks: list[str]
    validation: list[str]


class ReadonlyToolOutput(BaseModel):
    summary: str
    source_facts: list[str]
    risks: list[str]
    validation: list[str]


class HandoffTestOutput(BaseModel):
    summary: str
    test_cases: list[str]
    risks: list[str]
    verdict: str


class DevelopmentRoleOutput(BaseModel):
    summary: str
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    verdict: str


@dataclass(frozen=True, slots=True)
class DevelopmentExecution:
    observation: HostedStageObservation
    role_receipts: tuple[RoleReceipt, ...]


@dataclass(frozen=True, slots=True)
class HandoffExecution:
    observation: HostedStageObservation
    role_receipts: tuple[RoleReceipt, RoleReceipt]
    handoff_receipt: Phase2HandoffReceipt


@dataclass(frozen=True, slots=True)
class _RunData:
    output: dict[str, Any]
    requests: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    last_agent: str


RunnerCallable = Callable[..., Awaitable[Any]]

_ARCHITECTURE_INSTRUCTIONS = (
    "Analyze only the supplied public source packet. Return the exact structured "
    "ArchitectureOutput. Do not request tools, handoffs, secrets, deployment, or "
    "runtime authority. State uncertainty instead of inventing source facts."
)
_READONLY_INSTRUCTIONS = (
    "Call lookup_public_source exactly once using the path named in the request. "
    "Use only that returned public text. Then return the exact structured "
    "ReadonlyToolOutput. Do not request any other tool or authority."
)
_HANDOFF_ARCHITECTURE_INSTRUCTIONS = (
    "Immediately hand off this bounded validation request to the test specialist. "
    "Do not answer it yourself and do not call any other tool."
)
_HANDOFF_TEST_INSTRUCTIONS = (
    "Independently convert the supplied public Architecture packet into the exact "
    "structured HandoffTestOutput. Grant no release or runtime authority."
)


class HostedAgentsExecutor:
    """Small hosted executor; deterministic policy remains in ``hosted_phase2``."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        from agents import Runner

        self._runner: RunnerCallable = Runner.run
        self._authority: HostedRunAuthority | None = None
        self._run_claim: DurableRunClaim | None = None
        self._test_mode = False
        self._monotonic = monotonic
        self._runtime = AgentsSdkRuntime()

    @classmethod
    def for_test(
        cls,
        *,
        authority: HostedRunAuthority,
        runner: RunnerCallable,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> HostedAgentsExecutor:
        """Construct the isolated unit-test seam; production never calls it."""

        if type(authority) is not HostedRunAuthority:
            raise HostedPhase2Error("run_authority_invalid")
        instance = cls(monotonic=monotonic)
        instance._authority = authority
        instance._runner = runner
        instance._test_mode = True
        return instance

    @classmethod
    def _for_production(
        cls,
        *,
        authority: HostedRunAuthority,
        run_claim: DurableRunClaim,
    ) -> HostedAgentsExecutor:
        if type(authority) is not HostedRunAuthority:
            raise HostedPhase2Error("run_authority_invalid")
        if not authority.prompt_manifest_bound:
            raise HostedPhase2Error("prompt_manifest_required")
        if type(run_claim) is not DurableRunClaim:
            raise HostedPhase2Error("durable_run_claim_invalid")
        if run_claim.run_identity != authority.run_identity:
            raise HostedPhase2Error("durable_run_claim_identity_mismatch")
        instance = cls()
        instance._authority = authority
        instance._run_claim = run_claim
        return instance

    def preview_agent_graph_identity(
        self,
        plan: HostedStagePlan,
        *,
        lookup: LocalSourceLookup | None = None,
    ) -> str:
        """Build the exact no-key Agent graph and return its deterministic identity."""

        if plan.stage == "architecture":
            return self._runtime.agent_graph_identity(self._architecture_agent(plan))
        if plan.stage == "readonly_tool":
            if lookup is None:
                raise HostedPhase2Error("readonly_lookup_required")
            if type(lookup) is not LocalSourceLookup:
                raise HostedPhase2Error("readonly_lookup_capability_invalid")
            return content_digest(
                {
                    "agent_graph_identity": self._runtime.agent_graph_identity(
                        self._readonly_agent(plan, lookup)
                    ),
                    "capability_digest": lookup.capability_digest,
                }
            )
        if plan.stage == "handoff":
            return self._runtime.agent_graph_identity(self._handoff_agent(plan))
        if plan.stage == "development_loop":
            identities = [
                self._runtime.agent_graph_identity(self._role_agent(role, plan))
                for role in plan.handoff_route
            ]
            return content_digest(identities)
        raise HostedPhase2Error("stage_not_authorized")

    async def execute_architecture(
        self,
        plan: HostedStagePlan,
        *,
        authorization: StageAuthorization,
        prompt: str,
    ) -> HostedStageObservation:
        if plan.stage != "architecture":
            raise HostedPhase2Error("architecture_stage_required")
        agent = self._architecture_agent(plan)
        self._verify_graph(plan, agent)
        self._consume_before_key(plan, authorization, prompt)
        self._authorize_network()
        data = await self._run(agent, prompt, plan)
        return HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output=data.output,
            requests=data.requests,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            latency_ms=data.latency_ms,
            tool_calls=(),
            last_agent=data.last_agent,
            handoff_count=0,
        )

    async def execute_readonly_tool(
        self,
        plan: HostedStagePlan,
        *,
        authorization: StageAuthorization,
        prompt: str,
        lookup: LocalSourceLookup,
    ) -> HostedStageObservation:
        if plan.stage != "readonly_tool":
            raise HostedPhase2Error("readonly_tool_stage_required")
        if type(lookup) is not LocalSourceLookup:
            raise HostedPhase2Error("readonly_lookup_capability_invalid")

        agent = self._readonly_agent(plan, lookup)
        if (
            self.preview_agent_graph_identity(plan, lookup=lookup)
            != plan.agent_graph_identity
        ):
            raise HostedPhase2Error("agent_graph_identity_mismatch")
        self._consume_before_key(plan, authorization, prompt)
        self._authorize_network()
        data = await self._run(agent, prompt, plan)
        tool_calls = tuple("lookup_public_source" for _ in lookup.calls)
        return HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output=data.output,
            requests=data.requests,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            latency_ms=data.latency_ms,
            tool_calls=tool_calls,
            last_agent=data.last_agent,
            handoff_count=0,
        )

    async def execute_handoff(
        self,
        plan: HostedStagePlan,
        *,
        authorization: StageAuthorization,
        prompt: str,
    ) -> HandoffExecution:
        if plan.stage != "handoff":
            raise HostedPhase2Error("handoff_stage_required")
        architecture = self._handoff_agent(plan)
        self._verify_graph(plan, architecture)
        self._consume_before_key(plan, authorization, prompt)
        self._authorize_network()
        data = await self._run(architecture, prompt, plan)
        handoff_count = 1 if data.last_agent == "test" else 0
        observation = HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output=data.output,
            requests=data.requests,
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            latency_ms=data.latency_ms,
            tool_calls=(),
            last_agent=data.last_agent,
            handoff_count=handoff_count,
        )
        architecture_receipt = RoleReceipt(
            role="architecture",
            task_id=plan.task_id,
            source_identity=plan.source_identity,
            context_digest=plan.context_digest,
            agent_graph_identity=plan.agent_graph_identity,
            model=plan.model,
            authorization_digest=authorization.authorization_digest,
            input_digest=plan.predecessor_receipt_digest,
            output_digest=content_digest({"prompt": prompt}),
            verdict="PASS",
        )
        test_receipt = RoleReceipt(
            role="test",
            task_id=plan.task_id,
            source_identity=plan.source_identity,
            context_digest=plan.context_digest,
            agent_graph_identity=plan.agent_graph_identity,
            model=plan.model,
            authorization_digest=authorization.authorization_digest,
            input_digest=architecture_receipt.output_digest,
            output_digest=content_digest(data.output),
            verdict="PASS",
        )
        return HandoffExecution(
            observation=observation,
            role_receipts=(architecture_receipt, test_receipt),
            handoff_receipt=derive_handoff_receipt(architecture_receipt, test_receipt),
        )

    async def execute_development_loop(
        self,
        plan: HostedStagePlan,
        *,
        authorization: StageAuthorization,
        prompts: Mapping[str, str],
    ) -> DevelopmentExecution:
        if plan.stage != "development_loop":
            raise HostedPhase2Error("development_loop_stage_required")
        if tuple(prompts) != plan.handoff_route:
            raise HostedPhase2Error("development_loop_prompt_topology_invalid")
        if self.preview_agent_graph_identity(plan) != plan.agent_graph_identity:
            raise HostedPhase2Error("agent_graph_identity_mismatch")
        prompt_packet = content_digest({"prompts": dict(prompts)})
        self._consume_before_key(plan, authorization, prompt_packet)
        self._authorize_network()

        prior_output: dict[str, Any] | None = None
        input_digest = plan.predecessor_receipt_digest
        role_receipts: list[RoleReceipt] = []
        outputs: dict[str, dict[str, Any]] = {}
        requests = input_tokens = output_tokens = latency_ms = 0
        try:
            async with asyncio.timeout(plan.timeout_seconds):
                for role in plan.handoff_route:
                    suffix = ""
                    if prior_output is not None:
                        suffix = "\nUpstream public packet:\n" + canonical_json(
                            prior_output
                        )
                    role_prompt = prompts[role] + suffix
                    if len(role_prompt) > plan.max_input_chars:
                        raise HostedPhase2Error("prompt_exceeds_plan")
                    agent = self._role_agent(role, plan)
                    data = await self._run(agent, role_prompt, plan)
                    if data.last_agent != role:
                        raise HostedPhase2Error("development_role_identity_mismatch")
                    if data.output.get("verdict") != "PASS":
                        raise HostedPhase2Error(f"{role}_role_not_pass")
                    output_digest = content_digest(data.output)
                    role_receipts.append(
                        RoleReceipt(
                            role=role,
                            task_id=plan.task_id,
                            source_identity=plan.source_identity,
                            context_digest=plan.context_digest,
                            agent_graph_identity=plan.agent_graph_identity,
                            model=plan.model,
                            authorization_digest=authorization.authorization_digest,
                            input_digest=input_digest,
                            output_digest=output_digest,
                            verdict="PASS",
                        )
                    )
                    outputs[role] = data.output
                    prior_output = data.output
                    input_digest = output_digest
                    requests += data.requests
                    input_tokens += data.input_tokens
                    output_tokens += data.output_tokens
                    latency_ms += data.latency_ms
        except TimeoutError as exc:
            raise HostedPhase2Error("hosted_run_timeout") from exc

        development = outputs["development"]
        test = outputs["test"]
        quality = outputs["quality"]
        observation = HostedStageObservation(
            stage=plan.stage,
            plan_digest=plan.plan_digest,
            output={
                "summary": quality["summary"],
                "changed_paths": development["next_actions"],
                "tests": test["next_actions"],
                "verdict": quality["verdict"],
            },
            requests=requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            tool_calls=(),
            last_agent="quality",
            handoff_count=3,
        )
        return DevelopmentExecution(
            observation=observation,
            role_receipts=tuple(role_receipts),
        )

    def _architecture_agent(self, plan: HostedStagePlan) -> Any:
        return self._agent(
            name="architecture",
            instructions=_ARCHITECTURE_INSTRUCTIONS,
            plan=plan,
            output_type=ArchitectureOutput,
        )

    def _readonly_agent(self, plan: HostedStagePlan, lookup: LocalSourceLookup) -> Any:
        def lookup_public_source(path: str) -> str:
            """Return one exact allowlisted public source file as UTF-8 text."""

            return lookup.lookup(path)

        tool = self._runtime.approved_function_tool(
            lookup_public_source,
            name="lookup_public_source",
        )
        return self._agent(
            name="architecture",
            instructions=_READONLY_INSTRUCTIONS,
            plan=plan,
            output_type=ReadonlyToolOutput,
            tools=(tool,),
        )

    def _handoff_agent(self, plan: HostedStagePlan) -> Any:
        test_agent = self._agent(
            name="test",
            instructions=_HANDOFF_TEST_INSTRUCTIONS,
            plan=plan,
            output_type=HandoffTestOutput,
        )
        return self._agent(
            name="architecture",
            instructions=_HANDOFF_ARCHITECTURE_INSTRUCTIONS,
            plan=plan,
            handoffs=(test_agent,),
        )

    def _role_agent(self, role: str, plan: HostedStagePlan) -> Any:
        role_requirement = {
            "architecture": "Put bounded public-repository scope decisions in next_actions.",
            "test": "Put concrete deterministic test names or commands in next_actions.",
            "development": (
                "Put only repository-relative proposed changed paths under src/, tests/, "
                "scripts/, docs/, or .github/ in next_actions; do not put prose there."
            ),
            "quality": "Put only evidence checks in next_actions and reject unsupported PASS.",
        }[role]
        return self._agent(
            name=role,
            instructions=(
                f"Act only as the {role} specialist for this bounded public task. Return "
                "the exact structured DevelopmentRoleOutput. Use PASS only when your "
                "role-specific evidence is complete; grant no release or runtime authority. "
                + role_requirement
            ),
            plan=plan,
            output_type=DevelopmentRoleOutput,
        )

    def _verify_graph(self, plan: HostedStagePlan, agent: Any) -> None:
        if self._runtime.agent_graph_identity(agent) != plan.agent_graph_identity:
            raise HostedPhase2Error("agent_graph_identity_mismatch")

    def _agent(
        self,
        *,
        name: str,
        instructions: str,
        plan: HostedStagePlan,
        output_type: type[Any] | None = None,
        tools: tuple[Any, ...] = (),
        handoffs: tuple[Any, ...] = (),
    ) -> Any:
        from agents import ModelSettings

        agent = self._runtime.agent(
            name,
            instructions,
            model=MODEL_ID,
            tools=tools,
            handoffs=handoffs,
            output_type=output_type,
        )
        agent.model_settings = ModelSettings(
            max_tokens=plan.max_output_tokens,
            store=False,
            timeout=float(plan.timeout_seconds),
        )
        return agent

    async def _run(self, agent: Any, prompt: str, plan: HostedStagePlan) -> _RunData:
        from agents import RunConfig

        run_config = RunConfig(
            tracing_disabled=True,
            trace_include_sensitive_data=False,
            workflow_name=f"quantengine-public-{plan.stage}",
        )
        started = self._monotonic()
        try:
            result = await asyncio.wait_for(
                self._runner(
                    agent,
                    prompt,
                    max_turns=plan.max_turns,
                    run_config=run_config,
                ),
                timeout=plan.timeout_seconds,
            )
        except TimeoutError as exc:
            raise HostedPhase2Error("hosted_run_timeout") from exc
        elapsed_ms = max(0, int((self._monotonic() - started) * 1_000))
        output = result.final_output
        if isinstance(output, BaseModel):
            output = output.model_dump(mode="json")
        elif isinstance(output, Mapping):
            output = dict(output)
        else:
            raise HostedPhase2Error("hosted_output_not_structured")
        usage = result.context_wrapper.usage
        last_agent = getattr(result.last_agent, "name", None)
        return _RunData(
            output=output,
            requests=_positive_usage(usage.requests, "requests"),
            input_tokens=_nonnegative_usage(usage.input_tokens, "input_tokens"),
            output_tokens=_nonnegative_usage(usage.output_tokens, "output_tokens"),
            latency_ms=elapsed_ms,
            last_agent=str(last_agent or ""),
        )

    def _consume_before_key(
        self,
        plan: HostedStagePlan,
        authorization: StageAuthorization,
        prompt: str,
    ) -> None:
        if type(self._authority) is not HostedRunAuthority:
            raise HostedPhase2Error("run_authority_required")
        self._authority.consume(plan, authorization, prompt=prompt)

    def _authorize_network(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise HostedPhase2Error("hosted_api_key_missing")
        if self._test_mode:
            return
        if type(self._run_claim) is not DurableRunClaim:
            raise HostedPhase2Error("durable_run_claim_required")
        self._run_claim.claim()


def _positive_usage(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HostedPhase2Error(f"hosted_usage_{name}_invalid")
    return value


def _nonnegative_usage(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HostedPhase2Error(f"hosted_usage_{name}_invalid")
    return value
