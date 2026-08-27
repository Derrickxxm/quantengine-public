#!/usr/bin/env python3
"""Run the DEC-0019 hardened local OpenAI-compatible Phase 2 simulation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quantengine_public.agent_platform.contracts import canonical_json, content_digest
from quantengine_public.agent_platform.hosted_phase2 import LocalSourceLookup
from quantengine_public.agent_platform.qwen_phase2_simulation import (
    LOCAL_SIMULATION_MODEL,
    LocalModelSimulationExecutor,
    LocalSimulationConfig,
)


SOURCE_PATH = "src/quantengine_public/agent_platform/hosted_canary.py"


def _source_snapshot(root: Path) -> tuple[str, str]:
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise ValueError("simulation_requires_clean_worktree")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = (root / SOURCE_PATH).read_text(encoding="utf-8")
    source_identity = content_digest(
        {
            "repository": "quantengine-public",
            "commit": commit,
            "source_path": SOURCE_PATH,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "dirty": False,
            "owner_decision": "DEC-0019",
            "track": "qwen-local-simulation",
        }
    )
    return source_identity, source


async def _run(base_url: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    source_identity, source = _source_snapshot(root)
    packet = (
        "PUBLIC SOURCE PACKET\n"
        f"relative_path={SOURCE_PATH}\n"
        "This is a read-only local simulation with no hosted, write, Release, "
        "deployment, or QuantEngine runtime authority.\nSOURCE:\n"
        + source[:12_000]
    )
    lookup = LocalSourceLookup(root, allowed_paths=(SOURCE_PATH,), max_chars=16_000)
    executor = LocalModelSimulationExecutor(LocalSimulationConfig(base_url=base_url))
    try:
        return await executor.execute(
            source_identity=source_identity,
            architecture_prompt=packet,
            readonly_prompt=(
                f"Call lookup_public_source exactly once with {SOURCE_PATH}; return facts, "
                "risks, and validation grounded only in that result."
            ),
            handoff_prompt=(
                "Architecture must hand this public validation request to Test. Test must "
                "return a PASS verdict only with concrete negative cases.\n" + packet[:6_000]
            ),
            development_prompt=(
                "Process this bounded read-only public hardening task as the assigned role. "
                "Architecture scopes it, Test defines checks, Development proposes only "
                "repository-relative paths, and Quality returns PASS only with evidence.\n"
                + packet[:2_000]
            ),
            lookup=lookup,
        )
    finally:
        await executor.close()


def _blocked(exc: Exception) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "quantengine_public.qwen_phase2_simulation.receipt.v2",
        "execution_mode": "local_simulation",
        "owner_decision": "DEC-0019",
        "provider": {
            "kind": "ollama-openai-compatible",
            "model": LOCAL_SIMULATION_MODEL,
            "transport_scope": "loopback",
        },
        "verdict": "BLOCKED",
        "failure_digest": content_digest({"error_type": type(exc).__name__}),
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
    failure_code = str(exc)
    if type(exc).__name__ == "LocalSimulationError" and failure_code.startswith("simulation_"):
        body["failure_code"] = failure_code
    body["receipt_digest"] = content_digest(body)
    return body


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:21434/v1")
    args = parser.parse_args(argv)
    try:
        receipt = asyncio.run(_run(args.base_url))
    except Exception as exc:  # public boundary keeps the raw error local
        print(canonical_json(_blocked(exc)))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
