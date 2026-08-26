from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import StaleContextError
from .contracts import SourceIdentity, TaskSnapshot, content_digest


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
    "CANCELLED": frozenset(),
    "CLOSED": frozenset(),
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
                task_id TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                owner TEXT NOT NULL,
                source_identity TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                idempotency_key TEXT NOT NULL,
                from_state TEXT NOT NULL,
                next_state TEXT NOT NULL,
                version INTEGER NOT NULL,
                owner TEXT NOT NULL,
                next_owner TEXT NOT NULL,
                reason TEXT NOT NULL,
                source_identity TEXT NOT NULL,
                transition_digest TEXT NOT NULL,
                UNIQUE(task_id, idempotency_key)
            );
            """
        )
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
        row = self._db.execute("SELECT task_id,state,version,owner,source_identity FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise ControlStateError(f"task_not_found:{task_id}")
        return TaskState(**dict(row))

    def transition(self, *, task_id: str, expected_version: int, expected_state: str, next_state: str, owner: str, source: SourceIdentity, reason: str, idempotency_key: str, next_owner: str) -> Transition:
        if next_state not in TRANSITIONS.get(expected_state, frozenset()):
            raise InvalidTransitionError(f"invalid_transition:{expected_state}->{next_state}")
        with self._db:
            row = self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise ControlStateError(f"task_not_found:{task_id}")
            if row["source_identity"] != source.identity_digest:
                raise StaleContextError("source_identity_mismatch")
            prior = self._db.execute(
                "SELECT * FROM transitions WHERE task_id = ? AND idempotency_key = ?",
                (task_id, idempotency_key),
            ).fetchone()
            if prior is not None:
                return self._transition_from_row(prior)
            if row["version"] != expected_version or row["state"] != expected_state:
                raise ConcurrentTransitionError(
                    f"expected_{expected_state}@{expected_version}:actual_{row['state']}@{row['version']}"
                )
            if row["owner"] != owner:
                raise ControlStateError("owner_mismatch")
            version = row["version"] + 1
            fields = {
                "task_id": task_id, "idempotency_key": idempotency_key, "from_state": expected_state,
                "next_state": next_state, "version": version, "owner": owner, "next_owner": next_owner,
                "reason": reason, "source_identity": source.identity_digest,
            }
            fields["transition_digest"] = content_digest(fields)
            self._db.execute(
                "UPDATE tasks SET state = ?, version = ?, owner = ? WHERE task_id = ? AND version = ?",
                (next_state, version, next_owner, task_id, expected_version),
            )
            self._db.execute(
                "INSERT INTO transitions (task_id,idempotency_key,from_state,next_state,version,owner,next_owner,reason,source_identity,transition_digest) VALUES (:task_id,:idempotency_key,:from_state,:next_state,:version,:owner,:next_owner,:reason,:source_identity,:transition_digest)",
                fields,
            )
            return Transition(**fields)

    def list_transitions(self, task_id: str) -> list[Transition]:
        rows = self._db.execute("SELECT * FROM transitions WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [self._transition_from_row(row) for row in rows]

    @staticmethod
    def _transition_from_row(row: sqlite3.Row) -> Transition:
        return Transition(
            task_id=row["task_id"], idempotency_key=row["idempotency_key"], from_state=row["from_state"],
            next_state=row["next_state"], version=row["version"], owner=row["owner"],
            next_owner=row["next_owner"], reason=row["reason"], source_identity=row["source_identity"],
            transition_digest=row["transition_digest"],
        )


__all__ = ["ControlStateStore", "ConcurrentTransitionError", "InvalidTransitionError", "TaskState", "Transition"]
