"""Provider-neutral admission contract for the corrected native role topology.

The public repository validates evidence produced by external runtimes.  It
does not log into Codex, call Qwen Code, or turn Quality Shield into an Agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGES = (
    "architecture",
    "test_author",
    "development",
    "test_verify",
    "ops",
    "quality",
)
_ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}


class RoleTopologyError(ValueError):
    """Raised when native execution evidence violates the accepted topology."""


@dataclass(frozen=True, slots=True)
class NativeRoleReceipt:
    task_id: str
    stage: str
    role: str
    runtime: str
    model: str | None
    source_identity: str
    context_digest: str
    input_digest: str
    output_digest: str
    changed_paths: tuple[str, ...]
    status: str
    authority: Mapping[str, bool]
    schema_version: str = "public_delivery.native_role_receipt.v1"

    def __post_init__(self) -> None:
        for name in ("task_id", "stage", "role", "runtime"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RoleTopologyError(f"{name} required")
        if self.stage not in _STAGES:
            raise RoleTopologyError("unsupported native role stage")
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise RoleTopologyError("model must be explicit or null")
        for name in ("source_identity", "context_digest", "input_digest", "output_digest"):
            if not isinstance(getattr(self, name), str) or not _SHA256.fullmatch(getattr(self, name)):
                raise RoleTopologyError(f"{name} invalid")
        paths = tuple(self.changed_paths)
        for value in paths:
            path = PurePosixPath(value)
            if not isinstance(value, str) or not value or path.is_absolute() or ".." in path.parts:
                raise RoleTopologyError("changed path invalid")
        object.__setattr__(self, "changed_paths", paths)
        if self.status not in {"PASS", "BLOCKED"}:
            raise RoleTopologyError("role status invalid")
        if set(self.authority) != set(_ZERO_AUTHORITY) or any(
            not isinstance(value, bool) for value in self.authority.values()
        ):
            raise RoleTopologyError("authority shape invalid")
        if self.schema_version != "public_delivery.native_role_receipt.v1":
            raise RoleTopologyError("schema version mismatch")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "stage": self.stage,
            "role": self.role,
            "runtime": self.runtime,
            "model": self.model,
            "source_identity": self.source_identity,
            "context_digest": self.context_digest,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "changed_paths": list(self.changed_paths),
            "status": self.status,
            "authority": dict(self.authority),
        }

    @property
    def receipt_digest(self) -> str:
        return _digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NativeRoleReceipt":
        data = dict(value)
        supplied = data.pop("receipt_digest", None)
        data["changed_paths"] = tuple(data.get("changed_paths", ()))
        result = cls(**data)
        if supplied is None or supplied != result.receipt_digest:
            raise RoleTopologyError("receipt digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class RoleTopologyVerdict:
    status: str
    stages: tuple[str, ...]
    receipt_digests: tuple[str, ...]
    topology_digest: str
    authority: Mapping[str, bool]


def validate_native_role_topology(
    receipts: Sequence[NativeRoleReceipt | Mapping[str, Any]],
    *,
    expected_task_id: str,
    expected_source_identity: str,
    initial_input_digest: str,
    expected_qwen_model: str,
    expected_context_digests: Mapping[str, str],
) -> RoleTopologyVerdict:
    """Admit exactly Terra -> Sol -> Qwen Code -> Sol -> Ops -> QS."""
    if not _SHA256.fullmatch(expected_source_identity):
        raise RoleTopologyError("expected source identity invalid")
    if not _SHA256.fullmatch(initial_input_digest):
        raise RoleTopologyError("initial input digest invalid")
    if not isinstance(expected_qwen_model, str) or not expected_qwen_model.strip():
        raise RoleTopologyError("expected Qwen model required")
    if not isinstance(expected_context_digests, Mapping) or set(expected_context_digests) != set(_STAGES):
        raise RoleTopologyError("expected context digests must cover every stage")
    for stage, digest in expected_context_digests.items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise RoleTopologyError(f"expected context digest invalid: {stage}")
    items = tuple(
        item if isinstance(item, NativeRoleReceipt) else NativeRoleReceipt.from_dict(item)
        for item in receipts
    )
    if tuple(item.stage for item in items) != _STAGES:
        raise RoleTopologyError("native role stage order mismatch")

    prior = initial_input_digest
    for item in items:
        if item.task_id != expected_task_id or item.source_identity != expected_source_identity:
            raise RoleTopologyError("task or source identity mismatch")
        if item.context_digest != expected_context_digests[item.stage]:
            raise RoleTopologyError(f"context digest mismatch: {item.stage}")
        if dict(item.authority) != _ZERO_AUTHORITY:
            raise RoleTopologyError("authority injection")
        if item.input_digest != prior:
            raise RoleTopologyError("handoff digest mismatch")
        if item.status != "PASS":
            raise RoleTopologyError(f"stage not pass: {item.stage}")
        _validate_policy(item, expected_qwen_model=expected_qwen_model)
        prior = item.output_digest

    receipt_digests = tuple(item.receipt_digest for item in items)
    return RoleTopologyVerdict(
        status="PASS",
        stages=_STAGES,
        receipt_digests=receipt_digests,
        topology_digest=_digest(
            {
                "schema_version": "public_delivery.native_role_topology.v1",
                "task_id": expected_task_id,
                "source_identity": expected_source_identity,
                "initial_input_digest": initial_input_digest,
                "expected_context_digests": dict(expected_context_digests),
                "receipt_digests": list(receipt_digests),
            }
        ),
        authority=dict(_ZERO_AUTHORITY),
    )


def _validate_policy(receipt: NativeRoleReceipt, *, expected_qwen_model: str) -> None:
    expected = {
        "architecture": ("Architecture", "codex-cli-chatgpt-subscription", "gpt-5.6-terra"),
        "test_author": ("Test", "codex-cli-chatgpt-subscription", "gpt-5.6-sol"),
        "development": ("Development", "qwen-code-cli-studio-local", expected_qwen_model),
        "test_verify": ("Test", "codex-cli-chatgpt-subscription", "gpt-5.6-sol"),
        "ops": ("Ops", "deterministic-local", None),
        "quality": ("Quality Shield", "quality-shield.observe_delivery", None),
    }[receipt.stage]
    if (receipt.role, receipt.runtime, receipt.model) != expected:
        raise RoleTopologyError(f"role policy mismatch: {receipt.stage}")

    if receipt.stage == "test_author":
        if not receipt.changed_paths or any(
            not path.startswith("tests/") for path in receipt.changed_paths
        ):
            raise RoleTopologyError("Test may only author tests")
    elif receipt.stage == "development":
        if not receipt.changed_paths:
            raise RoleTopologyError("Development requires an implementation change")
        if any(path.startswith("tests/") for path in receipt.changed_paths):
            raise RoleTopologyError("Development must not modify tests")
    elif receipt.changed_paths:
        raise RoleTopologyError(f"stage must not modify files: {receipt.stage}")


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "NativeRoleReceipt",
    "RoleTopologyError",
    "RoleTopologyVerdict",
    "validate_native_role_topology",
]
