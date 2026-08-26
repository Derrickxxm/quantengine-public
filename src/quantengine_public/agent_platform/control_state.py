from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from quantengine_public.delivery.identity import verify_artifact, verify_artifact_chain

from .context import StaleContextError
from .contracts import ArtifactRef, HandoffReceipt, SourceIdentity, TaskSnapshot, content_digest

_DIGEST = re.compile(r"^[0-9a-f]{64}$")

TASK_STATES = (
    "DRAFT", "ACCEPTED", "CONTEXT_READY", "ARCHITECTURE_READY", "VALIDATION_READY",
    "IMPLEMENTATION_READY", "TEST_VERIFIED", "OPS_READY", "RUNTIME_VERIFIED",
    "QUALITY_REVIEWED", "RELEASE_DECIDED", "LEARNING_RECORDED", "CLOSED",
    "BLOCKED", "REVISION_REQUIRED", "HUMAN_APPROVAL_REQUIRED", "CANCELLED",
)
TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"ACCEPTED", "BLOCKED", "CANCELLED"}),
    "ACCEPTED": frozenset({"CONTEXT_READY", "BLOCKED", "CANCELLED"}),
    "CONTEXT_READY": frozenset({"ARCHITECTURE_READY", "BLOCKED", "CANCELLED"}),
    "ARCHITECTURE_READY": frozenset({"VALIDATION_READY", "BLOCKED", "REVISION_REQUIRED"}),
    "VALIDATION_READY": frozenset({"IMPLEMENTATION_READY", "BLOCKED", "REVISION_REQUIRED"}),
    "IMPLEMENTATION_READY": frozenset({"TEST_VERIFIED", "BLOCKED", "REVISION_REQUIRED"}),
    "TEST_VERIFIED": frozenset({"OPS_READY", "REVISION_REQUIRED", "BLOCKED"}),
    "OPS_READY": frozenset({"RUNTIME_VERIFIED", "REVISION_REQUIRED", "BLOCKED"}),
    "RUNTIME_VERIFIED": frozenset({"QUALITY_REVIEWED", "REVISION_REQUIRED", "BLOCKED"}),
    "QUALITY_REVIEWED": frozenset({"RELEASE_DECIDED", "REVISION_REQUIRED", "BLOCKED"}),
    "RELEASE_DECIDED": frozenset({"LEARNING_RECORDED", "BLOCKED"}),
    "LEARNING_RECORDED": frozenset({"CLOSED", "BLOCKED"}),
    "BLOCKED": frozenset({"DRAFT", "CONTEXT_READY", "REVISION_REQUIRED", "CANCELLED"}),
    "REVISION_REQUIRED": frozenset({"IMPLEMENTATION_READY", "VALIDATION_READY", "CONTEXT_READY", "CANCELLED"}),
    "HUMAN_APPROVAL_REQUIRED": frozenset({"ACCEPTED", "CANCELLED"}),
    "CANCELLED": frozenset(), "CLOSED": frozenset(),
}
REQUIRED_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "ARCHITECTURE_READY": ("public_delivery.architecture_packet", "READY", "public_architecture_agent"),
    "VALIDATION_READY": ("public_delivery.validation_plan", "READY", "public_test_agent"),
    "IMPLEMENTATION_READY": ("public_delivery.patch_manifest", "READY", "public_development_agent"),
    "TEST_VERIFIED": ("public_delivery.test_result", "PASS", "public_test_agent"),
    "OPS_READY": ("public_delivery.ops_plan", "READY", "public_ops_agent"),
    "RUNTIME_VERIFIED": ("public_delivery.runtime_evidence", "PASS", "quantengine_public"),
    "QUALITY_REVIEWED": ("public_delivery.quality_verdict", "PASS", "public_quality_shield"),
    "RELEASE_DECIDED": ("public_delivery.release_verdict", "PASS", "public_release_controller"),
}


class ControlStateError(RuntimeError):
    pass


