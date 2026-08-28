"""Offline verification for the owner-attested DEC-0031 native canary bundle.

The signature proves that the repository owner published the exact bundle.
It does not prove that Codex, Qwen Code, or Quality Shield signed a receipt.
Provider execution and bundle publication are intentionally separate claims.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .role_topology import (
    NativeRoleReceipt,
    RoleTopologyError,
    validate_native_role_topology,
)


MANIFEST_FILE = "native-role-canary-manifest.json"
SIGNATURE_FILE = f"{MANIFEST_FILE}.sig"
ALLOWED_SIGNERS_FILE = "owner_allowed_signers"
MANIFEST_SCHEMA = "public_delivery.native_role_canary_manifest.v1"
VERIFICATION_SCHEMA = "public_delivery.native_role_canary_verification.v1"
EVIDENCE_CLASS = "retrospective_operator_attestation"
OWNER_IDENTITY = "derrick.xu84@gmail.com"
SIGNATURE_NAMESPACE = "evidence-controlled-ai-delivery"
OWNER_KEY_FINGERPRINT = "SHA256:qBZ5C+UCkE2zP0dMCwEQBL23/dt/yPYUI2coTfAzV1I"
OWNER_ALLOWED_SIGNERS_SHA256 = "3ec2deda3c10370ce770b23b0a5f5183023339a02cbc560efce7d653ceb685cc"

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
_EXPECTED_TRUST = {
    "operator_attested": True,
    "provider_signed": False,
    "continuous_native_run": False,
    "independently_replayable_provider_execution": False,
    "owner_identity": OWNER_IDENTITY,
    "signer_key_fingerprint": OWNER_KEY_FINGERPRINT,
    "signature_namespace": SIGNATURE_NAMESPACE,
    "signature_file": SIGNATURE_FILE,
    "allowed_signers_file": ALLOWED_SIGNERS_FILE,
    "statement": (
        "The owner signature authenticates publication and byte integrity only; "
        "the providers did not sign these retrospective canary records."
    ),
}
_MANIFEST_KEYS = {
    "schema_version",
    "evidence_class",
    "task_id",
    "source_artifact",
    "source_identity",
    "request_artifact",
    "initial_input_digest",
    "expected_qwen_model",
    "expected_development_paths",
    "expected_context_digests",
    "expected_execution_heads",
    "stage_artifacts",
    "receipts",
    "artifacts",
    "trust",
    "authority",
    "manifest_digest",
}


class NativeCanaryError(ValueError):
    """Raised when the published native canary bundle fails closed."""


def verify_native_canary_bundle(
    bundle_dir: Path,
    *,
    ssh_keygen: str = "ssh-keygen",
) -> dict[str, Any]:
    """Verify the pinned owner key, SSH signature, bytes, and role topology."""
    root = bundle_dir.resolve()
    manifest_path = _fixed_file(root, MANIFEST_FILE)
    signature_path = _fixed_file(root, SIGNATURE_FILE)
    allowed_signers_path = _fixed_file(root, ALLOWED_SIGNERS_FILE)
    manifest_bytes = manifest_path.read_bytes()
    allowed_signers_bytes = allowed_signers_path.read_bytes()
    if _sha256(allowed_signers_bytes) != OWNER_ALLOWED_SIGNERS_SHA256:
        raise NativeCanaryError("owner trust root mismatch")
    _verify_owner_signature(
        manifest_bytes,
        signature_path=signature_path,
        allowed_signers_path=allowed_signers_path,
        ssh_keygen=ssh_keygen,
    )
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise NativeCanaryError("native canary manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise NativeCanaryError("native canary manifest must be an object")
    result = validate_native_canary_manifest(manifest, bundle_dir=root)
    result["schema_version"] = VERIFICATION_SCHEMA
    result["status"] = "PASS"
    result["owner_attested"] = True
    return result


def validate_native_canary_manifest(
    manifest: Mapping[str, Any],
    *,
    bundle_dir: Path,
) -> dict[str, Any]:
    """Validate bundle semantics without claiming signature authentication."""
    data = dict(manifest)
    if set(data) != _MANIFEST_KEYS:
        raise NativeCanaryError("native canary manifest shape mismatch")
    if data["schema_version"] != MANIFEST_SCHEMA:
        raise NativeCanaryError("native canary schema mismatch")
    if data["evidence_class"] != EVIDENCE_CLASS:
        raise NativeCanaryError("native canary evidence class mismatch")
    if data["trust"] != _EXPECTED_TRUST:
        raise NativeCanaryError("native canary trust boundary mismatch")
    if data["authority"] != _ZERO_AUTHORITY:
        raise NativeCanaryError("native canary authority must remain zero")
    supplied_digest = data["manifest_digest"]
    unsigned_body = {key: value for key, value in data.items() if key != "manifest_digest"}
    if not isinstance(supplied_digest, str) or supplied_digest != _canonical_digest(unsigned_body):
        raise NativeCanaryError("native canary manifest digest mismatch")

    artifact_hashes = _verify_artifacts(data["artifacts"], bundle_dir.resolve())
    source_artifact = _required_artifact_path(data["source_artifact"])
    request_artifact = _required_artifact_path(data["request_artifact"])
    if data["source_identity"] != artifact_hashes.get(source_artifact):
        raise NativeCanaryError("native canary source identity is not artifact-bound")
    if data["initial_input_digest"] != artifact_hashes.get(request_artifact):
        raise NativeCanaryError("native canary initial input is not artifact-bound")

    stage_artifacts = data["stage_artifacts"]
    if not isinstance(stage_artifacts, dict) or set(stage_artifacts) != set(_STAGES):
        raise NativeCanaryError("native canary stage artifacts must cover the exact topology")
    contexts: dict[str, str] = {}
    outputs: dict[str, str] = {}
    expected_artifacts = {source_artifact, request_artifact}
    for stage in _STAGES:
        value = stage_artifacts[stage]
        if not isinstance(value, dict) or set(value) != {"context", "output"}:
            raise NativeCanaryError(f"native canary stage artifact shape mismatch: {stage}")
        context_path = _required_artifact_path(value["context"])
        output_path = _required_artifact_path(value["output"])
        if context_path not in artifact_hashes or output_path not in artifact_hashes:
            raise NativeCanaryError(f"native canary stage artifact missing: {stage}")
        contexts[stage] = artifact_hashes[context_path]
        outputs[stage] = artifact_hashes[output_path]
        expected_artifacts.update((context_path, output_path))
    if set(artifact_hashes) != expected_artifacts:
        raise NativeCanaryError("native canary artifact inventory mismatch")
    if data["expected_context_digests"] != contexts:
        raise NativeCanaryError("native canary context digest mismatch")

    receipts_value = data["receipts"]
    if not isinstance(receipts_value, list) or len(receipts_value) != len(_STAGES):
        raise NativeCanaryError("native canary must contain exactly six receipts")
    try:
        receipts = tuple(NativeRoleReceipt.from_dict(value) for value in receipts_value)
        for receipt in receipts:
            if receipt.output_digest != outputs[receipt.stage]:
                raise NativeCanaryError(
                    f"native canary output digest is not artifact-bound: {receipt.stage}"
                )
        topology = validate_native_role_topology(
            receipts,
            expected_task_id=data["task_id"],
            expected_source_identity=data["source_identity"],
            initial_input_digest=data["initial_input_digest"],
            expected_qwen_model=data["expected_qwen_model"],
            expected_development_paths=data["expected_development_paths"],
            expected_context_digests=data["expected_context_digests"],
            expected_execution_heads=data["expected_execution_heads"],
        )
    except (RoleTopologyError, KeyError, TypeError) as exc:
        raise NativeCanaryError(f"native canary topology rejected: {exc}") from exc

    return {
        "schema_version": "public_delivery.native_role_canary_semantic_validation.v1",
        "status": "SEMANTIC_PASS",
        "manifest_digest": supplied_digest,
        "topology_digest": topology.topology_digest,
        "owner_attested": False,
        "provider_signed": False,
        "continuous_native_run": False,
        "independently_replayable_provider_execution": False,
        "authority": dict(_ZERO_AUTHORITY),
    }


def canonical_manifest_digest(manifest_without_digest: Mapping[str, Any]) -> str:
    """Return the v1 canonical digest used before the owner signs the file."""
    return _canonical_digest(dict(manifest_without_digest))


def _verify_artifacts(value: Any, root: Path) -> dict[str, str]:
    if not isinstance(value, list) or not value:
        raise NativeCanaryError("native canary artifacts must be a non-empty list")
    observed: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise NativeCanaryError("native canary artifact shape mismatch")
        relative = _required_artifact_path(item["path"])
        expected = item["sha256"]
        if relative in observed or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise NativeCanaryError("native canary artifact identity invalid")
        path = _relative_file(root, relative)
        actual = _sha256(path.read_bytes())
        if actual != expected:
            raise NativeCanaryError(f"native canary artifact digest mismatch: {relative}")
        observed[relative] = actual
    return observed


def _required_artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise NativeCanaryError("native canary artifact path required")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise NativeCanaryError("native canary artifact path escapes bundle")
    return value


def _fixed_file(root: Path, name: str) -> Path:
    return _relative_file(root, name)


def _relative_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise NativeCanaryError(f"native canary file unavailable or unsafe: {relative}")
    return path


def _verify_owner_signature(
    manifest_bytes: bytes,
    *,
    signature_path: Path,
    allowed_signers_path: Path,
    ssh_keygen: str,
) -> None:
    executable = shutil.which(ssh_keygen)
    if executable is None:
        raise NativeCanaryError("ssh-keygen is required for owner signature verification")
    completed = subprocess.run(
        (
            executable,
            "-Y",
            "verify",
            "-f",
            str(allowed_signers_path),
            "-I",
            OWNER_IDENTITY,
            "-n",
            SIGNATURE_NAMESPACE,
            "-s",
            str(signature_path),
        ),
        input=manifest_bytes,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise NativeCanaryError("owner signature verification failed")


def _canonical_digest(value: Mapping[str, Any]) -> str:
    return _sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
