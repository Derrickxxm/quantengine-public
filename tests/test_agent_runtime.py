"""Executable, network-free contract checks for the selected Agents SDK seam."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

agents = pytest.importorskip("agents", reason="install openai-agents==0.22.0 for SDK spike")
from pydantic import BaseModel

from quantengine_public.agent_platform.runtime import (
    AgentsSdkRuntime,
    RecordingTraceProcessor,
    SDK_PACKAGE,
    SDK_VERSION,
    SdkUnavailableError,
    UnsupportedToolError,
)


class Decision(BaseModel):
    answer: str


def test_sdk_import_and_version_are_real() -> None:
    assert SDK_PACKAGE == "openai-agents"
    assert SDK_VERSION == "0.22.0"
    assert agents.Agent.__module__.startswith("agents.")


def test_runtime_rejects_sdk_version_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("quantengine_public.agent_platform.runtime.SDK_VERSION", "0.21.0")
    with pytest.raises(SdkUnavailableError, match="version_mismatch"):
        _ = AgentsSdkRuntime().sdk_version


def test_structured_output_uses_sdk_runner_and_scripted_model() -> None:
    from agents import Runner
    from agents.testing import ScriptedModel, assistant_message

    model = ScriptedModel([[assistant_message('{"answer":"accepted"}')]])
    agent = agents.Agent(
        name="architecture",
        instructions="Return a structured decision.",
        model=model,
        output_type=Decision,
    )
    result = asyncio.run(Runner.run(agent, "review", run_config={"tracing_disabled": True}))

    assert isinstance(result.final_output, Decision)
    assert result.final_output.answer == "accepted"
    model.assert_complete()


def test_sqlite_session_persists_history_across_instances(tmp_path: Path) -> None:
    from agents.testing import ScriptedModel, assistant_message

    db_path = tmp_path / "sessions.sqlite"
    first_model = ScriptedModel([[assistant_message("first")]])
    first = agents.Agent(name="session-agent", instructions="reply", model=first_model)
    session = AgentsSdkRuntime().session("task-1260", db_path)
    asyncio.run(
        AgentsSdkRuntime().run(
            first, "hello", run_config={"tracing_disabled": True}, session=session
        )
    )
    first_model.assert_complete()

    second_session = AgentsSdkRuntime().session("task-1260", db_path)
    items = asyncio.run(second_session.get_items())
    assert len(items) == 2
    assert json.dumps(items, default=str, ensure_ascii=False).find("first") >= 0


def test_run_state_serializes_and_resumes_after_tool_approval() -> None:
    from agents import Agent, Runner
    from agents.testing import ScriptedModel, assistant_message, function_call

    calls: list[str] = []

    def publish(message: str) -> str:
        calls.append(message)
        return "published"

    model = ScriptedModel(
        [
            [function_call("publish", {"message": "hello"}, call_id="publish-1")],
            [assistant_message("complete")],
        ]
    )
    tool = AgentsSdkRuntime.approved_function_tool(publish, needs_approval=True)
    agent = Agent(name="publisher", instructions="publish", model=model, tools=[tool])
    runtime = AgentsSdkRuntime()
    paused = asyncio.run(runtime.run(agent, "go", run_config={"tracing_disabled": True}))

    assert len(paused.interruptions) == 1
    state_json = runtime.serialize_state(
        paused.to_state(),
        task_id="TASKSYS-1261",
        source_identity="1" * 64,
        context_digest="2" * 64,
        graph_identity=runtime.agent_graph_identity(agent),
        skill_identity="skill://development@1",
        tool_policy_identity="policy://development@1",
    )
    assert state_json["state"]["no_active_agent_run"] is True
    restored = asyncio.run(
        runtime.deserialize_state(
            agent,
            state_json,
            task_id="TASKSYS-1261",
            source_identity="1" * 64,
            context_digest="2" * 64,
            graph_identity=runtime.agent_graph_identity(agent),
            skill_identity="skill://development@1",
            tool_policy_identity="policy://development@1",
        )
    )
    restored.approve(restored.get_interruptions()[0])
    resumed = asyncio.run(runtime.run(agent, restored, run_config={"tracing_disabled": True}))

    assert resumed.final_output == "complete"
    assert calls == ["hello"]
    model.assert_complete()


def test_handoff_path_is_sdk_owned() -> None:
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    child_model = ScriptedModel([[assistant_message("child complete")]])
    child = Agent(name="test", instructions="finish", model=child_model)

    def select_child(call: object) -> list[object]:
        handoff = call.handoffs[0]  # type: ignore[attr-defined]
        return [function_call(handoff.tool_name, {}, call_id="handoff-1")]

    parent_model = ScriptedModel([ModelStep.respond(select_child)])
    parent = Agent(
        name="architecture", instructions="delegate", model=parent_model, handoffs=[child]
    )
    result = asyncio.run(
        AgentsSdkRuntime().run(parent, "start", run_config={"tracing_disabled": True})
    )

    assert result.last_agent is child
    assert result.final_output == "child complete"
    parent_model.assert_complete()
    child_model.assert_complete()


def test_trace_processor_receives_sdk_trace_without_network() -> None:
    from agents import Agent, trace
    from agents.testing import ScriptedModel, assistant_message

    processor = RecordingTraceProcessor()
    AgentsSdkRuntime.add_trace_processor(processor)
    agent = Agent(
        name="trace-agent",
        instructions="reply",
        model=ScriptedModel([[assistant_message("ok")]], emit_traces=True),
    )
    with trace("tasksys-1260"):
        result = asyncio.run(AgentsSdkRuntime().run(agent, "hello"))

    assert result.final_output == "ok"
    assert len(processor.traces_started) == 1
    assert len(processor.traces_finished) == 1
    assert processor.spans_started
    assert processor.spans_finished


def test_builtin_and_sandbox_tools_fail_closed() -> None:
    from agents import Agent, WebSearchTool

    runtime = AgentsSdkRuntime()
    with pytest.raises(UnsupportedToolError, match="Built-in or non-function tools"):
        runtime.agent("unsafe", "no", tools=[WebSearchTool()])
    with pytest.raises(UnsupportedToolError, match="Sandbox/built-in"):
        asyncio.run(
            runtime.run(
                Agent(name="a", instructions="x"), "x", run_config={"sandbox": object()}
            )
        )


def test_prebuilt_agent_and_unbounded_runs_fail_closed() -> None:
    from agents import Agent, WebSearchTool
    from agents.testing import ScriptedModel, assistant_message

    runtime = AgentsSdkRuntime()
    unsafe = Agent(
        name="unsafe",
        instructions="x",
        tools=[WebSearchTool()],
        model=ScriptedModel([[assistant_message("ok")]]),
    )
    with pytest.raises(UnsupportedToolError):
        asyncio.run(runtime.run(unsafe, "x", run_config={"tracing_disabled": True}))
    safe = Agent(
        name="safe",
        instructions="x",
        model=ScriptedModel([[assistant_message("ok")]]),
    )
    for value in (None, 0, -1, 101):
        with pytest.raises(ValueError, match="max_turns"):
            asyncio.run(runtime.run(safe, "x", max_turns=value, run_config={"tracing_disabled": True}))


def test_run_state_envelope_rejects_foreign_context_and_agent_graph() -> None:
    from agents import Agent
    from agents.testing import ScriptedModel, assistant_message, function_call

    def finish(message: str) -> str:
        return message

    model = ScriptedModel(
        [[function_call("finish", {"message": "ok"}, call_id="finish-1")], [assistant_message("done")]]
    )
    tool = AgentsSdkRuntime.approved_function_tool(finish, needs_approval=True)
    agent = Agent(name="bound", instructions="bound", model=model, tools=[tool])
    runtime = AgentsSdkRuntime()
    paused = asyncio.run(runtime.run(agent, "go", run_config={"tracing_disabled": True}))
    envelope = runtime.serialize_state(
        paused.to_state(),
        task_id="TASKSYS-1261",
        source_identity="1" * 64,
        context_digest="2" * 64,
        graph_identity=runtime.agent_graph_identity(agent),
        skill_identity="skill://development@1",
        tool_policy_identity="policy://development@1",
    )
    with pytest.raises(ValueError, match="context_override_forbidden"):
        asyncio.run(
            runtime.deserialize_state(
                agent,
                envelope,
                task_id="TASKSYS-1261",
                source_identity="1" * 64,
                context_digest="2" * 64,
                graph_identity=runtime.agent_graph_identity(agent),
                skill_identity="skill://development@1",
                tool_policy_identity="policy://development@1",
                context_override={"task_id": "EVIL"},
            )
        )
    foreign = Agent(name="bound", instructions="foreign", model=ScriptedModel([[assistant_message("x")]]), tools=[tool])
    with pytest.raises(ValueError, match="agent_graph_identity"):
        asyncio.run(
            runtime.deserialize_state(
                foreign,
                envelope,
                task_id="TASKSYS-1261",
                source_identity="1" * 64,
                context_digest="2" * 64,
                graph_identity=runtime.agent_graph_identity(agent),
                skill_identity="skill://development@1",
                tool_policy_identity="policy://development@1",
            )
        )
