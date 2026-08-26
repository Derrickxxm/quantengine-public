"""A thin, fail-closed adapter around the OpenAI Agents SDK.

The SDK owns Agent execution, sessions, resumable ``RunState`` objects, handoffs,
tool approvals, and tracing.  This module deliberately does not implement a
second orchestrator or a release/control plane.  It only provides stable import
points for the public MVP and rejects SDK built-in tools until the repository's
authority policy explicitly covers their approval and evidence semantics.
"""

from __future__ import annotations

import importlib.metadata
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import SCHEMA_VERSION, content_digest

SDK_PACKAGE = "openai-agents"
SDK_REQUIRED_VERSION = "0.22.0"
RUN_STATE_ENVELOPE_VERSION = f"{SCHEMA_VERSION}.run-state"
MAX_TURNS = 100
try:
    SDK_VERSION: str | None = importlib.metadata.version(SDK_PACKAGE)
except importlib.metadata.PackageNotFoundError:
    SDK_VERSION = None

try:  # Keep the base package importable before the optional runtime is installed.
    import agents as _agents
except ImportError:  # pragma: no cover - exercised by the base test environment.
    _agents: Any = None


class SdkUnavailableError(RuntimeError):
    """Raised when the optional Agents SDK dependency is not installed."""


class UnsupportedToolError(ValueError):
    """Raised when a tool has no repository-owned fail-closed policy yet."""


def _require_sdk() -> Any:
    if _agents is None or SDK_VERSION is None:
        raise SdkUnavailableError(
            f"The Native-Agent runtime requires {SDK_PACKAGE}=={SDK_REQUIRED_VERSION}; "
            "install the declared optional dependency before running it."
        )
    if SDK_VERSION != SDK_REQUIRED_VERSION:
        raise SdkUnavailableError(
            "sdk_version_mismatch:"
            f"required={SDK_REQUIRED_VERSION}:installed={SDK_VERSION}"
        )
    return _agents


def _validate_tools(tools: Iterable[Any]) -> tuple[Any, ...]:
    sdk = _require_sdk()
    function_tool = sdk.FunctionTool
    checked = tuple(tools)
    unsupported = tuple(tool for tool in checked if not isinstance(tool, function_tool))
    if unsupported:
        names = ", ".join(type(tool).__name__ for tool in unsupported)
        raise UnsupportedToolError(
            "Built-in or non-function tools are blocked by default because their "
            f"approval/evidence policy is not implemented: {names}"
        )
    return checked


def _agent_graph_payload(agent: Any, sdk: Any, seen: set[int]) -> dict[str, Any]:
    if not isinstance(agent, sdk.Agent):
        raise UnsupportedToolError("agent_graph_contains_non_agent")
    marker = id(agent)
    if marker in seen:
        raise UnsupportedToolError("agent_graph_cycle")
    seen.add(marker)
    if getattr(agent, "mcp_servers", ()) or getattr(agent, "mcp_config", {}):
        raise UnsupportedToolError("agent_graph_contains_mcp_tools")
    tools = _validate_tools(agent.tools)
    handoffs = []
    for handoff in agent.handoffs:
        if not isinstance(handoff, sdk.Agent):
            raise UnsupportedToolError("agent_graph_contains_opaque_handoff")
        handoffs.append(_agent_graph_payload(handoff, sdk, seen))
    seen.remove(marker)
    instructions = agent.instructions if isinstance(agent.instructions, str) else type(agent.instructions).__qualname__
    return {
        "name": agent.name,
        "instructions": instructions,
        "output_type": getattr(agent.output_type, "__qualname__", None),
        "tools": [
            {
                "type": type(tool).__qualname__,
                "name": getattr(tool, "name", None),
                "needs_approval": getattr(tool, "needs_approval", None),
            }
            for tool in tools
        ],
        "handoffs": handoffs,
    }


def _agent_graph_identity(agent: Any, sdk: Any) -> str:
    return content_digest(_agent_graph_payload(agent, sdk, set()))


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}_required")
    return value


def _require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name}_invalid")
    return value


