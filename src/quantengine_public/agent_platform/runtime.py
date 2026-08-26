"""A thin, fail-closed adapter around the OpenAI Agents SDK.

The SDK owns Agent execution, sessions, resumable ``RunState`` objects, handoffs,
tool approvals, and tracing.  This module deliberately does not implement a
second orchestrator or a release/control plane.  It only provides stable import
points for the public MVP and rejects SDK built-in tools until the repository's
authority policy explicitly covers their approval and evidence semantics.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SDK_PACKAGE = "openai-agents"
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
            "The Native-Agent runtime requires openai-agents==0.22.0; "
            "install the declared optional dependency before running it."
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


@dataclass(frozen=True)
class AgentsSdkRuntime:
    """Small adapter exposing only the approved SDK runtime seams."""

    workflow_name: str = "quantengine-public-native-agent"

    @property
    def sdk_version(self) -> str:
        _require_sdk()
        assert SDK_VERSION is not None
        return SDK_VERSION

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
        return sdk.Agent(
            name=name,
            instructions=instructions,
            model=model,
            tools=list(_validate_tools(tools)),
            handoffs=list(handoffs),
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

        _require_sdk()
        return agent.as_tool(
            tool_name=tool_name,
            tool_description=tool_description,
            needs_approval=needs_approval,
        )

    def serialize_state(self, state: Any) -> dict[str, Any]:
        """Serialize an SDK RunState for an external durable store."""

        _require_sdk()
        to_json = getattr(state, "to_json", None)
        if not callable(to_json):
            raise TypeError("state must be an OpenAI Agents SDK RunState")
        return to_json(strict_context=True)

    async def deserialize_state(
        self,
        initial_agent: Any,
        state: Mapping[str, Any] | str,
        *,
        context_override: Any = None,
    ) -> Any:
        """Restore a serialized SDK RunState with the supplied agent graph."""

        sdk = _require_sdk()
        if isinstance(state, str):
            return await sdk.RunState.from_string(
                initial_agent,
                state,
                context_override=context_override,
                strict_context=True,
            )
        return await sdk.RunState.from_json(
            initial_agent,
            dict(state),
            context_override=context_override,
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
