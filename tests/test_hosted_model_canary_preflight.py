"""Red contracts for the zero-network Hosted-Model Canary preflight."""

from __future__ import annotations

from dataclasses import replace

import pytest

from quantengine_public.agent_platform.hosted_canary import (
    HostedCanaryPolicy,
    HostedCanaryPreflightError,
    HostedCanaryRequest,
    preflight_hosted_canary,
)


def request() -> HostedCanaryRequest:
    return HostedCanaryRequest(
        task_id="TASKSYS-1317",
        task_revision="p2-1-v1",
        source_identity="1" * 64,
        context_digest="2" * 64,
        agent_graph_identity="3" * 64,
        model="pinned-model-for-contract-test",
        max_turns=2,
        max_output_tokens=512,
        timeout_seconds=60,
        trace_mode="disabled",
        evidence_mode="digest_only",
        tool_count=0,
        handoff_count=0,
    )


def policy() -> HostedCanaryPolicy:
    return HostedCanaryPolicy(
        allowed_models=("pinned-model-for-contract-test",),
        max_turns=2,
        max_output_tokens=512,
        max_timeout_seconds=60,
    )


def test_valid_preflight_is_identity_bound_but_network_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "os.getenv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("environment access forbidden")),
    )

    receipt = preflight_hosted_canary(request(), policy())

    assert receipt.verdict == "BLOCKED"
    assert receipt.reason == "NETWORK_EXECUTION_NOT_AUTHORIZED"
    assert receipt.execution_allowed is False
    assert receipt.network_attempted is False
    assert receipt.trace_mode == "disabled"
    assert receipt.evidence_mode == "digest_only"
    assert receipt.request_digest == request().request_digest
    assert len(receipt.policy_digest) == 64
    assert len(receipt.receipt_digest) == 64


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("network_execution_enabled", True, "network_execution_not_authorized"),
        ("hosted_trace_export_enabled", True, "hosted_trace_export_not_authorized"),
        ("tools_enabled", True, "hosted_canary_tools_not_authorized"),
        ("handoffs_enabled", True, "hosted_canary_handoffs_not_authorized"),
        ("evidence_mode", "raw", "evidence_mode_not_authorized"),
    ],
)
def test_policy_cannot_expand_p2_1_authority(field: str, value: object, reason: str) -> None:
    with pytest.raises(HostedCanaryPreflightError, match=reason):
        HostedCanaryPolicy(**{**policy().to_dict(include_digest=False), field: value})


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"model": "unapproved-model"}, "model_not_allowed"),
        ({"max_turns": 3}, "max_turns_exceeds_policy"),
        ({"max_output_tokens": 513}, "max_output_tokens_exceeds_policy"),
        ({"timeout_seconds": 61}, "timeout_exceeds_policy"),
        ({"trace_mode": "hosted"}, "trace_mode_not_authorized"),
        ({"evidence_mode": "raw"}, "evidence_mode_not_authorized"),
        ({"tool_count": 1}, "hosted_canary_tools_not_authorized"),
        ({"handoff_count": 1}, "hosted_canary_handoffs_not_authorized"),
    ],
)
def test_request_fails_closed_outside_exact_policy(change: dict[str, object], reason: str) -> None:
    with pytest.raises(HostedCanaryPreflightError, match=reason):
        preflight_hosted_canary(replace(request(), **change), policy())


def test_request_identity_covers_every_execution_bound() -> None:
    baseline = request()
    changes = (
        {"task_id": "TASKSYS-OTHER"},
        {"task_revision": "p2-1-v2"},
        {"source_identity": "4" * 64},
        {"context_digest": "5" * 64},
        {"agent_graph_identity": "6" * 64},
        {"model": "another-pinned-model"},
        {"max_turns": 1},
        {"max_output_tokens": 256},
        {"timeout_seconds": 30},
    )

    assert all(replace(baseline, **change).request_digest != baseline.request_digest for change in changes)


def test_public_receipt_contains_no_prompt_output_key_or_hosted_trace() -> None:
    receipt = preflight_hosted_canary(request(), policy()).to_dict()
    serialized = str(receipt).lower()

    assert "prompt" not in receipt
    assert "output" not in receipt
    assert "api_key" not in serialized
    assert "trace_id" not in receipt
    assert set(receipt) == {
        "schema_version",
        "task_id",
        "task_revision",
        "request_digest",
        "policy_digest",
        "model",
        "max_turns",
        "max_output_tokens",
        "timeout_seconds",
        "trace_mode",
        "evidence_mode",
        "verdict",
        "reason",
        "execution_allowed",
        "network_attempted",
        "receipt_digest",
    }


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"verdict": "PASS"}, "hosted_canary_verdict_invalid"),
        ({"reason": "AUTHORIZED"}, "hosted_canary_reason_invalid"),
        ({"execution_allowed": True}, "network_execution_not_authorized"),
        ({"network_attempted": True}, "network_attempted_invalid"),
        ({"trace_mode": "hosted"}, "trace_mode_not_authorized"),
        ({"evidence_mode": "raw"}, "evidence_mode_not_authorized"),
    ],
)
def test_blocked_receipt_cannot_be_forged(change: dict[str, object], reason: str) -> None:
    receipt = preflight_hosted_canary(request(), policy())

    with pytest.raises(HostedCanaryPreflightError, match=reason):
        replace(receipt, **change)
