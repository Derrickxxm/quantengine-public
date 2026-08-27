from __future__ import annotations

from dataclasses import replace

import pytest

from quantengine_public.agent_platform.role_topology import (
    NativeRoleReceipt,
    RoleTopologyError,
    validate_native_role_topology,
)


ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}
EXPECTED_HEADS = {
    stage: "c" * 40
    for stage in (
        "architecture",
        "test_author",
        "development",
        "test_verify",
        "ops",
        "quality",
    )
}
EXPECTED_CONTEXTS = {
    stage: "b" * 64
    for stage in (
        "architecture",
        "test_author",
        "development",
        "test_verify",
        "ops",
        "quality",
    )
}


def _receipt(
    *,
    stage: str,
    role: str,
    runtime: str,
    model: str | None,
    input_digest: str,
    output_digit: str,
    changed_paths: tuple[str, ...] = (),
) -> NativeRoleReceipt:
    return NativeRoleReceipt(
        task_id="TASKSYS-1327",
        stage=stage,
        role=role,
        runtime=runtime,
        model=model,
        source_identity="a" * 64,
        context_digest="b" * 64,
        execution_head_before="c" * 40,
        execution_head_after="c" * 40,
        input_digest=input_digest,
        output_digest=output_digit * 64,
        changed_paths=changed_paths,
        status="PASS",
        authority=ZERO_AUTHORITY,
    )


def _topology() -> tuple[NativeRoleReceipt, ...]:
    source = "0" * 64
    architecture = _receipt(
        stage="architecture",
        role="Architecture",
        runtime="codex-cli-chatgpt-subscription",
        model="gpt-5.6-terra",
        input_digest=source,
        output_digit="1",
    )
    test_author = _receipt(
        stage="test_author",
        role="Test",
        runtime="codex-cli-chatgpt-subscription",
        model="gpt-5.6-sol",
        input_digest=architecture.output_digest,
        output_digit="2",
        changed_paths=("tests/agent_platform/test_runtime.py",),
    )
    development = _receipt(
        stage="development",
        role="Development",
        runtime="qwen-code-cli-studio-local",
        model="qwen2.7-coder-local",
        input_digest=test_author.output_digest,
        output_digit="3",
        changed_paths=("src/quantengine_public/agent_platform/runtime.py",),
    )
    test_verify = _receipt(
        stage="test_verify",
        role="Test",
        runtime="codex-cli-chatgpt-subscription",
        model="gpt-5.6-sol",
        input_digest=development.output_digest,
        output_digit="4",
    )
    ops = _receipt(
        stage="ops",
        role="Ops",
        runtime="deterministic-local",
        model=None,
        input_digest=test_verify.output_digest,
        output_digit="5",
    )
    quality = _receipt(
        stage="quality",
        role="Quality Shield",
        runtime="quality-shield.observe_delivery",
        model=None,
        input_digest=ops.output_digest,
        output_digit="6",
    )
    return architecture, test_author, development, test_verify, ops, quality


def test_corrected_native_role_topology_is_admitted() -> None:
    receipts = _topology()

    verdict = validate_native_role_topology(
        receipts,
        expected_task_id="TASKSYS-1327",
        expected_source_identity="a" * 64,
        initial_input_digest="0" * 64,
        expected_qwen_model="qwen2.7-coder-local",
        expected_context_digests=EXPECTED_CONTEXTS,
        expected_execution_heads=EXPECTED_HEADS,
    )

    assert verdict.status == "PASS"
    assert verdict.stages == (
        "architecture",
        "test_author",
        "development",
        "test_verify",
        "ops",
        "quality",
    )
    assert len(verdict.topology_digest) == 64
    assert verdict.authority == ZERO_AUTHORITY


@pytest.mark.parametrize(
    ("index", "field", "value", "reason"),
    (
        (0, "model", "qwen2.7-coder-local", "role policy mismatch"),
        (1, "model", "gpt-5.6-terra", "role policy mismatch"),
        (2, "runtime", "scripted-model", "role policy mismatch"),
        (4, "model", "gpt-5.6-sol", "role policy mismatch"),
        (5, "runtime", "agent", "role policy mismatch"),
    ),
)
def test_wrong_model_or_runtime_is_rejected(
    index: int, field: str, value: str, reason: str
) -> None:
    receipts = list(_topology())
    receipts[index] = replace(receipts[index], **{field: value})

    with pytest.raises(RoleTopologyError, match=reason):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )


def test_handoff_digest_and_authority_fail_closed() -> None:
    receipts = list(_topology())
    receipts[2] = replace(receipts[2], input_digest="f" * 64)
    with pytest.raises(RoleTopologyError, match="handoff digest mismatch"):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )

    receipts = list(_topology())
    receipts[5] = replace(
        receipts[5],
        authority={**ZERO_AUTHORITY, "deployment_allowed": True},
    )
    with pytest.raises(RoleTopologyError, match="authority injection"):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )


def test_role_filesystem_ownership_is_enforced() -> None:
    receipts = list(_topology())
    receipts[1] = replace(receipts[1], changed_paths=("src/runtime.py",))
    with pytest.raises(RoleTopologyError, match="Test may only author tests"):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )

    receipts = list(_topology())
    receipts[2] = replace(receipts[2], changed_paths=("tests/test_runtime.py",))
    with pytest.raises(RoleTopologyError, match="Development must not modify tests"):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )


def test_each_stage_is_bound_to_its_accepted_context_digest() -> None:
    receipts = list(_topology())
    receipts[2] = replace(receipts[2], context_digest="e" * 64)

    with pytest.raises(RoleTopologyError, match="context digest mismatch: development"):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )


def test_each_stage_is_bound_to_its_expected_execution_head() -> None:
    receipts = list(_topology())
    receipts[2] = replace(
        receipts[2],
        execution_head_before="d" * 40,
        execution_head_after="d" * 40,
    )

    with pytest.raises(RoleTopologyError, match="execution head mismatch: development"):
        validate_native_role_topology(
            receipts,
            expected_task_id="TASKSYS-1327",
            expected_source_identity="a" * 64,
            initial_input_digest="0" * 64,
            expected_qwen_model="qwen2.7-coder-local",
            expected_context_digests=EXPECTED_CONTEXTS,
            expected_execution_heads=EXPECTED_HEADS,
        )
