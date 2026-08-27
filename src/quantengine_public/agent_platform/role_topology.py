"""Provider-neutral admission contract for the corrected native role topology.

The public repository validates evidence produced by external runtimes.  It
does not log into Codex, call Qwen Code, or turn Quality Shield into an Agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_STAGES = (
    "architecture",
    "test_author",
    "development",
    "test_verify",
    "ops",
    "quality",
)
STUDIO_QWEN_MODEL = "qwen3.8:27b-mxfp8"
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
    execution_head_before: str
    execution_head_after: str
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
        for name in ("execution_head_before", "execution_head_after"):
            if not isinstance(getattr(self, name), str) or not _GIT_SHA.fullmatch(getattr(self, name)):
                raise RoleTopologyError(f"{name} invalid")
        if self.execution_head_before != self.execution_head_after:
            raise RoleTopologyError("role must not create a commit")
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
            "execution_head_before": self.execution_head_before,
            "execution_head_after": self.execution_head_after,
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


@dataclass(frozen=True, slots=True)
class NativeRoleReleaseVerdict:
    """Deterministic, zero-authority decision over one exact native topology."""

    task_id: str
    source_identity: str
    topology_digest: str
    receipt_digests: tuple[str, ...]
    status: str = "PASS"
    controller: str = "deterministic-local"
    schema_version: str = "public_delivery.native_role_release.v1"
    authority: Mapping[str, bool] = field(
        default_factory=lambda: dict(_ZERO_AUTHORITY)
    )

    def __post_init__(self) -> None:
        if self.status != "PASS" or self.controller != "deterministic-local":
            raise RoleTopologyError("native release controller mismatch")
        if self.schema_version != "public_delivery.native_role_release.v1":
            raise RoleTopologyError("native release schema mismatch")
        if not _SHA256.fullmatch(self.source_identity) or not _SHA256.fullmatch(
            self.topology_digest
        ):
            raise RoleTopologyError("native release identity invalid")
        if len(self.receipt_digests) != len(_STAGES) or any(
            not _SHA256.fullmatch(value) for value in self.receipt_digests
        ):
            raise RoleTopologyError("native release receipts invalid")
        if dict(self.authority) != _ZERO_AUTHORITY:
            raise RoleTopologyError("native release authority injection")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "source_identity": self.source_identity,
            "topology_digest": self.topology_digest,
            "receipt_digests": list(self.receipt_digests),
            "status": self.status,
            "controller": self.controller,
            "authority": dict(self.authority),
        }

    @property
    def release_digest(self) -> str:
        return _digest(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "release_digest": self.release_digest}


def validate_native_role_topology(
    receipts: Sequence[NativeRoleReceipt | Mapping[str, Any]],
    *,
    expected_task_id: str,
    expected_source_identity: str,
    initial_input_digest: str,
    expected_qwen_model: str,
    expected_development_paths: Sequence[str],
    expected_context_digests: Mapping[str, str],
    expected_execution_heads: Mapping[str, str],
) -> RoleTopologyVerdict:
    """Admit exactly Terra -> Sol -> Qwen Code -> Sol -> Ops -> QS."""
    if not _SHA256.fullmatch(expected_source_identity):
        raise RoleTopologyError("expected source identity invalid")
    if not _SHA256.fullmatch(initial_input_digest):
        raise RoleTopologyError("initial input digest invalid")
    if expected_qwen_model != STUDIO_QWEN_MODEL:
        raise RoleTopologyError("expected Qwen model mismatch")
    development_paths = tuple(expected_development_paths)
    if not development_paths or len(set(development_paths)) != len(development_paths):
        raise RoleTopologyError("expected Development paths invalid")
    for value in development_paths:
        path = PurePosixPath(value)
        if (
            not isinstance(value, str)
            or not value
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] != "src"
        ):
            raise RoleTopologyError("expected Development paths invalid")
    if not isinstance(expected_context_digests, Mapping) or set(expected_context_digests) != set(_STAGES):
        raise RoleTopologyError("expected context digests must cover every stage")
    for stage, digest in expected_context_digests.items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise RoleTopologyError(f"expected context digest invalid: {stage}")
    if not isinstance(expected_execution_heads, Mapping) or set(expected_execution_heads) != set(_STAGES):
        raise RoleTopologyError("expected execution heads must cover every stage")
    for stage, head in expected_execution_heads.items():
        if not isinstance(head, str) or not _GIT_SHA.fullmatch(head):
            raise RoleTopologyError(f"expected execution head invalid: {stage}")
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
        if (
            item.execution_head_before != expected_execution_heads[item.stage]
            or item.execution_head_after != expected_execution_heads[item.stage]
        ):
            raise RoleTopologyError(f"execution head mismatch: {item.stage}")
        if dict(item.authority) != _ZERO_AUTHORITY:
            raise RoleTopologyError("authority injection")
        if item.input_digest != prior:
            raise RoleTopologyError("handoff digest mismatch")
        if item.status != "PASS":
            raise RoleTopologyError(f"stage not pass: {item.stage}")
        _validate_policy(
            item,
            expected_qwen_model=expected_qwen_model,
            expected_development_paths=development_paths,
        )
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
                "expected_qwen_model": expected_qwen_model,
                "expected_development_paths": list(development_paths),
                "expected_context_digests": dict(expected_context_digests),
                "expected_execution_heads": dict(expected_execution_heads),
                "receipt_digests": list(receipt_digests),
            }
        ),
        authority=dict(_ZERO_AUTHORITY),
    )


def derive_native_role_release(
    receipts: Sequence[NativeRoleReceipt | Mapping[str, Any]],
    *,
    expected_task_id: str,
    expected_source_identity: str,
    initial_input_digest: str,
    expected_qwen_model: str,
    expected_development_paths: Sequence[str],
    expected_context_digests: Mapping[str, str],
    expected_execution_heads: Mapping[str, str],
) -> NativeRoleReleaseVerdict:
    """Derive Release only after the exact six-stage native chain is admitted."""
    verdict = validate_native_role_topology(
        receipts,
        expected_task_id=expected_task_id,
        expected_source_identity=expected_source_identity,
        initial_input_digest=initial_input_digest,
        expected_qwen_model=expected_qwen_model,
        expected_development_paths=expected_development_paths,
        expected_context_digests=expected_context_digests,
        expected_execution_heads=expected_execution_heads,
    )
    return NativeRoleReleaseVerdict(
        task_id=expected_task_id,
        source_identity=expected_source_identity,
        topology_digest=verdict.topology_digest,
        receipt_digests=verdict.receipt_digests,
    )


def _validate_policy(
    receipt: NativeRoleReceipt,
    *,
    expected_qwen_model: str,
    expected_development_paths: Sequence[str],
) -> None:
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
        if any(path not in expected_development_paths for path in receipt.changed_paths):
            raise RoleTopologyError(
                "Development changed paths outside accepted allowlist"
            )
    elif receipt.changed_paths:
        raise RoleTopologyError(f"stage must not modify files: {receipt.stage}")


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "STUDIO_QWEN_MODEL",
    "NativeRoleReleaseVerdict",
    "NativeRoleReceipt",
    "RoleTopologyError",
    "RoleTopologyVerdict",
    "derive_native_role_release",
    "validate_native_role_topology",
]
