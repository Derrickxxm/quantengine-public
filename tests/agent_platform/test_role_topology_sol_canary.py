from __future__ import annotations

from dataclasses import replace

import pytest

from quantengine_public.agent_platform.role_topology import (
    NativeRoleReceipt,
    RoleTopologyError,
    validate_native_role_topology,
)


TASK_ID = "TASKSYS-1327"
ACCEPTED_SOURCE_IDENTITY = "a" * 64
ACCEPTED_CONTEXT_DIGEST = "b" * 64
INITIAL_INPUT_DIGEST = "0" * 64
QWEN_MODEL = "qwen2.7-coder-local"
ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}
STAGE_POLICIES = (
    ("architecture", "Architecture", "codex-cli-chatgpt-subscription", "gpt-5.6-terra", ()),
    (
        "test_author",
        "Test",
        "codex-cli-chatgpt-subscription",
        "gpt-5.6-sol",
        ("tests/agent_platform/test_role_topology_sol_canary.py",),
    ),
    (
        "development",
        "Development",
        "qwen-code-cli-studio-local",
        QWEN_MODEL,
        ("src/quantengine_public/agent_platform/role_topology.py",),
    ),
    ("test_verify", "Test", "codex-cli-chatgpt-subscription", "gpt-5.6-sol", ()),
    ("ops", "Ops", "deterministic-local", None, ()),
    ("quality", "Quality Shield", "quality-shield.observe_delivery", None, ()),
)


def _accepted_contexts() -> dict[str, str]:
    return {stage: ACCEPTED_CONTEXT_DIGEST for stage, *_ in STAGE_POLICIES}


def _valid_receipts() -> tuple[NativeRoleReceipt, ...]:
    receipts = []
    input_digest = INITIAL_INPUT_DIGEST
    for index, (stage, role, runtime, model, changed_paths) in enumerate(
        STAGE_POLICIES, start=1
    ):
        output_digest = str(index) * 64
        receipts.append(
            NativeRoleReceipt(
                task_id=TASK_ID,
                stage=stage,
                role=role,
                runtime=runtime,
                model=model,
                source_identity=ACCEPTED_SOURCE_IDENTITY,
                context_digest=ACCEPTED_CONTEXT_DIGEST,
                input_digest=input_digest,
                output_digest=output_digest,
                changed_paths=changed_paths,
                status="PASS",
                authority=ZERO_AUTHORITY,
            )
        )
        input_digest = output_digest
    return tuple(receipts)


def _validate(
    receipts: tuple[NativeRoleReceipt, ...], expected_contexts: dict[str, str]
) -> None:
    validate_native_role_topology(
        receipts,
        expected_task_id=TASK_ID,
        expected_source_identity=ACCEPTED_SOURCE_IDENTITY,
        initial_input_digest=INITIAL_INPUT_DIGEST,
        expected_qwen_model=QWEN_MODEL,
        expected_context_digests=expected_contexts,
    )


def test_incomplete_accepted_context_map_is_rejected() -> None:
    incomplete_contexts = _accepted_contexts()
    incomplete_contexts.pop("quality")

    with pytest.raises(
        RoleTopologyError,
        match="expected context digests must cover every stage",
    ):
        _validate(_valid_receipts(), incomplete_contexts)


def test_receipt_context_different_from_accepted_stage_context_is_rejected() -> None:
    receipts = list(_valid_receipts())
    receipts[1] = replace(receipts[1], context_digest="f" * 64)

    with pytest.raises(RoleTopologyError, match="context digest mismatch: test_author"):
        _validate(tuple(receipts), _accepted_contexts())
