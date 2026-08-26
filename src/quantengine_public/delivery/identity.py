from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


ARTIFACT_SCHEMA_VERSION = "quantengine_public.delivery_artifact.v1"
CLOSED_STATUSES = {
    "READY",
    "PASS",
    "BLOCKED",
    "EVIDENCE_GAP",
    "FAIL_CLOSED",
    "RECORDED",
    "REVISION_REQUIRED",
}
AUTHORITY_KEYS = {
    "deployment_allowed",
    "paper_allowed",
    "real_allowed",
}
ARTIFACT_PRODUCERS: dict[str, set[str]] = {
    "public_delivery.ogsm": {"owner_fixture"},
    "public_delivery.plane_task": {"public_plane_fixture"},
    "public_delivery.architecture_packet": {"public_architecture_agent"},
    "public_delivery.validation_plan": {"public_test_agent"},
    "public_delivery.worker_handoff": {"public_control_plane"},
    "public_delivery.patch_manifest": {"public_development_agent"},
    "public_delivery.test_result": {"public_test_agent"},
    "public_delivery.ops_plan": {"public_ops_agent"},
    "public_delivery.runtime_evidence": {"quantengine_public"},
    "public_delivery.qcs_manifest": {"public_qcs"},
    "public_delivery.qcs_receipt": {"public_qcs"},
    "public_delivery.quality_verdict": {"public_quality_shield"},
    "public_delivery.release_verdict": {"public_release_controller"},
    "public_delivery.aar": {"public_learning_flywheel"},
    "public_delivery.block_receipt": {
        "owner_fixture",
        "public_architecture_agent",
        "public_development_agent",
        "public_test_agent",
        "public_ops_agent",
        "public_qcs",
        "public_quality_shield",
        "quantengine_public",
        "public_release_controller",
    },
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_KEYS = {
    "schema_version",
    "artifact_type",
    "producer",
    "status",
    "upstream",
    "payload",
    "authority",
    "artifact_digest",
}


class ArtifactContractError(ValueError):
    """Raised when a public delivery artifact cannot satisfy the closed contract."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for content addressing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    """Return a SHA-256 digest over canonical JSON."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def artifact_ref(artifact: dict[str, Any]) -> dict[str, str]:
    """Create the only accepted cross-artifact identity edge."""
    errors = verify_artifact(artifact)
    if errors:
        raise ArtifactContractError(f"invalid_upstream_artifact:{','.join(errors)}")
    return {
        "artifact_type": artifact["artifact_type"],
        "artifact_digest": artifact["artifact_digest"],
    }


def seal_artifact(
    *,
    artifact_type: str,
    producer: str,
    status: str,
    upstream: list[dict[str, str]],
    payload: dict[str, Any],
    authority: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Validate and seal one public delivery artifact."""
    if not artifact_type or not isinstance(artifact_type, str):
        raise ArtifactContractError("invalid_artifact_type")
    if not producer or not isinstance(producer, str):
        raise ArtifactContractError("invalid_producer")
    if status not in CLOSED_STATUSES:
        raise ArtifactContractError(f"unsupported_status:{status}")
    if not isinstance(payload, dict):
        raise ArtifactContractError("invalid_payload")
    if not isinstance(upstream, list) or any(not _valid_upstream(item) for item in upstream):
        raise ArtifactContractError("invalid_upstream")

    resolved_authority = authority or {
        "deployment_allowed": False,
        "paper_allowed": False,
        "real_allowed": False,
    }
    if not _valid_authority(resolved_authority):
        raise ArtifactContractError("invalid_authority")
    if not _valid_authority_semantics(artifact_type, status, resolved_authority):
        raise ArtifactContractError("invalid_authority_semantics")

    artifact: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "producer": producer,
        "status": status,
        "upstream": deepcopy(upstream),
        "payload": deepcopy(payload),
        "authority": deepcopy(resolved_authority),
    }
    artifact["artifact_digest"] = content_digest(artifact)
    return artifact


def verify_artifact(artifact: dict[str, Any]) -> list[str]:
    """Verify shape, closed values, upstream identities, and self digest."""
    if not isinstance(artifact, dict):
        return ["artifact_not_object"]

    errors: list[str] = []
    if set(artifact) != _ARTIFACT_KEYS:
        errors.append("artifact_fields_not_closed")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if not isinstance(artifact.get("artifact_type"), str) or not artifact.get("artifact_type"):
        errors.append("invalid_artifact_type")
    if not isinstance(artifact.get("producer"), str) or not artifact.get("producer"):
        errors.append("invalid_producer")
    if artifact.get("status") not in CLOSED_STATUSES:
        errors.append("unsupported_status")
    if not isinstance(artifact.get("payload"), dict):
        errors.append("invalid_payload")
    upstream = artifact.get("upstream")
    if not isinstance(upstream, list) or any(not _valid_upstream(item) for item in upstream):
        errors.append("invalid_upstream")
    if not _valid_authority(artifact.get("authority")):
        errors.append("invalid_authority")
    elif not _valid_authority_semantics(
        artifact.get("artifact_type"),
        artifact.get("status"),
        artifact["authority"],
    ):
        errors.append("invalid_authority_semantics")

    declared_digest = artifact.get("artifact_digest")
    if not isinstance(declared_digest, str) or not _SHA256_RE.fullmatch(declared_digest):
        errors.append("invalid_artifact_digest")
    else:
        material = {key: deepcopy(value) for key, value in artifact.items() if key != "artifact_digest"}
        if content_digest(material) != declared_digest:
            errors.append("artifact_digest_mismatch")
    return errors


def verify_artifact_chain(artifacts: list[dict[str, Any]]) -> list[str]:
    """Verify producer ownership and that every upstream digest already exists."""
    if not isinstance(artifacts, list):
        return ["artifact_chain_not_list"]

    errors: list[str] = []
    known_artifacts: dict[str, str] = {}
    for artifact in artifacts:
        artifact_errors = verify_artifact(artifact)
        if artifact_errors:
            errors.extend(f"invalid_artifact:{error}" for error in artifact_errors)
            continue

        artifact_type = artifact["artifact_type"]
        producer = artifact["producer"]
        allowed_producers = ARTIFACT_PRODUCERS.get(artifact_type)
        if allowed_producers is None:
            errors.append(f"unknown_artifact_type:{artifact_type}")
        elif producer not in allowed_producers:
            errors.append(f"producer_mismatch:{artifact_type}:{producer}")

        digest = artifact["artifact_digest"]
        if digest in known_artifacts:
            errors.append(f"duplicate_artifact_digest:{digest}")
        for edge in artifact["upstream"]:
            upstream_type = known_artifacts.get(edge["artifact_digest"])
            if upstream_type is None:
                errors.append(
                    f"unknown_upstream:{artifact_type}:{edge['artifact_digest']}"
                )
            elif upstream_type != edge["artifact_type"]:
                errors.append(
                    "upstream_type_mismatch:"
                    f"{artifact_type}:{edge['artifact_type']}:{upstream_type}:"
                    f"{edge['artifact_digest']}"
                )
        known_artifacts[digest] = artifact_type
    return errors


def _valid_upstream(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"artifact_type", "artifact_digest"}
        and isinstance(value.get("artifact_type"), str)
        and bool(value.get("artifact_type"))
        and isinstance(value.get("artifact_digest"), str)
        and bool(_SHA256_RE.fullmatch(value["artifact_digest"]))
    )


def _valid_authority(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == AUTHORITY_KEYS
        and all(isinstance(value[key], bool) for key in AUTHORITY_KEYS)
    )


def _valid_authority_semantics(
    artifact_type: Any,
    status: Any,
    authority: dict[str, bool],
) -> bool:
    if not any(authority.values()):
        return True
    return artifact_type == "public_delivery.release_verdict" and status == "PASS"
