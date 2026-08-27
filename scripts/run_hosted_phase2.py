"""Run the bounded hosted Phase 2 canary.

The command is deliberately a dry-run unless ``--execute`` is supplied.  A
dry-run constructs and validates the four stage plans without consulting the
process environment.  Execute mode is the only path that delegates to the
credential-isolated hosted executor.  Data returned by this module is a
public-safe receipt: model packets, prompts, credentials, and trace IDs never
cross the receipt boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quantengine_public.agent_platform.hosted_phase2 import (
    MODEL_ID,
    HostedPhase2Error,
    HostedPhase2Policy,
    DurableRunClaim,
    HostedRunAuthority,
    HostedStagePlan,
    LocalSourceLookup,
    derive_development_loop_receipt,
    evaluate_stage,
)
from quantengine_public.agent_platform.hosted_phase2_executor import (
    DevelopmentExecution,
    HandoffExecution,
    HostedAgentsExecutor,
)
from quantengine_public.agent_platform.contracts import canonical_json, content_digest


PHASE2_STAGES = ("architecture", "readonly_tool", "handoff", "development_loop")
MAX_TOTAL_BUDGET_MICROUSD = 100_000
TASK_ID = "TASKSYS-1318"
TASK_REVISION = "p2-v1"
SOURCE_PATH = "src/quantengine_public/agent_platform/hosted_canary.py"
_ZERO_DIGEST = "0" * 64
_SEED_DIGEST = content_digest({"task_id": TASK_ID, "task_revision": TASK_REVISION, "phase": "hosted-phase2"})
_APPROVAL_SCOPE_DIGEST = content_digest(
    {
        "owner_decision": "DEC-0017",
        "task_id": TASK_ID,
        "task_revision": TASK_REVISION,
    }
)
_PUBLIC_FIELDS = frozenset(
    {
        "stage",
        "status",
        "plan_digest",
        "receipt_digest",
        "output_digest",
        "usage",
        "accounted_cost_microusd",
        "latency_ms",
        "authority_flags",
    }
)


def _git_snapshot(root: Path) -> tuple[str, bool]:
    """Return HEAD and worktree dirtiness without placing paths in evidence."""

    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if not head:
        raise HostedPhase2Error("git_head_unavailable")
    return head, bool(status.strip())


def _durable_claim_state_dir() -> Path:
    configured = os.getenv("XDG_STATE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    return base / "quantengine-public" / "hosted-phase2"


def _source_metadata(root: Path) -> tuple[str, str, bool, str]:
    source_path = root / SOURCE_PATH
    try:
        source_bytes = source_path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise HostedPhase2Error("public_source_unreadable") from exc
    file_digest = hashlib.sha256(source_bytes).hexdigest()
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise HostedPhase2Error("public_source_unreadable") from exc
    head, dirty = _git_snapshot(root)
    source_identity = content_digest(
        {
            "source_path": SOURCE_PATH,
            "git_head": head,
            "file_sha256": file_digest,
            "worktree_dirty": dirty,
        }
    )
    return source_identity, file_digest, dirty, source


def _architecture_packet(source: str, *, max_chars: int, file_digest: str) -> str:
    """Build a bounded packet from a relative path, summary, and source bytes."""
    summary = (
        "PUBLIC SOURCE PACKET\n"
        f"relative_path={SOURCE_PATH}\n"
        f"file_sha256={file_digest}\n"
        f"source_chars={len(source)}\n"
        "The packet is public, fixed, and read-only; reason only from this content.\n"
        "SOURCE CONTENT (truncated only if required):\n"
    )
    if len(summary) >= max_chars:
        return summary[:max_chars]
    return summary + source[: max_chars - len(summary)]


def _prompts(architecture_packet: str) -> dict[str, str]:
    """Return fixed public task packets; none are included in receipts."""

    bounded_packet = architecture_packet[:16_000]
    return {
        "architecture": architecture_packet,
        "readonly_tool": f"Use lookup_public_source once for {SOURCE_PATH}, then report source-grounded facts.",
        "handoff": (
            "Transfer this public validation packet from architecture to test and have Test "
            "derive concrete negative cases.\n" + bounded_packet
        ),
        "development_loop": (
            "Process this read-only public hardening task as your assigned role. Architecture "
            "identifies risks, Test defines executable checks, Development proposes bounded "
            "source changes, and Quality returns PASS only with evidence. No role may write, "
            "release, deploy, or request secrets.\n" + bounded_packet
        ),
    }


def _authorization_prompt_packets(prompts: Mapping[str, str]) -> dict[str, str]:
    return {
        stage: (
            content_digest(
                {"prompts": {role: prompts[stage] for role in ("architecture", "test", "development", "quality")}}
            )
            if stage == "development_loop"
            else prompts[stage]
        )
        for stage in PHASE2_STAGES
    }


def _base_plan(
    stage: str,
    predecessor: str,
    *,
    source_identity: str,
    max_input_chars: int,
) -> HostedStagePlan:
    tools = ("lookup_public_source",) if stage == "readonly_tool" else ()
    route = ("architecture", "test") if stage == "handoff" else ()
    if stage == "development_loop":
        route = ("architecture", "test", "development", "quality")
    return HostedStagePlan(
        stage=stage,
        task_id=TASK_ID,
        task_revision=TASK_REVISION,
        source_identity=source_identity,
        context_digest=content_digest({"task_id": TASK_ID, "stage": stage, "revision": TASK_REVISION}),
        agent_graph_identity=_ZERO_DIGEST,
        predecessor_receipt_digest=predecessor,
        model=MODEL_ID,
        max_turns=2,
        max_input_chars=max_input_chars,
        max_output_tokens=1_200,
        timeout_seconds=90,
        trace_mode="disabled",
        evidence_mode="digest_only",
        tool_names=tools,
        handoff_route=route,
    )


def _plan_for(
    stage: str,
    predecessor: str,
    executor: Any,
    lookup: LocalSourceLookup,
    *,
    source_identity: str,
    max_input_chars: int,
) -> HostedStagePlan:
    draft = _base_plan(
        stage,
        predecessor,
        source_identity=source_identity,
        max_input_chars=max_input_chars,
    )
    kwargs: dict[str, Any] = {}
    if stage == "readonly_tool":
        kwargs["lookup"] = lookup
    graph_identity = executor.preview_agent_graph_identity(draft, **kwargs)
    return replace(draft, agent_graph_identity=graph_identity)


def _authority_flags(stage: str, *, execute: bool) -> dict[str, bool]:
    return {
        "authorized": execute,
        "execution_allowed": execute,
        "tool_authority_granted": stage == "readonly_tool",
        "handoff_authority_granted": stage in {"handoff", "development_loop"},
        "write_authority_granted": False,
        "release_authority_granted": False,
        "hosted_trace_enabled": False,
    }


def _planned_row(plan: HostedStagePlan) -> dict[str, Any]:
    planned_receipt = content_digest({"stage": plan.stage, "plan_digest": plan.plan_digest, "status": "PLANNED"})
    return {
        "stage": plan.stage,
        "status": "PLANNED",
        "plan_digest": plan.plan_digest,
        "receipt_digest": planned_receipt,
        "output_digest": _ZERO_DIGEST,
        "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0},
        "accounted_cost_microusd": 0,
        "latency_ms": 0,
        "authority_flags": _authority_flags(plan.stage, execute=False),
    }


def _receipt_row(receipt: Any, *, execute: bool) -> dict[str, Any]:
    return {
        "stage": receipt.stage,
        "status": "PASS",
        "plan_digest": receipt.plan_digest,
        "receipt_digest": receipt.receipt_digest,
        "output_digest": receipt.output_digest,
        "usage": {
            "requests": receipt.requests,
            "input_tokens": receipt.input_tokens,
            "output_tokens": receipt.output_tokens,
        },
        "accounted_cost_microusd": receipt.actual_cost_microusd,
        "latency_ms": receipt.latency_ms,
        "authority_flags": _authority_flags(receipt.stage, execute=execute),
    }


def _blocked_row(plan: HostedStagePlan, *, reserved_cost_microusd: int) -> dict[str, Any]:
    return {
        "stage": plan.stage,
        "status": "BLOCKED",
        "plan_digest": plan.plan_digest,
        "receipt_digest": content_digest(
            {
                "stage": plan.stage,
                "plan_digest": plan.plan_digest,
                "status": "BLOCKED",
                "reserved_cost_microusd": reserved_cost_microusd,
            }
        ),
        "output_digest": _ZERO_DIGEST,
        "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0},
        "accounted_cost_microusd": reserved_cost_microusd,
        "latency_ms": 0,
        "authority_flags": _authority_flags(plan.stage, execute=True),
    }


def _sum_usage(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        key: sum(int(row["usage"][key]) for row in rows)
        for key in ("requests", "input_tokens", "output_tokens")
    }


def _strict_public_row(source: Mapping[str, Any]) -> dict[str, Any]:
    if set(source) != _PUBLIC_FIELDS:
        raise ValueError("public_receipt_fields_invalid")
    usage_source = source["usage"]
    flags_source = source["authority_flags"]
    expected_usage = {"requests", "input_tokens", "output_tokens"}
    expected_flags = {
        "authorized",
        "execution_allowed",
        "tool_authority_granted",
        "handoff_authority_granted",
        "write_authority_granted",
        "release_authority_granted",
        "hosted_trace_enabled",
    }
    if not isinstance(usage_source, Mapping) or set(usage_source) != expected_usage:
        raise ValueError("public_receipt_usage_invalid")
    if not isinstance(flags_source, Mapping) or set(flags_source) != expected_flags:
        raise ValueError("public_receipt_authority_flags_invalid")
    usage: dict[str, int] = {}
    for key in sorted(expected_usage):
        value = usage_source[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("public_receipt_usage_invalid")
        usage[key] = value
    flags: dict[str, bool] = {}
    for key in sorted(expected_flags):
        value = flags_source[key]
        if not isinstance(value, bool):
            raise ValueError("public_receipt_authority_flags_invalid")
        flags[key] = value
    row = {
        "stage": str(source["stage"]),
        "status": str(source["status"]),
        "plan_digest": str(source["plan_digest"]),
        "receipt_digest": str(source["receipt_digest"]),
        "output_digest": str(source["output_digest"]),
        "usage": usage,
        "accounted_cost_microusd": source["accounted_cost_microusd"],
        "latency_ms": source["latency_ms"],
        "authority_flags": flags,
    }
    if row["stage"] not in PHASE2_STAGES or row["status"] not in {"PLANNED", "PASS", "BLOCKED"}:
        raise ValueError("public_receipt_stage_invalid")
    for name in ("plan_digest", "receipt_digest", "output_digest"):
        value = row[name]
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("public_receipt_digest_invalid")
    for name in ("accounted_cost_microusd", "latency_ms"):
        value = row[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("public_receipt_metric_invalid")
    return row


def build_public_receipt(
    *,
    execution_mode: str,
    stages: Sequence[Mapping[str, Any]],
    failure_digest: str | None = None,
) -> dict[str, Any]:
    """Build a receipt using an explicit digest/usage/cost/latency allowlist."""

    if execution_mode not in {"dry_run", "execute"}:
        raise ValueError("execution_mode_invalid")
    rows: list[dict[str, Any]] = []
    for source in stages:
        rows.append(_strict_public_row(source))
    observed_stages = tuple(row["stage"] for row in rows)
    if observed_stages != PHASE2_STAGES[: len(rows)]:
        raise ValueError("public_receipt_stage_order_invalid")
    if failure_digest is not None and (
        len(failure_digest) != 64
        or any(character not in "0123456789abcdef" for character in failure_digest)
    ):
        raise ValueError("public_receipt_failure_digest_invalid")
    statuses = tuple(row["status"] for row in rows)
    if execution_mode == "dry_run":
        if failure_digest is None:
            if len(rows) != len(PHASE2_STAGES) or any(status != "PLANNED" for status in statuses):
                raise ValueError("dry_run_receipt_topology_invalid")
            verdict = "PLANNED"
        elif rows:
            raise ValueError("dry_run_failure_receipt_invalid")
        else:
            verdict = "BLOCKED"
    elif failure_digest is None:
        if len(rows) != len(PHASE2_STAGES) or any(status != "PASS" for status in statuses):
            raise ValueError("execute_receipt_topology_invalid")
        verdict = "PASS"
    else:
        if rows and (statuses[-1] != "BLOCKED" or any(status != "PASS" for status in statuses[:-1])):
            raise ValueError("blocked_receipt_topology_invalid")
        verdict = "BLOCKED"
    for row in rows:
        expected_flags = _authority_flags(
            row["stage"],
            execute=execution_mode == "execute",
        )
        if row["authority_flags"] != expected_flags:
            raise ValueError("public_receipt_authority_flags_mismatch")
    cost = sum(int(row["accounted_cost_microusd"]) for row in rows)
    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0 or cost > MAX_TOTAL_BUDGET_MICROUSD:
        raise ValueError("hosted budget exceeded")
    usage = _sum_usage(rows)
    latency_ms = sum(int(row["latency_ms"]) for row in rows)
    body: dict[str, Any] = {
        "schema_version": "quantengine_public.hosted_phase2.public_receipt.v1",
        "execution_mode": execution_mode,
        "model": MODEL_ID,
        "verdict": verdict,
        "stages": rows,
        "total": {
            "usage": usage,
            "accounted_cost_microusd": cost,
            "latency_ms": latency_ms,
        },
        "authority_flags": {
            "hosted_trace_enabled": False,
            "write_authority_granted": False,
            "release_authority_granted": False,
            "deployment_authority_granted": False,
            "quantengine_runtime_authority_granted": False,
        },
    }
    if failure_digest is not None:
        body["failure_digest"] = failure_digest
    body["receipt_digest"] = content_digest(body)
    return body


async def _execute(
    *,
    executor: Any,
    policy: HostedPhase2Policy,
    lookup: LocalSourceLookup,
    source_identity: str,
    prompts: Mapping[str, str],
    authority: HostedRunAuthority,
) -> tuple[list[dict[str, Any]], str | None]:
    rows: list[dict[str, Any]] = []
    predecessor = _SEED_DIGEST
    authorization_prompts = _authorization_prompt_packets(prompts)
    for stage in PHASE2_STAGES:
        plan = _plan_for(
            stage,
            predecessor,
            executor,
            lookup,
            source_identity=source_identity,
            max_input_chars=policy.max_input_chars,
        )
        prompt_packet = authorization_prompts[stage]
        authorization = authority.authorize(plan, prompt=prompt_packet)
        try:
            if stage == "architecture":
                observation = await executor.execute_architecture(
                    plan, authorization=authorization, prompt=prompts[stage]
                )
            elif stage == "readonly_tool":
                observation = await executor.execute_readonly_tool(
                    plan, authorization=authorization, prompt=prompts[stage], lookup=lookup
                )
            elif stage == "handoff":
                handoff: HandoffExecution = await executor.execute_handoff(
                    plan, authorization=authorization, prompt=prompts[stage]
                )
                if len(handoff.role_receipts) != 2:
                    raise HostedPhase2Error("handoff_role_receipts_required")
                observation = handoff.observation
            else:
                development: DevelopmentExecution = await executor.execute_development_loop(
                    plan,
                    authorization=authorization,
                    prompts={role: prompts[stage] for role in plan.handoff_route},
                )
                observation = development.observation
                if len(development.role_receipts) != len(plan.handoff_route):
                    raise HostedPhase2Error("development_loop_role_receipts_required")
                derive_development_loop_receipt(development.role_receipts)
            receipt = evaluate_stage(
                observation,
                plan,
                policy,
                spent_microusd=authority.accounted_cost_microusd,
            )
            authority.settle(
                authorization,
                receipt=receipt,
            )
        except Exception as exc:
            authority.block(authorization)
            rows.append(
                _blocked_row(
                    plan,
                    reserved_cost_microusd=authorization.reserved_cost_microusd,
                )
            )
            return rows, content_digest({"error_type": type(exc).__name__, "stage": stage})
        rows.append(_receipt_row(receipt, execute=True))
        predecessor = receipt.receipt_digest
    return rows, None


def _run_phase2(
    *,
    execute: bool = False,
    executor: Any | None = None,
    root: str | Path | None = None,
    policy: HostedPhase2Policy | None = None,
) -> dict[str, Any]:
    """Plan all four gates, or execute them when explicitly requested."""

    policy = policy or HostedPhase2Policy(total_budget_microusd=MAX_TOTAL_BUDGET_MICROUSD)
    if policy.total_budget_microusd > MAX_TOTAL_BUDGET_MICROUSD:
        raise HostedPhase2Error("runner_budget_cap_exceeded")
    source_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    source_identity, file_digest, dirty, source_snapshot = _source_metadata(source_root)
    if execute and dirty:
        raise HostedPhase2Error("execute_requires_clean_worktree")
    architecture_packet = _architecture_packet(
        source_snapshot,
        max_chars=policy.max_input_chars,
        file_digest=file_digest,
    )
    prompts = _prompts(architecture_packet)
    authorization_prompts = _authorization_prompt_packets(prompts)
    prompt_manifest_digest = content_digest(
        {
            stage: content_digest({"prompt": authorization_prompts[stage]})
            for stage in PHASE2_STAGES
        }
    )
    run_identity = content_digest(
        {
            "task_id": TASK_ID,
            "task_revision": TASK_REVISION,
            "source_identity": source_identity,
            "policy_digest": policy.policy_digest,
            "prompt_manifest_digest": prompt_manifest_digest,
        }
    )
    authority = HostedRunAuthority(
        policy=policy,
        run_identity=run_identity,
        initial_predecessor_receipt_digest=_SEED_DIGEST,
        prompt_manifest=authorization_prompts,
    )
    if executor is None:
        if execute:
            run_claim = DurableRunClaim(
                _durable_claim_state_dir(),
                approval_scope_digest=_APPROVAL_SCOPE_DIGEST,
                run_identity=run_identity,
            )
            executor = HostedAgentsExecutor._for_production(
                authority=authority,
                run_claim=run_claim,
            )
        else:
            executor = HostedAgentsExecutor()
    elif execute:
        binder = getattr(executor, "bind_test_authority", None)
        if not callable(binder):
            raise HostedPhase2Error("test_executor_authority_binding_required")
        binder(authority)
    lookup = LocalSourceLookup(
        source_root,
        allowed_paths=(SOURCE_PATH,),
        max_chars=policy.max_input_chars,
        snapshot_contents={SOURCE_PATH: source_snapshot},
    )
    plans: list[HostedStagePlan] = []
    predecessor = _SEED_DIGEST
    for stage in PHASE2_STAGES:
        plan = _plan_for(
            stage,
            predecessor,
            executor,
            lookup,
            source_identity=source_identity,
            max_input_chars=policy.max_input_chars,
        )
        plans.append(plan)
        predecessor = content_digest({"stage": stage, "plan_digest": plan.plan_digest, "status": "PLANNED"})
    if not execute:
        rows = [_planned_row(plan) for plan in plans]
        return build_public_receipt(execution_mode="dry_run", stages=rows)
    rows, failure_digest = asyncio.run(
        _execute(
            executor=executor,
            policy=policy,
            lookup=lookup,
            source_identity=source_identity,
            prompts=prompts,
            authority=authority,
        )
    )
    return build_public_receipt(
        execution_mode="execute",
        stages=rows,
        failure_digest=failure_digest,
    )


def run_phase2(
    *,
    execute: bool = False,
    root: str | Path | None = None,
    policy: HostedPhase2Policy | None = None,
) -> dict[str, Any]:
    """Public production entry point with a fixed SDK executor.

    Execute mode is bound to this repository checkout and does not accept an
    injected executor. Tests use the private helper below.
    """

    if execute and root is not None:
        raise HostedPhase2Error("execute_root_override_forbidden")
    return _run_phase2(execute=execute, root=root, policy=policy)


def _run_phase2_for_test(
    *,
    execute: bool,
    executor: Any,
    root: str | Path | None = None,
    policy: HostedPhase2Policy | None = None,
) -> dict[str, Any]:
    return _run_phase2(
        execute=execute,
        executor=executor,
        root=root,
        policy=policy,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded hosted Phase 2 canary")
    parser.add_argument("--execute", action="store_true", help="consume the process API key and run hosted stages")
    args = parser.parse_args(argv)
    try:
        receipt = run_phase2(execute=args.execute)
    except Exception as exc:  # public CLI emits no exception text or private payload
        receipt = build_public_receipt(
            execution_mode="execute" if args.execute else "dry_run",
            stages=(),
            failure_digest=content_digest({"error_type": type(exc).__name__}),
        )
        print(json.dumps(receipt, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
