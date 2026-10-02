"""Independent SQLite journal for CE-2A cooperative conversation turns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Literal


COOPERATION_SCHEMA_VERSION = "cooperative_history_v1"
TurnLifecycle = Literal[
    "started", "prepared", "completed", "failed_before_reply", "recovery_required"
]


class CooperativeHistoryError(RuntimeError):
    pass


class CooperativePayloadConflict(CooperativeHistoryError):
    pass


@dataclass(frozen=True)
class CooperativeTurnRecord:
    player_id: str
    case_id: str
    session_id: str
    operation_id: str
    sequence: int
    lifecycle: TurnLifecycle
    request_fingerprint: str
    request_json: str
    contribution_json: str | None
    prepared_decision_json: str | None
    result_json: str | None
    owner_process_id: str
    failure_code: str | None


class SQLiteCooperativeHistoryRepository:
    """A small journal intentionally separate from memories and world JSON."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def stable_request_json(payload: dict[str, object]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def fingerprint(cls, payload: dict[str, object]) -> str:
        raw = cls.stable_request_json(payload).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cooperative_turns (
                        player_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        operation_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        lifecycle TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        contribution_json TEXT,
                        prepared_decision_json TEXT,
                        result_json TEXT,
                        owner_process_id TEXT NOT NULL,
                        failure_code TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (player_id, case_id, session_id, operation_id),
                        UNIQUE (player_id, case_id, session_id, sequence)
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise CooperativeHistoryError("cooperative history is unavailable") from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _record(row: sqlite3.Row) -> CooperativeTurnRecord:
        return CooperativeTurnRecord(**{
            key: row[key]
            for key in CooperativeTurnRecord.__dataclass_fields__
        })

    def get(self, player_id: str, case_id: str, session_id: str, operation_id: str) -> CooperativeTurnRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT * FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=? AND operation_id=?""",
                    (player_id, case_id, session_id, operation_id),
                ).fetchone()
            return self._record(row) if row is not None else None
        except sqlite3.Error as exc:
            raise CooperativeHistoryError("cooperative history read failed") from exc

    def begin(
        self,
        *,
        player_id: str,
        case_id: str,
        session_id: str,
        operation_id: str,
        stable_request: dict[str, object],
        contribution_json: str,
        owner_process_id: str,
    ) -> tuple[CooperativeTurnRecord, bool]:
        request_json = self.stable_request_json(stable_request)
        fingerprint = self.fingerprint(stable_request)
        now = self._now()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT * FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=? AND operation_id=?""",
                    (player_id, case_id, session_id, operation_id),
                ).fetchone()
                if row is not None:
                    record = self._record(row)
                    if record.request_fingerprint != fingerprint or record.request_json != request_json:
                        raise CooperativePayloadConflict("operation_id was reused with a different request")
                    return record, False
                sequence = connection.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 1 FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=?""",
                    (player_id, case_id, session_id),
                ).fetchone()[0]
                connection.execute(
                    """INSERT INTO cooperative_turns
                       (player_id,case_id,session_id,operation_id,sequence,lifecycle,
                        request_fingerprint,request_json,contribution_json,owner_process_id,
                        created_at,updated_at)
                       VALUES (?,?,?,?,?,'started',?,?,?,?,?,?)""",
                    (player_id, case_id, session_id, operation_id, sequence,
                     fingerprint, request_json, contribution_json, owner_process_id, now, now),
                )
                row = connection.execute(
                    """SELECT * FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=? AND operation_id=?""",
                    (player_id, case_id, session_id, operation_id),
                ).fetchone()
                return self._record(row), True
        except CooperativePayloadConflict:
            raise
        except sqlite3.Error as exc:
            raise CooperativeHistoryError("cooperative history begin failed") from exc

    def _transition(
        self,
        record: CooperativeTurnRecord,
        *,
        lifecycle: TurnLifecycle,
        prepared_decision_json: str | None = None,
        result_json: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """UPDATE cooperative_turns SET lifecycle=?,
                       prepared_decision_json=COALESCE(?, prepared_decision_json),
                       result_json=COALESCE(?, result_json), failure_code=?, updated_at=?
                       WHERE player_id=? AND case_id=? AND session_id=? AND operation_id=?
                         AND request_fingerprint=?""",
                    (lifecycle, prepared_decision_json, result_json, failure_code, self._now(),
                     record.player_id, record.case_id, record.session_id, record.operation_id,
                     record.request_fingerprint),
                )
                if cursor.rowcount != 1:
                    raise CooperativeHistoryError("cooperative history ownership changed")
        except sqlite3.Error as exc:
            raise CooperativeHistoryError("cooperative history transition failed") from exc

    def mark_prepared(self, record: CooperativeTurnRecord, decision_json: str) -> None:
        self._transition(record, lifecycle="prepared", prepared_decision_json=decision_json)

    def complete(self, record: CooperativeTurnRecord, result_json: str) -> None:
        self._transition(record, lifecycle="completed", result_json=result_json)

    def fail_before_reply(self, record: CooperativeTurnRecord, code: str) -> None:
        self._transition(record, lifecycle="failed_before_reply", failure_code=code)

    def require_recovery(self, record: CooperativeTurnRecord, code: str) -> None:
        self._transition(record, lifecycle="recovery_required", failure_code=code)

    def recent_completed_before(self, record: CooperativeTurnRecord, limit: int) -> tuple[CooperativeTurnRecord, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT * FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=?
                         AND sequence < ? AND lifecycle='completed'
                       ORDER BY sequence DESC LIMIT ?""",
                    (record.player_id, record.case_id, record.session_id, record.sequence, limit),
                ).fetchall()
            return tuple(self._record(row) for row in rows)
        except sqlite3.Error as exc:
            raise CooperativeHistoryError("cooperative history selection failed") from exc

    def completed_count_before(self, record: CooperativeTurnRecord) -> int:
        try:
            with self._connect() as connection:
                return int(connection.execute(
                    """SELECT COUNT(*) FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=?
                         AND sequence < ? AND lifecycle='completed'""",
                    (record.player_id, record.case_id, record.session_id, record.sequence),
                ).fetchone()[0])
        except sqlite3.Error as exc:
            raise CooperativeHistoryError("cooperative history count failed") from exc

    def completed_for_session(
        self,
        player_id: str,
        case_id: str,
        session_id: str,
        *,
        limit: int = 16,
    ) -> tuple[CooperativeTurnRecord, ...]:
        """Return completed public conversation turns in display order."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT * FROM cooperative_turns
                       WHERE player_id=? AND case_id=? AND session_id=?
                         AND lifecycle='completed'
                       ORDER BY sequence DESC LIMIT ?""",
                    (player_id, case_id, session_id, limit),
                ).fetchall()
            return tuple(self._record(row) for row in reversed(rows))
        except sqlite3.Error as exc:
            raise CooperativeHistoryError("cooperative history selection failed") from exc