@dataclass(frozen=True)
class AgentsSdkRuntime:
    """Small adapter exposing only the approved SDK runtime seams."""

    workflow_name: str = "quantengine-public-native-agent"

    @property
    def sdk_version(self) -> str:
        _require_sdk()
        assert SDK_VERSION is not None
        return SDK_VERSION

    def agent_graph_identity(self, agent: Any) -> str:
        """Return the deterministic identity used by durable RunState envelopes."""

        return _agent_graph_identity(agent, _require_sdk())

    def agent(
        self,
        name: str,
        instructions: str,
        *,
        model: Any = None,
        tools: Iterable[Any] = (),
        handoffs: Iterable[Any] = (),
        output_type: type[Any] | None = None,
    ) -> Any:
        """Construct an SDK Agent after applying the default tool boundary."""

        sdk = _require_sdk()
        handoff_list = tuple(handoffs)
        if any(not isinstance(handoff, sdk.Agent) for handoff in handoff_list):
            raise UnsupportedToolError("agent_graph_contains_opaque_handoff")
        return sdk.Agent(
            name=name,
            instructions=instructions,
            model=model,
            tools=list(_validate_tools(tools)),
            handoffs=list(handoff_list),
            output_type=output_type,
        )

    def session(self, session_id: str, db_path: str | Path = ":memory:") -> Any:
        """Return the SDK's persistent SQLite conversation session."""

        return _require_sdk().SQLiteSession(session_id, db_path=db_path)

    async def run(
        self,
        agent: Any,
        input_or_state: str | list[Any] | Any,
        *,
        context: Any = None,
        max_turns: int | None = 10,
        run_config: Any = None,
        session: Any = None,
    ) -> Any:
        """Run or resume an SDK workflow without introducing another state machine."""

        sdk = _require_sdk()
        if not isinstance(agent, sdk.Agent):
            raise UnsupportedToolError("agent_required")
        _agent_graph_identity(agent, sdk)
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or not 1 <= max_turns <= MAX_TURNS:
            raise ValueError(f"max_turns_must_be_between_1_and_{MAX_TURNS}")
        self._reject_sandbox(run_config)
        return await sdk.Runner.run(
            agent,
            input_or_state,
            context=context,
            max_turns=max_turns,
            run_config=run_config,
            session=session,
        )

    def agent_as_tool(
        self,
        agent: Any,
        *,
        tool_name: str,
        tool_description: str,
        needs_approval: bool = False,
    ) -> Any:
        """Expose the SDK's Agent-as-tool seam with explicit approval opt-in."""

        sdk = _require_sdk()
        _agent_graph_identity(agent, sdk)
        return agent.as_tool(
            tool_name=tool_name,
            tool_description=tool_description,
            needs_approval=needs_approval,
        )

    def serialize_state(
        self,
        state: Any,
        *,
        task_id: str,
        source_identity: str,
        context_digest: str,
        graph_identity: str | None,
        skill_identity: str,
        tool_policy_identity: str,
    ) -> dict[str, Any]:
        """Serialize an SDK RunState for an external durable store."""

        sdk = _require_sdk()
        to_json = getattr(state, "to_json", None)
        if not callable(to_json):
            raise TypeError("state must be an OpenAI Agents SDK RunState")
        starting_agent = getattr(state, "_starting_agent", None)
        if starting_agent is None:
            raise ValueError("state_agent_required")
        body = {
            "schema_version": RUN_STATE_ENVELOPE_VERSION,
            "sdk_package": SDK_PACKAGE,
            "sdk_version": SDK_REQUIRED_VERSION,
            "task_id": _require_text(task_id, "task_id"),
            "source_identity": _require_digest(source_identity, "source_identity"),
            "context_digest": _require_digest(context_digest, "context_digest"),
            "graph_identity": None if graph_identity is None else _require_digest(graph_identity, "graph_identity"),
            "skill_identity": _require_text(skill_identity, "skill_identity"),
            "tool_policy_identity": _require_text(tool_policy_identity, "tool_policy_identity"),
            "agent_graph_identity": _agent_graph_identity(starting_agent, sdk),
            "state": to_json(strict_context=True),
        }
        return {**body, "envelope_digest": content_digest(body)}

    async def deserialize_state(
        self,
        initial_agent: Any,
        state: Mapping[str, Any] | str,
        *,
        task_id: str,
        source_identity: str,
        context_digest: str,
        graph_identity: str | None,
        skill_identity: str,
        tool_policy_identity: str,
        context_override: Any = None,
    ) -> Any:
        """Restore a serialized SDK RunState with the supplied agent graph."""

        sdk = _require_sdk()
        if context_override is not None:
            raise ValueError("context_override_forbidden")
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except json.JSONDecodeError as exc:
                raise ValueError("run_state_envelope_invalid") from exc
        if not isinstance(state, Mapping):
            raise ValueError("run_state_envelope_required")
        envelope = dict(state)
        supplied = envelope.pop("envelope_digest", None)
        if envelope.get("schema_version") != RUN_STATE_ENVELOPE_VERSION:
            raise ValueError("run_state_envelope_schema_mismatch")
        if supplied is None or supplied != content_digest(envelope):
            raise ValueError("run_state_envelope_digest_mismatch")
        expected = {
            "task_id": _require_text(task_id, "task_id"),
            "source_identity": _require_digest(source_identity, "source_identity"),
            "context_digest": _require_digest(context_digest, "context_digest"),
            "graph_identity": None if graph_identity is None else _require_digest(graph_identity, "graph_identity"),
            "skill_identity": _require_text(skill_identity, "skill_identity"),
            "tool_policy_identity": _require_text(tool_policy_identity, "tool_policy_identity"),
        }
        for name, value in expected.items():
            if envelope.get(name) != value:
                raise ValueError(f"run_state_{name}_mismatch")
        if envelope.get("sdk_package") != SDK_PACKAGE or envelope.get("sdk_version") != SDK_REQUIRED_VERSION:
            raise ValueError("run_state_sdk_identity_mismatch")
        if envelope.get("agent_graph_identity") != _agent_graph_identity(initial_agent, sdk):
            raise ValueError("run_state_agent_graph_identity_mismatch")
        snapshot = envelope.get("state")
        if not isinstance(snapshot, Mapping):
            raise ValueError("run_state_snapshot_required")
        return await sdk.RunState.from_json(
            initial_agent,
            dict(snapshot),
            context_override=None,
            strict_context=True,
        )

    @staticmethod
    def add_trace_processor(processor: Any) -> None:
        """Register an SDK ``TracingProcessor``; no remote exporter is required."""

        _require_sdk().add_trace_processor(processor)

    @staticmethod
    def approved_function_tool(
        function: Any,
        *,
        needs_approval: bool = False,
        name: str | None = None,
    ) -> Any:
        """Create an SDK function tool, optionally pausing before invocation."""

        sdk = _require_sdk()
        kwargs: dict[str, Any] = {"needs_approval": needs_approval}
        if name is not None:
            kwargs["name_override"] = name
        return sdk.function_tool(function, **kwargs)

    @staticmethod
    def _reject_sandbox(run_config: Any) -> None:
        """Reject SDK sandbox execution until its repository policy is implemented."""

        sandbox = run_config.get("sandbox") if isinstance(run_config, Mapping) else getattr(
            run_config, "sandbox", None
        )
        if sandbox is not None:
            raise UnsupportedToolError(
                "Sandbox/built-in tool execution is fail-closed in the MVP adapter; "
                "use an approved function tool until a sandbox policy exists."
            )


class RecordingTraceProcessor:
    """Minimal SDK ``TracingProcessor`` useful for local evidence tests."""

    def __init__(self) -> None:
        self.traces_started: list[Any] = []
        self.traces_finished: list[Any] = []
        self.spans_started: list[Any] = []
        self.spans_finished: list[Any] = []

    def on_trace_start(self, trace: Any) -> None:
        self.traces_started.append(trace)

    def on_trace_end(self, trace: Any) -> None:
        self.traces_finished.append(trace)

    def on_span_start(self, span: Any) -> None:
        self.spans_started.append(span)

    def on_span_end(self, span: Any) -> None:
        self.spans_finished.append(span)

    def shutdown(self) -> None:
        return None

    def force_flush(self) -> None:
        return None
