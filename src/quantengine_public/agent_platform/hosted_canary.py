"""Fail-closed preflight for a future hosted-model architecture canary.

This module deliberately has no environment, network, or Agents SDK access. It
only binds an approved request to a closed policy and emits a digest-only
receipt that keeps execution blocked until a later authority is implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .contracts import content_digest


SCHEMA_VERSION = "quantengine_public.agent_platform.hosted_canary.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HostedCanaryPreflightError(ValueError):
    """Raised when a hosted-canary request exceeds the P2-1 authority."""


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostedCanaryPreflightError(f"{name}_required")
    return value


def _required_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise HostedCanaryPreflightError(f"{name}_invalid")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HostedCanaryPreflightError(f"{name}_invalid")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HostedCanaryPreflightError(f"{name}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class HostedCanaryRequest:
    """Identity-bound inputs proposed for one future hosted-model request."""

    task_id: str
    task_revision: str
    source_identity: str
    context_digest: str
    agent_graph_identity: str
    model: str
    max_turns: int
    max_output_tokens: int
    timeout_seconds: int
    trace_mode: str
    evidence_mode: str
    tool_count: int
    handoff_count: int

    def __post_init__(self) -> None:
        _required_text(self.task_id, "task_id")
        _required_text(self.task_revision, "task_revision")
        _required_digest(self.source_identity, "source_identity")
        _required_digest(self.context_digest, "context_digest")
        _required_digest(self.agent_graph_identity, "agent_graph_identity")
        _required_text(self.model, "model")
        _positive_int(self.max_turns, "max_turns")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        _positive_int(self.timeout_seconds, "timeout_seconds")
        _required_text(self.trace_mode, "trace_mode")
        _required_text(self.evidence_mode, "evidence_mode")
        _nonnegative_int(self.tool_count, "tool_count")
        _nonnegative_int(self.handoff_count, "handoff_count")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "agent_graph_identity": self.agent_graph_identity,
            "model": self.model,
            "max_turns": self.max_turns,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "trace_mode": self.trace_mode,
            "evidence_mode": self.evidence_mode,
            "tool_count": self.tool_count,
            "handoff_count": self.handoff_count,
        }

    @property
    def request_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        body = self._body()
        if include_digest:
            body["request_digest"] = self.request_digest
        return body


@dataclass(frozen=True, slots=True)
class HostedCanaryPolicy:
    """Closed P2-1 limits; authority-expanding values are invalid by design."""

    allowed_models: tuple[str, ...]
    max_turns: int
    max_output_tokens: int
    max_timeout_seconds: int
    network_execution_enabled: bool = False
    hosted_trace_export_enabled: bool = False
    tools_enabled: bool = False
    handoffs_enabled: bool = False
    evidence_mode: str = "digest_only"

    def __post_init__(self) -> None:
        if isinstance(self.allowed_models, (str, bytes)) or not isinstance(
            self.allowed_models, (list, tuple)
        ):
            raise HostedCanaryPreflightError("allowed_models_invalid")
        normalized = tuple(_required_text(model, "allowed_model") for model in self.allowed_models)
        if not normalized or len(set(normalized)) != len(normalized):
            raise HostedCanaryPreflightError("allowed_models_invalid")
        object.__setattr__(self, "allowed_models", normalized)
        _positive_int(self.max_turns, "max_turns")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        _positive_int(self.max_timeout_seconds, "max_timeout_seconds")
        if self.network_execution_enabled is not False:
            raise HostedCanaryPreflightError("network_execution_not_authorized")
        if self.hosted_trace_export_enabled is not False:
            raise HostedCanaryPreflightError("hosted_trace_export_not_authorized")
        if self.tools_enabled is not False:
            raise HostedCanaryPreflightError("hosted_canary_tools_not_authorized")
        if self.handoffs_enabled is not False:
            raise HostedCanaryPreflightError("hosted_canary_handoffs_not_authorized")
        if self.evidence_mode != "digest_only":
            raise HostedCanaryPreflightError("evidence_mode_not_authorized")

    def _body(self) -> dict[str, Any]:
        return {
            "allowed_models": list(self.allowed_models),
            "max_turns": self.max_turns,
            "max_output_tokens": self.max_output_tokens,
            "max_timeout_seconds": self.max_timeout_seconds,
            "network_execution_enabled": self.network_execution_enabled,
            "hosted_trace_export_enabled": self.hosted_trace_export_enabled,
            "tools_enabled": self.tools_enabled,
            "handoffs_enabled": self.handoffs_enabled,
            "evidence_mode": self.evidence_mode,
        }

    @property
    def policy_digest(self) -> str:
        return content_digest({"schema_version": SCHEMA_VERSION, **self._body()})

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        body = self._body()
        if include_digest:
            return {
                "schema_version": SCHEMA_VERSION,
                **body,
                "policy_digest": self.policy_digest,
            }
        return body


@dataclass(frozen=True, slots=True)
class HostedCanaryPreflightReceipt:
    """Public, digest-only evidence that the P2-1 preflight stayed blocked."""

    task_id: str
    task_revision: str
    request_digest: str
    policy_digest: str
    model: str
    max_turns: int
    max_output_tokens: int
    timeout_seconds: int
    trace_mode: str
    evidence_mode: str
    verdict: str = "BLOCKED"
    reason: str = "NETWORK_EXECUTION_NOT_AUTHORIZED"
    execution_allowed: bool = False
    network_attempted: bool = False

    def __post_init__(self) -> None:
        _required_text(self.task_id, "task_id")
        _required_text(self.task_revision, "task_revision")
        _required_digest(self.request_digest, "request_digest")
        _required_digest(self.policy_digest, "policy_digest")
        _required_text(self.model, "model")
        _positive_int(self.max_turns, "max_turns")
        _positive_int(self.max_output_tokens, "max_output_tokens")
        _positive_int(self.timeout_seconds, "timeout_seconds")
        if self.trace_mode != "disabled":
            raise HostedCanaryPreflightError("trace_mode_not_authorized")
        if self.evidence_mode != "digest_only":
            raise HostedCanaryPreflightError("evidence_mode_not_authorized")
        if self.verdict != "BLOCKED":
            raise HostedCanaryPreflightError("hosted_canary_verdict_invalid")
        if self.reason != "NETWORK_EXECUTION_NOT_AUTHORIZED":
            raise HostedCanaryPreflightError("hosted_canary_reason_invalid")
        if self.execution_allowed is not False:
            raise HostedCanaryPreflightError("network_execution_not_authorized")
        if self.network_attempted is not False:
            raise HostedCanaryPreflightError("network_attempted_invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "request_digest": self.request_digest,
            "policy_digest": self.policy_digest,
            "model": self.model,
            "max_turns": self.max_turns,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "trace_mode": self.trace_mode,
            "evidence_mode": self.evidence_mode,
            "verdict": self.verdict,
            "reason": self.reason,
            "execution_allowed": self.execution_allowed,
            "network_attempted": self.network_attempted,
        }

    @property
    def receipt_digest(self) -> str:
        return content_digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}


def preflight_hosted_canary(
    request: HostedCanaryRequest,
    policy: HostedCanaryPolicy,
) -> HostedCanaryPreflightReceipt:
    """Validate exact P2-1 bounds and return a deliberately blocked receipt."""

    if not isinstance(request, HostedCanaryRequest):
        raise HostedCanaryPreflightError("request_invalid")
    if not isinstance(policy, HostedCanaryPolicy):
        raise HostedCanaryPreflightError("policy_invalid")
    if request.model not in policy.allowed_models:
        raise HostedCanaryPreflightError("model_not_allowed")
    if request.max_turns > policy.max_turns:
        raise HostedCanaryPreflightError("max_turns_exceeds_policy")
    if request.max_output_tokens > policy.max_output_tokens:
        raise HostedCanaryPreflightError("max_output_tokens_exceeds_policy")
    if request.timeout_seconds > policy.max_timeout_seconds:
        raise HostedCanaryPreflightError("timeout_exceeds_policy")
    if request.trace_mode != "disabled":
        raise HostedCanaryPreflightError("trace_mode_not_authorized")
    if request.evidence_mode != policy.evidence_mode:
        raise HostedCanaryPreflightError("evidence_mode_not_authorized")
    if request.tool_count != 0:
        raise HostedCanaryPreflightError("hosted_canary_tools_not_authorized")
    if request.handoff_count != 0:
        raise HostedCanaryPreflightError("hosted_canary_handoffs_not_authorized")

    return HostedCanaryPreflightReceipt(
        task_id=request.task_id,
        task_revision=request.task_revision,
        request_digest=request.request_digest,
        policy_digest=policy.policy_digest,
        model=request.model,
        max_turns=request.max_turns,
        max_output_tokens=request.max_output_tokens,
        timeout_seconds=request.timeout_seconds,
        trace_mode=request.trace_mode,
        evidence_mode=request.evidence_mode,
    )
