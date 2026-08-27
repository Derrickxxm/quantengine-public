from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import content_digest


DEFAULT_TOOLS: dict[str, frozenset[str]] = {
    "Architecture": frozenset({"read_task", "read_git", "read_graph", "read_contracts", "read_source"}),
    "Test": frozenset({"read_scope", "propose_test"}),
    "Development": frozenset({"read_source", "edit_approved_paths", "run_declared_tests"}),
    "Ops": frozenset({"build", "run_ci_checks", "hash_artifacts", "collect_readback"}),
    "Quality": frozenset({"read_closed_evidence", "run_declared_verification"}),
    "Release Controller": frozenset({"read_admitted_evidence"}),
}


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    role: str
    allowed_tools: frozenset[str]
    policy_version: str = "1"

    @classmethod
    def for_role(cls, role: str) -> ToolPolicy:
        try:
            tools = DEFAULT_TOOLS[role]
        except KeyError as exc:
            raise ValueError(f"unknown_role:{role}") from exc
        return cls(role=role, allowed_tools=tools)

    @property
    def policy_digest(self) -> str:
        return content_digest({"role": self.role, "allowed_tools": sorted(self.allowed_tools), "version": self.policy_version})

    def permits(self, tool_id: str) -> bool:
        return isinstance(tool_id, str) and tool_id in self.allowed_tools


@dataclass(frozen=True, slots=True)
class ToolCallReceipt:
    run_id: str
    role: str
    tool_id: str
    allowed: bool
    arguments_digest: str
    result_digest: str | None
    error_class: str | None
    authority_granted: bool = False
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.authority_granted is not False:
            raise ValueError("tool_receipt_authority_cannot_be_granted")
        object.__setattr__(self, "receipt_digest", content_digest(self._body()))

    def _body(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "tool_id": self.tool_id,
            "allowed": self.allowed,
            "arguments_digest": self.arguments_digest,
            "result_digest": self.result_digest,
            "error_class": self.error_class,
            "authority_granted": self.authority_granted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}


class ToolDeniedError(PermissionError):
    def __init__(self, receipt: ToolCallReceipt) -> None:
        self.receipt = receipt
        super().__init__(f"PERMISSION_DENIED:{receipt.role}:{receipt.tool_id}")


def record_tool_call(
    *,
    policy: ToolPolicy,
    run_id: str,
    tool_id: str,
    arguments: Any,
    result: Any = None,
) -> ToolCallReceipt:
    args_digest = content_digest(arguments)
    if not policy.permits(tool_id):
        receipt = ToolCallReceipt(
            run_id=run_id,
            role=policy.role,
            tool_id=tool_id,
            allowed=False,
            arguments_digest=args_digest,
            result_digest=None,
            error_class="PERMISSION_DENIED",
        )
        raise ToolDeniedError(receipt)
    return ToolCallReceipt(
        run_id=run_id,
        role=policy.role,
        tool_id=tool_id,
        allowed=True,
        arguments_digest=args_digest,
        result_digest=content_digest(result),
        error_class=None,
    )


__all__ = ["DEFAULT_TOOLS", "ToolCallReceipt", "ToolDeniedError", "ToolPolicy", "record_tool_call"]
