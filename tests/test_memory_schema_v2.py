from __future__ import annotations

import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.domain import CaseDefinition, PlayerState
from xuanyi_npc.memory import (
    DeterministicMemoryProjector,
    MemoryHardDeleteOperation,
    MemoryInvalidationOperation,
    MemoryLifecycleReason,
    MemorySchemaVersionError,
    MemoryStorageError,
    MemoryStoreCorruptionError,
    TrustedMemoryBoundary,
    stable_lifecycle_operation_id,
)
from xuanyi_npc.storage import MEMORY_SCHEMA_VERSION, SQLiteMemoryRepository

from .memory_helpers import reference_case_results


FIXED_TIME = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


class FailingMigrationRepository(SQLiteMemoryRepository):
    def _fault_point(self, name: str) -> None:
        if name == "migration_after_embedding_table":
            raise RuntimeError("injected migration failure")


def write_reference_memories(
    repository: SQLiteMemoryRepository,
    case: CaseDefinition,
    player: PlayerState,
    *,
    count: int = 3,
) -> tuple[str, ...]:
    _, results = reference_case_results(
        case,
        player,
        session_id="session_schema_v2",
    )
    projector = DeterministicMemoryProjector()
    memory_ids: list[str] = []
    for before, result in results[:count]:
        source, memory = projector.project_committed_event(
            event=result.events[0],
            case=case,
            player=player,
            session=result.session,
            source_revision=before.revision + 1,
        )
        repository.write_projection(source, memory)
        memory_ids.append(memory.memory_id)
    return tuple(memory_ids)


def downgrade_empty_embedding_schema_to_v1(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0
        connection.execute("DROP TABLE memory_embeddings")
        connection.execute("DROP INDEX IF EXISTS idx_memory_events_player_memory")
        connection.execute("UPDATE memory_schema SET version = 1 WHERE singleton = 1")
        connection.execute("PRAGMA user_version = 1")


def core_snapshot(database_path: Path) -> dict[str, list[tuple[object, ...]]]:
    tables = (
        "memory_source_receipts",
        "memory_events",
        "memory_lifecycle_events",
        "memory_tombstones",
    )
    with sqlite3.connect(database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }


def test_v1_to_v2_migration_preserves_authoritative_and_lifecycle_data(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    database_path = tmp_path / "memory.sqlite3"
    original = SQLiteMemoryRepository(database_path, clock=lambda: FIXED_TIME)
    original.initialize()
    memory_ids = write_reference_memories(
        original,
        case_definition,
        qualified_player_state,
    )
    operation = MemoryInvalidationOperation(
        operation_id=stable_lifecycle_operation_id(
            "invalidate",
            qualified_player_state.player_id,
            memory_ids[1],
            "migration_invalidate",
        ),
        request_id="migration_invalidate",
        player_id=qualified_player_state.player_id,
        target_memory_id=memory_ids[1],
        reason=MemoryLifecycleReason.SOURCE_REVOKED,
        trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
        occurred_at=FIXED_TIME,
    )
    original.invalidate_memory(operation)
    deletion = MemoryHardDeleteOperation(
        operation_id=stable_lifecycle_operation_id(
            "hard_delete",
            qualified_player_state.player_id,
            memory_ids[2],
            "migration_delete",
        ),
        request_id="migration_delete",
        player_id=qualified_player_state.player_id,
        target_memory_id=memory_ids[2],
        reason=MemoryLifecycleReason.PRIVACY_REQUEST,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=FIXED_TIME,
    )
    original.hard_delete_memory(deletion)
    downgrade_empty_embedding_schema_to_v1(database_path)
    before = core_snapshot(database_path)

    migrated = SQLiteMemoryRepository(database_path, clock=lambda: FIXED_TIME)
    migrated.initialize()

    assert migrated.schema_version() == MEMORY_SCHEMA_VERSION == 2
    assert core_snapshot(database_path) == before
    assert migrated.table_counts()["memory_embeddings"] == 0
    migrated.initialize()
    assert core_snapshot(database_path) == before


def test_v1_to_v2_migration_failure_rolls_back_atomically(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(database_path)
    repository.initialize()
    downgrade_empty_embedding_schema_to_v1(database_path)

    with pytest.raises(MemoryStorageError):
        FailingMigrationRepository(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT version FROM memory_schema WHERE singleton=1"
        ).fetchone()[0] == 1
    assert "memory_embeddings" not in tables

    SQLiteMemoryRepository(database_path).initialize()
    assert SQLiteMemoryRepository(database_path).schema_version() == 2


def test_future_schema_version_is_rejected_without_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite3"
    SQLiteMemoryRepository(database_path).initialize()
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 3")
        connection.execute("UPDATE memory_schema SET version=3 WHERE singleton=1")
    before = database_path.read_bytes()

    with pytest.raises(MemorySchemaVersionError):
        SQLiteMemoryRepository(database_path).initialize()

    assert database_path.read_bytes() == before


def test_embedding_table_rejects_bad_blob_and_orphan_memory(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    database_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(database_path)
    repository.initialize()
    memory_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
    )[0]
    memory = repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory_id,
    )
    values = (
        memory_id,
        qualified_player_state.player_id,
        "test_space_v1",
        memory.content_hash,
        2,
        sqlite3.Binary(struct.pack("<f", 1.0)),
        1.0,
        FIXED_TIME.isoformat(),
    )
    insert = (
        "INSERT INTO memory_embeddings (memory_id,player_id,embedding_space_id,"
        "content_hash,dimension,vector_blob,l2_norm,generated_at) "
        "VALUES (?,?,?,?,?,?,?,?)"
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, values)
        orphan_values = (
            "missing_memory",
            qualified_player_state.player_id,
            "test_space_v1",
            "0" * 64,
            2,
            sqlite3.Binary(struct.pack("<2f", 1.0, 0.0)),
            1.0,
            FIXED_TIME.isoformat(),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, orphan_values)


def test_corrupt_non_finite_blob_fails_safe_on_decode(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    database_path = tmp_path / "memory.sqlite3"
    repository = SQLiteMemoryRepository(database_path)
    repository.initialize()
    memory_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
    )[0]
    memory = repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory_id,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO memory_embeddings (
                memory_id, player_id, embedding_space_id, content_hash,
                dimension, vector_blob, l2_norm, generated_at
            ) VALUES (?, ?, ?, ?, 2, ?, 1.0, ?)
            """,
            (
                memory_id,
                qualified_player_state.player_id,
                "corrupt_space_v1",
                memory.content_hash,
                sqlite3.Binary(struct.pack("<2f", float("nan"), 1.0)),
                FIXED_TIME.isoformat(),
            ),
        )

    with pytest.raises(MemoryStoreCorruptionError):
        repository.list_embeddings(
            player_id=qualified_player_state.player_id,
            embedding_space_id="corrupt_space_v1",
        )
