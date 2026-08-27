"""Public-safe, identity-bound proof for the Native-Agent MVP.

The proof executes the existing OpenAI Agents SDK vertical slice with its
network-free ``ScriptedModel`` and then replays the deterministic M7 learning
closure.  This module adds no orchestration or runtime authority; it only
serializes inspectable receipts and verifies them from bytes.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from quantengine_public.delivery.identity import verify_artifact_chain

from .contracts import GraphIdentity, HandoffReceipt, SourceIdentity, TaskSnapshot, content_digest
from .learning import execute_learning_closure, verify_learning_closure
from .runtime import SDK_PACKAGE, SDK_REQUIRED_VERSION, SDK_VERSION
from .vertical_slice import SliceArtifact, VerticalSliceResult, VerticalSliceRunner, derive_release


PROOF_SCHEMA = "quantengine_public.agent_platform.public_proof.v1"
PROOF_FILES = (
    "source_identity.json",
    "graph_identity.json",
    "task_snapshot.json",
    "public_trace.json",
    "handoffs.json",
    "evidence.json",
    "release.json",
    "learning_evidence.json",
    "historical_regressions.json",
    "aar.json",
    "manifest.json",
)
_ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}
_FORBIDDEN_PUBLIC_TEXT = (
    "/Users/",
    "/home/",
    "OPENAI_API_KEY",
    "api_key",
    "private_adapters",
)


class PublicProofError(RuntimeError):
    """Raised when a generated public proof cannot be independently verified."""


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> str:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicProofError(f"invalid_json:{path.name}") from exc


def _task(source: SourceIdentity) -> TaskSnapshot:
    return TaskSnapshot(
        task_id="TASKSYS-1266",
        task_revision="m8-public-proof-v1",
        objective="publish an identity-bound Native-Agent MVP proof",
        measures=("bounded SDK slice", "M7 replay", "zero authority", "byte-verifiable proof"),
        acceptance_criteria=(
            "six role runs and handoffs",
            "exact-topology Release",
            "seven retained regressions",
            "independent promotion review",
        ),
        non_goals=("network model call", "deployment", "QuantEngine Replay", "Paper", "Real"),
        approved_scope=("quantengine_public.agent_platform", ".github/workflows/ci.yml", "public documentation"),
        required_approvals=("Owner:M8",),
        source_reference=source.identity_digest,
    )


def _public_trace(result: VerticalSliceResult) -> list[dict[str, str]]:
    return [
        {
            "result_digest": run.result_digest,
            "role": run.role,
            "run_id": run.run_id,
            "status": run.status,
            "stop_reason": run.stop_reason,
        }
        for run in result.runs
    ]


def generate_public_proof(
    output_dir: str | Path,
    *,
    repository: str,
    branch: str,
    commit: str,
    tree_digest: str,
    graph_revision: str,
    graph_digest: str,
) -> dict[str, Any]:
    """Execute the bounded MVP and write deterministic public proof files."""

    if SDK_VERSION != SDK_REQUIRED_VERSION:
        raise PublicProofError(
            f"sdk_version_mismatch:required={SDK_REQUIRED_VERSION}:installed={SDK_VERSION}"
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    unexpected = {path.name for path in output.iterdir()} - set(PROOF_FILES)
    if unexpected:
        raise PublicProofError("output_directory_not_empty:" + ",".join(sorted(unexpected)))

    source = SourceIdentity(repository, branch, commit, tree_digest)
    graph = GraphIdentity(graph_revision, source.commit, graph_digest)
    task = _task(source)
    with tempfile.TemporaryDirectory(prefix="qep-m8-public-proof-") as temporary:
        runner = VerticalSliceRunner(Path(temporary) / "vertical.sqlite3", task=task, source=source, graph=graph)
        try:
            import asyncio

            subject = asyncio.run(runner.run())
        finally:
            runner.close()

    learning_context_digest = content_digest(
        {
            "purpose": "M8 public proof and re-review",
            "task_id": task.task_id,
            "source_identity": source.identity_digest,
            "graph_identity": graph.identity_digest,
        }
    )
    learning = execute_learning_closure(
        subject=subject,
        learning_task_id=task.task_id,
        learning_source_identity=source.identity_digest,
        learning_graph_identity=graph.identity_digest,
        learning_context_digest=learning_context_digest,
        reviewer_identity="public-quality-reviewer@1",
    )

    values: dict[str, Any] = {
        "source_identity.json": source.to_dict(),
        "graph_identity.json": graph.to_dict(),
        "task_snapshot.json": task.to_dict(),
        "public_trace.json": _public_trace(subject),
        "handoffs.json": [handoff.to_dict() for handoff in subject.handoffs],
        "evidence.json": [artifact.to_dict() for artifact in subject.evidence],
        "release.json": dict(subject.release or {}),
        "learning_evidence.json": [artifact.to_dict() for artifact in learning.artifacts],
        "historical_regressions.json": [case.to_dict() for case in learning.replay_cases],
        "aar.json": learning.aar.to_dict(),
    }
    file_digests = {name: _write_json(output / name, value) for name, value in values.items()}
    release = SliceArtifact.from_dict(values["release.json"])
    body = {
        "schema_version": PROOF_SCHEMA,
        "task_id": task.task_id,
        "source_identity": source.identity_digest,
        "graph_identity": graph.identity_digest,
        "execution": {
            "mode": "bounded-ci-scripted-model",
            "network_model_calls": False,
            "sdk_package": SDK_PACKAGE,
            "sdk_version": SDK_REQUIRED_VERSION,
        },
        "authority": dict(_ZERO_AUTHORITY),
        "counts": {
            "roles": len(subject.runs),
            "handoffs": len(subject.handoffs),
            "vertical_evidence": len(subject.evidence),
            "learning_evidence": len(learning.artifacts),
            "historical_regressions": len(learning.replay_cases),
        },
        "release_ref": release.ref().to_dict(),
        "aar_ref": learning.aar.ref().to_dict(),
        "learning_identity": {
            "learning_task_id": task.task_id,
            "learning_source_identity": source.identity_digest,
            "learning_graph_identity": graph.identity_digest,
            "learning_context_digest": learning_context_digest,
            "reviewer_identity": "public-quality-reviewer@1",
        },
        "files": file_digests,
    }
    manifest = {**body, "proof_digest": content_digest(body)}
    _write_json(output / "manifest.json", manifest)
    return manifest


def verify_public_proof(
    output_dir: str | Path,
    *,
    expected_commit: str | None = None,
) -> dict[str, Any]:
    """Recompute every public proof binding and return the admitted manifest."""

    output = Path(output_dir)
    names = {path.name for path in output.iterdir()} if output.is_dir() else set()
    if names != set(PROOF_FILES):
        raise PublicProofError("proof_file_set_mismatch")
    manifest = _read_json(output / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != PROOF_SCHEMA:
        raise PublicProofError("manifest_schema_mismatch")
    body = {key: value for key, value in manifest.items() if key != "proof_digest"}
    if manifest.get("proof_digest") != content_digest(body):
        raise PublicProofError("proof_digest_mismatch")
    if manifest.get("authority") != _ZERO_AUTHORITY:
        raise PublicProofError("nonzero_authority")
    if manifest.get("execution") != {
        "mode": "bounded-ci-scripted-model",
        "network_model_calls": False,
        "sdk_package": SDK_PACKAGE,
        "sdk_version": SDK_REQUIRED_VERSION,
    }:
        raise PublicProofError("execution_identity_mismatch")

    expected_files = set(PROOF_FILES) - {"manifest.json"}
    if set(manifest.get("files", {})) != expected_files:
        raise PublicProofError("manifest_file_set_mismatch")
    for name, expected_digest in manifest["files"].items():
        observed = hashlib.sha256((output / name).read_bytes()).hexdigest()
        if observed != expected_digest:
            raise PublicProofError(f"file_digest_mismatch:{name}")

    for name in PROOF_FILES:
        serialized = (output / name).read_text(encoding="utf-8")
        if any(forbidden in serialized for forbidden in _FORBIDDEN_PUBLIC_TEXT):
            raise PublicProofError(f"public_safety_violation:{name}")

    source = SourceIdentity.from_dict(_read_json(output / "source_identity.json"))
    graph = GraphIdentity.from_dict(_read_json(output / "graph_identity.json"))
    task = TaskSnapshot.from_dict(_read_json(output / "task_snapshot.json"))
    if expected_commit is not None and source.commit != expected_commit:
        raise PublicProofError("source_commit_mismatch")
    if graph.source_commit != source.commit or task.source_reference != source.identity_digest:
        raise PublicProofError("source_graph_task_binding_mismatch")
    if manifest.get("source_identity") != source.identity_digest or manifest.get("graph_identity") != graph.identity_digest:
        raise PublicProofError("manifest_identity_mismatch")

    evidence = tuple(SliceArtifact.from_dict(value) for value in _read_json(output / "evidence.json"))
    release = SliceArtifact.from_dict(_read_json(output / "release.json"))
    chain_errors = verify_artifact_chain([item.to_dict() for item in (*evidence, release)])
    if chain_errors:
        raise PublicProofError("vertical_chain_invalid:" + ",".join(chain_errors))
    rederived = derive_release(
        task_id=task.task_id,
        source_identity=source.identity_digest,
        graph_identity=graph.identity_digest,
        evidence=evidence,
    )
    if rederived["artifact_digest"] != release.artifact_digest:
        raise PublicProofError("release_not_rederived")
    if release.authority != _ZERO_AUTHORITY or manifest.get("release_ref") != release.ref().to_dict():
        raise PublicProofError("release_binding_or_authority_mismatch")

    handoffs = tuple(HandoffReceipt.from_dict(value) for value in _read_json(output / "handoffs.json"))
    trace = _read_json(output / "public_trace.json")
    if len(trace) != 6 or len(handoffs) != 6:
        raise PublicProofError("run_or_handoff_count_mismatch")
    allowed_trace_keys = {"result_digest", "role", "run_id", "status", "stop_reason"}
    if any(not isinstance(entry, Mapping) or set(entry) != allowed_trace_keys for entry in trace):
        raise PublicProofError("public_trace_shape_mismatch")

    subject = VerticalSliceResult(task, source, graph, None, evidence, handoffs, (), release.to_dict())  # type: ignore[arg-type]
    learning_values = _read_json(output / "learning_evidence.json")
    learning_artifacts = tuple(SliceArtifact.from_dict(value) for value in learning_values)
    learning_identity = manifest.get("learning_identity")
    if not isinstance(learning_identity, Mapping):
        raise PublicProofError("learning_identity_missing")
    try:
        aar = verify_learning_closure(subject=subject, artifacts=learning_artifacts, **dict(learning_identity))
    except Exception as exc:
        raise PublicProofError(f"learning_closure_invalid:{exc}") from exc
    if _read_json(output / "aar.json") != aar.to_dict() or manifest.get("aar_ref") != aar.ref().to_dict():
        raise PublicProofError("aar_binding_mismatch")
    regressions = _read_json(output / "historical_regressions.json")
    if len(regressions) != 7 or any(item.get("status") != "PASS" for item in regressions):
        raise PublicProofError("historical_regression_mismatch")
    if any(any(artifact.authority.values()) for artifact in (*evidence, *learning_artifacts, release)):
        raise PublicProofError("upstream_nonzero_authority")
    return manifest


__all__ = ["PROOF_FILES", "PROOF_SCHEMA", "PublicProofError", "generate_public_proof", "verify_public_proof"]