class ConcurrentTransitionError(ControlStateError):
    pass


class InvalidTransitionError(ControlStateError):
    pass


@dataclass(frozen=True, slots=True)
class TaskState:
    task_id: str
    state: str
    version: int
    owner: str
    source_identity: str


@dataclass(frozen=True, slots=True)
class Transition:
    task_id: str
    idempotency_key: str
    from_state: str
    next_state: str
    version: int
    owner: str
    next_owner: str
    reason: str
    source_identity: str
    transition_digest: str
    evidence_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class AdmittedArtifact:
    artifact_type: str
    artifact_digest: str
    status: str
    producer: str
    task_id: str
    source_identity: str
    context_digest: str
    graph_identity: str


class ControlStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, snapshot_json TEXT NOT NULL, state TEXT NOT NULL,
                version INTEGER NOT NULL, owner TEXT NOT NULL, source_identity TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                idempotency_key TEXT NOT NULL, from_state TEXT NOT NULL, next_state TEXT NOT NULL,
                version INTEGER NOT NULL, owner TEXT NOT NULL, next_owner TEXT NOT NULL, reason TEXT NOT NULL,
                source_identity TEXT NOT NULL, transition_digest TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL DEFAULT '[]', UNIQUE(task_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_digest TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                artifact_type TEXT NOT NULL, status TEXT NOT NULL, producer TEXT NOT NULL,
                source_identity TEXT NOT NULL, context_digest TEXT NOT NULL, graph_identity TEXT NOT NULL,
                artifact_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS handoffs (
                receipt_digest TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                task_version INTEGER NOT NULL, from_owner TEXT NOT NULL, to_role TEXT NOT NULL,
                source_identity TEXT NOT NULL, context_digest TEXT NOT NULL,
                graph_identity TEXT NOT NULL DEFAULT '',
                required_artifact_refs_json TEXT NOT NULL, accepted_or_rejected TEXT NOT NULL,
                reason TEXT NOT NULL, next_owner TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, task_id TEXT, task_version INTEGER, source_identity TEXT,
                context_digest TEXT, status TEXT, payload_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tool_id TEXT, status TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY, task_id TEXT, run_id TEXT, owner TEXT, status TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(transitions)")}
        if "evidence_refs_json" not in columns:
            self._db.execute("ALTER TABLE transitions ADD COLUMN evidence_refs_json TEXT NOT NULL DEFAULT '[]'")
        handoff_columns = {row[1] for row in self._db.execute("PRAGMA table_info(handoffs)")}
        if "graph_identity" not in handoff_columns:
            self._db.execute("ALTER TABLE handoffs ADD COLUMN graph_identity TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def create_task(self, task: TaskSnapshot, source: SourceIdentity, *, owner: str) -> TaskState:
        if task.source_reference != source.identity_digest:
            raise StaleContextError("source_identity_mismatch")
        try:
            self._db.execute(
                "INSERT INTO tasks VALUES (?, ?, 'DRAFT', 0, ?, ?)",
                (task.task_id, json.dumps(task.to_dict(), sort_keys=True), owner, source.identity_digest),
            )
            self._db.commit()
        except sqlite3.IntegrityError as exc:
            raise ControlStateError(f"task_exists:{task.task_id}") from exc
        return self.get_task(task.task_id)

    def get_task(self, task_id: str) -> TaskState:
        row = self._db.execute(
            "SELECT task_id,state,version,owner,source_identity FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise ControlStateError(f"task_not_found:{task_id}")
        return TaskState(**dict(row))

    def transition(
        self, *, task_id: str, expected_version: int, expected_state: str, next_state: str,
        owner: str, source: SourceIdentity, reason: str, idempotency_key: str, next_owner: str,
        evidence_refs: Iterable[ArtifactRef | Mapping[str, str] | str] = (),
        context_digest: str | None = None,
    ) -> Transition:
        if next_state not in TRANSITIONS.get(expected_state, frozenset()):
            raise InvalidTransitionError(f"invalid_transition:{expected_state}->{next_state}")
        with self._db:
            row = self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise ControlStateError(f"task_not_found:{task_id}")
            if row["source_identity"] != source.identity_digest:
                raise StaleContextError("source_identity_mismatch")
            refs = self._resolve_refs(evidence_refs)
            prior = self._db.execute(
                "SELECT * FROM transitions WHERE task_id = ? AND idempotency_key = ?", (task_id, idempotency_key)
            ).fetchone()
            if prior is None:
                self._check_evidence(row, next_state, refs, context_digest=context_digest)
            if prior is not None:
                same = (
                    prior["from_state"] == expected_state and prior["next_state"] == next_state
                    and prior["version"] == expected_version + 1 and prior["owner"] == owner
                    and prior["next_owner"] == next_owner and prior["reason"] == reason
                    and prior["source_identity"] == source.identity_digest
                    and self._decode_refs(prior["evidence_refs_json"]) == refs
                )
                if not same:
                    raise ConcurrentTransitionError(f"idempotency_key_collision:{task_id}:{idempotency_key}")
                return self._transition_from_row(prior)
            if row["version"] != expected_version or row["state"] != expected_state:
                raise ConcurrentTransitionError(
                    f"expected_{expected_state}@{expected_version}:actual_{row['state']}@{row['version']}"
                )
            if row["owner"] != owner:
                raise ControlStateError("owner_mismatch")
            version = row["version"] + 1
            body = {
                "task_id": task_id, "idempotency_key": idempotency_key, "from_state": expected_state,
                "next_state": next_state, "version": version, "owner": owner, "next_owner": next_owner,
                "reason": reason, "source_identity": source.identity_digest,
                "evidence_refs": [ref.to_dict() for ref in refs],
            }
            fields = {**body, "transition_digest": content_digest(body),
                      "evidence_refs_json": json.dumps(body["evidence_refs"], sort_keys=True)}
            updated = self._db.execute(
                "UPDATE tasks SET state = ?, version = ?, owner = ? WHERE task_id = ? AND version = ?",
                (next_state, version, next_owner, task_id, expected_version),
            )
            if updated.rowcount != 1:
                raise ConcurrentTransitionError("cas_rowcount_mismatch")
            self._db.execute(
                "INSERT INTO transitions (task_id,idempotency_key,from_state,next_state,version,owner,next_owner,reason,source_identity,transition_digest,evidence_refs_json) VALUES (:task_id,:idempotency_key,:from_state,:next_state,:version,:owner,:next_owner,:reason,:source_identity,:transition_digest,:evidence_refs_json)",
                fields,
            )
            return Transition(
                task_id=task_id, idempotency_key=idempotency_key, from_state=expected_state,
                next_state=next_state, version=version, owner=owner, next_owner=next_owner,
                reason=reason, source_identity=source.identity_digest,
                transition_digest=fields["transition_digest"], evidence_refs=refs,
            )

    def list_transitions(self, task_id: str) -> list[Transition]:
        rows = self._db.execute("SELECT * FROM transitions WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [self._transition_from_row(row) for row in rows]

    def admit_artifact(self, artifact: Mapping[str, Any], *, chain: Iterable[Mapping[str, Any]] | None = None) -> ArtifactRef:
        value = dict(artifact)
        errors = verify_artifact(value)
        if errors:
            raise ControlStateError(f"artifact_invalid:{','.join(errors)}")
        payload = value["payload"]
        keys = ("task_id", "source_identity", "context_digest", "graph_identity")
        if any(key not in payload for key in keys):
            raise ControlStateError("artifact_payload_identity_required")
        task_id, source_identity = payload["task_id"], payload["source_identity"]
        context_digest, graph_identity = payload["context_digest"], payload["graph_identity"]
        if not isinstance(task_id, str) or not task_id:
            raise ControlStateError("artifact_task_id_invalid")
        for name, candidate in (("source_identity", source_identity), ("context_digest", context_digest), ("graph_identity", graph_identity)):
            if not _valid_digest(candidate):
                raise ControlStateError(f"artifact_{name}_invalid")
        if any(value["authority"].values()):
            raise ControlStateError("artifact_authority_forbidden")
        with self._db:
            task = self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise ControlStateError(f"task_not_found:{task_id}")
            if source_identity != task["source_identity"]:
                raise StaleContextError("source_identity_mismatch")
            existing = self._db.execute("SELECT artifact_json FROM artifacts WHERE artifact_digest = ?", (value["artifact_digest"],)).fetchone()
            if existing is not None:
                if json.loads(existing["artifact_json"]) != value:
                    raise ControlStateError("artifact_digest_collision")
                return ArtifactRef(value["artifact_type"], value["artifact_digest"])
            items = list(chain or ())
            if not items:
                items = [json.loads(row[0]) for row in self._db.execute("SELECT artifact_json FROM artifacts ORDER BY rowid")]
            if not any(item.get("artifact_digest") == value["artifact_digest"] for item in items):
                items.append(value)
            chain_errors = verify_artifact_chain([dict(item) for item in items])
            if chain_errors:
                raise ControlStateError(f"artifact_chain_invalid:{','.join(chain_errors)}")
            self._db.execute(
                "INSERT INTO artifacts (artifact_digest,task_id,artifact_type,status,producer,source_identity,context_digest,graph_identity,artifact_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (value["artifact_digest"], task_id, value["artifact_type"], value["status"], value["producer"],
                 source_identity, context_digest, graph_identity, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )
        return ArtifactRef(value["artifact_type"], value["artifact_digest"])

    admit_evidence = admit_artifact

    def list_admitted_artifacts(self, task_id: str) -> list[AdmittedArtifact]:
        rows = self._db.execute(
            "SELECT artifact_type,artifact_digest,status,producer,task_id,source_identity,context_digest,graph_identity FROM artifacts WHERE task_id = ? ORDER BY rowid", (task_id,)
        ).fetchall()
        return [AdmittedArtifact(**dict(row)) for row in rows]

    def record_handoff(self, receipt: HandoffReceipt, *, graph_identity: str | None = None) -> HandoffReceipt:
        refs = self._resolve_refs(receipt.required_artifact_refs)
        graph_ids = {self._artifact_graph_identity(ref) for ref in refs}
        if not graph_ids or "" in graph_ids or len(graph_ids) != 1:
            raise ControlStateError("handoff_graph_identity_mismatch")
        resolved_graph = next(iter(graph_ids))
        if graph_identity is not None and graph_identity != resolved_graph:
            raise StaleContextError("handoff_graph_identity_mismatch")
        with self._db:
            task = self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (receipt.task_id,)).fetchone()
            if task is None:
                raise ControlStateError(f"task_not_found:{receipt.task_id}")
            self._check_handoff_binding(task, receipt, refs)
            existing = self._db.execute("SELECT * FROM handoffs WHERE receipt_digest = ?", (receipt.receipt_digest,)).fetchone()
            if existing is None:
                self._db.execute(
                    "INSERT INTO handoffs (receipt_digest,task_id,task_version,from_owner,to_role,source_identity,context_digest,graph_identity,required_artifact_refs_json,accepted_or_rejected,reason,next_owner) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (receipt.receipt_digest, receipt.task_id, receipt.task_version, receipt.from_owner, receipt.to_role,
                     receipt.source_identity, receipt.context_digest, resolved_graph,
                     json.dumps([ref.to_dict() for ref in refs], sort_keys=True),
                     receipt.accepted_or_rejected, receipt.reason, receipt.next_owner),
                )
        return receipt

    def accept_handoff(self, receipt: HandoffReceipt | str, *, graph_identity: str | None = None) -> HandoffReceipt:
        digest = receipt if isinstance(receipt, str) else receipt.receipt_digest
        with self._db:
            row = self._db.execute("SELECT * FROM handoffs WHERE receipt_digest = ?", (digest,)).fetchone()
            if row is None:
                raise ControlStateError("handoff_not_recorded")
            if graph_identity is not None and row["graph_identity"] != graph_identity:
                raise StaleContextError("handoff_graph_identity_mismatch")
            if row["accepted_or_rejected"] == "rejected":
                raise ControlStateError("handoff_rejected")
            task = self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            if task is None:
                raise ControlStateError(f"task_not_found:{row['task_id']}")
            if row["accepted"]:
                return self._handoff_from_row(row)
            if task["version"] != row["task_version"]:
                raise ConcurrentTransitionError("handoff_task_version_stale")
            if task["owner"] != row["from_owner"]:
                raise ConcurrentTransitionError("handoff_owner_stale")
            updated = self._db.execute(
                "UPDATE tasks SET owner = ? WHERE task_id = ? AND version = ? AND owner = ?",
                (row["next_owner"], row["task_id"], row["task_version"], row["from_owner"]),
            )
            if updated.rowcount != 1:
                raise ConcurrentTransitionError("handoff_cas_rowcount_mismatch")
            self._db.execute("UPDATE handoffs SET accepted = 1 WHERE receipt_digest = ?", (digest,))
            return self._handoff_from_row(row)

    def record_run(self, run_id: str, **fields: Any) -> None:
        self._record_index("runs", "run_id", run_id, fields, ("task_id", "task_version", "source_identity", "context_digest", "status"))

    def record_tool_call(self, call_id: str, *, run_id: str, **fields: Any) -> None:
        self._record_index("tool_calls", "call_id", call_id, {"run_id": run_id, **fields}, ("run_id", "tool_id", "status"))

    def record_approval(self, approval_id: str, **fields: Any) -> None:
        self._record_index("approvals", "approval_id", approval_id, fields, ("task_id", "run_id", "owner", "status"))

    def _record_index(self, table: str, key: str, value: str, fields: dict[str, Any], columns: tuple[str, ...]) -> None:
        if not isinstance(value, str) or not value:
            raise ControlStateError(f"{key}_required")
        names = ",".join((key, *columns, "payload_json"))
        placeholders = ",".join("?" for _ in range(len(columns) + 2))
        payload_json = json.dumps(fields, sort_keys=True)
        with self._db:
            existing = self._db.execute(f"SELECT {names} FROM {table} WHERE {key} = ?", (value,)).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload_json or any(existing[name] != fields.get(name) for name in columns):
                    raise ControlStateError(f"{key}_collision:{value}")
                return
            params = [value, *(fields.get(name) for name in columns), payload_json]
            self._db.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", params)

    def _resolve_refs(self, refs: Iterable[ArtifactRef | Mapping[str, str] | str]) -> tuple[ArtifactRef, ...]:
        result: list[ArtifactRef] = []
        for ref in refs:
            if isinstance(ref, ArtifactRef):
                result.append(ref)
            elif isinstance(ref, Mapping):
                result.append(ArtifactRef(str(ref["artifact_type"]), str(ref["artifact_digest"])))
            elif isinstance(ref, str):
                row = self._db.execute("SELECT artifact_type FROM artifacts WHERE artifact_digest = ?", (ref,)).fetchone()
                if row is None:
                    raise ControlStateError(f"evidence_not_admitted:{ref}")
                result.append(ArtifactRef(row[0], ref))
            else:
                raise ControlStateError("evidence_ref_invalid")
        return tuple(result)

    def _check_evidence(self, task: sqlite3.Row, next_state: str, refs: tuple[ArtifactRef, ...], *, context_digest: str | None) -> None:
        required = REQUIRED_EVIDENCE.get(next_state)
        if required and not refs:
            raise ControlStateError(f"evidence_required:{next_state}")
        if required and refs and not any(ref.artifact_type == required[0] for ref in refs):
            raise ControlStateError("evidence_type_mismatch")
        for ref in refs:
            row = self._db.execute("SELECT * FROM artifacts WHERE artifact_digest = ?", (ref.artifact_digest,)).fetchone()
            if row is None:
                raise ControlStateError(f"evidence_not_admitted:{ref.artifact_digest}")
            if row["artifact_type"] != ref.artifact_type:
                raise ControlStateError("evidence_type_mismatch")
            if row["task_id"] != task["task_id"] or row["source_identity"] != task["source_identity"]:
                raise StaleContextError("evidence_identity_mismatch")
            if context_digest is not None and row["context_digest"] != context_digest:
                raise StaleContextError("evidence_context_mismatch")
            if required and (row["artifact_type"], row["status"], row["producer"]) != required:
                raise ControlStateError("evidence_type_mismatch")

    def _check_handoff_binding(self, task: sqlite3.Row, receipt: HandoffReceipt, refs: tuple[ArtifactRef, ...]) -> None:
        if task["version"] != receipt.task_version:
            raise ConcurrentTransitionError("handoff_task_version_stale")
        if task["owner"] != receipt.from_owner:
            raise ConcurrentTransitionError("handoff_owner_stale")
        if receipt.source_identity != task["source_identity"]:
            raise StaleContextError("handoff_source_identity_mismatch")
        if not refs:
            raise ControlStateError("handoff_evidence_required")
        graph_ids = {self._artifact_graph_identity(ref) for ref in refs}
        if len(graph_ids) != 1 or "" in graph_ids:
            raise ControlStateError("handoff_graph_identity_mismatch")
        context_match = False
        for ref in refs:
            self._check_evidence(task, "", (ref,), context_digest=None)
            row = self._db.execute(
                "SELECT context_digest FROM artifacts WHERE artifact_digest = ?", (ref.artifact_digest,)
            ).fetchone()
            context_match = context_match or row["context_digest"] == receipt.context_digest
        if not context_match:
            raise StaleContextError("handoff_context_mismatch")

    def _artifact_graph_identity(self, ref: ArtifactRef) -> str:
        row = self._db.execute(
            "SELECT graph_identity FROM artifacts WHERE artifact_digest = ? AND artifact_type = ?",
            (ref.artifact_digest, ref.artifact_type),
        ).fetchone()
        if row is None:
            raise ControlStateError(f"evidence_not_admitted:{ref.artifact_digest}")
        return row["graph_identity"]

    @staticmethod
    def _decode_refs(value: str | None) -> tuple[ArtifactRef, ...]:
        return tuple(ArtifactRef(**ref) for ref in json.loads(value or "[]"))

    @staticmethod
    def _handoff_from_row(row: sqlite3.Row) -> HandoffReceipt:
        return HandoffReceipt(
            task_id=row["task_id"], task_version=row["task_version"], from_owner=row["from_owner"],
            to_role=row["to_role"], source_identity=row["source_identity"], context_digest=row["context_digest"],
            required_artifact_refs=ControlStateStore._decode_refs(row["required_artifact_refs_json"]),
            accepted_or_rejected=row["accepted_or_rejected"], reason=row["reason"], next_owner=row["next_owner"],
        )

    @staticmethod
    def _transition_from_row(row: sqlite3.Row) -> Transition:
        return Transition(
            task_id=row["task_id"], idempotency_key=row["idempotency_key"], from_state=row["from_state"],
            next_state=row["next_state"], version=row["version"], owner=row["owner"], next_owner=row["next_owner"],
            reason=row["reason"], source_identity=row["source_identity"], transition_digest=row["transition_digest"],
            evidence_refs=ControlStateStore._decode_refs(row["evidence_refs_json"]),
        )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


__all__ = [
    "AdmittedArtifact", "ControlStateStore", "ControlStateError", "ConcurrentTransitionError",
    "InvalidTransitionError", "REQUIRED_EVIDENCE", "TaskState", "Transition",
]
