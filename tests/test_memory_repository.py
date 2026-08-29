from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.domain import CaseDefinition, PlayerState
from xuanyi_npc.memory import (
    AuthoritativeMemoryRecord,
    DeterministicMemoryProjector,
    InvalidMemoryLifecycleError,
    LifecycleDisposition,
    MemoryCorrectionOperation,
    MemoryHardDeleteOperation,
    MemoryInvalidationOperation,
    MemoryLifecycleConflictError,
    MemoryLifecycleReason,
    MemoryNotFoundError,
    MemoryPlayerIsolationError,
    MemorySchemaVersionError,
    MemoryStatus,
    MemoryStorageError,
    MemoryStoreCorruptionError,
    MemoryTombstonedError,
    ProjectionConflictError,
    ProjectionWriteDisposition,
    TrustedMemoryBoundary,
    UnsupportedMemorySourceError,
    VerifiedMemorySource,
    sha256_hex,
    stable_lifecycle_operation_id,
    stable_memory_id,
)
from xuanyi_npc.memory.contracts import authoritative_content_payload
from xuanyi_npc.storage import MEMORY_SCHEMA_VERSION, SQLiteMemoryRepository

from .memory_helpers import reference_case_results


FIXED_TIME = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
HIDDEN_SENTINEL = "hidden_truth_must_never_enter_sqlite"


class FailingSQLiteMemoryRepository(SQLiteMemoryRepository):
    def __init__(self, database_path: Path, *, fail_at: str | None = None) -> None:
        super().__init__(database_path, clock=lambda: FIXED_TIME)
        self.fail_at = fail_at

    def _fault_point(self, name: str) -> None:
        if name == self.fail_at:
            raise RuntimeError("injected transaction failure")


@pytest.fixture()
def memory_repository(tmp_path: Path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(
        tmp_path / "memory.sqlite3",
        clock=lambda: FIXED_TIME,
    )
    repository.initialize()
    return repository


def first_projection(
    case: CaseDefinition,
    player: PlayerState,
    *,
    session_id: str = "session_memory_repository",
):
    _, results = reference_case_results(case, player, session_id=session_id)
    before, result = results[0]
    return DeterministicMemoryProjector().project_committed_event(
        event=result.events[0],
        case=case,
        player=player,
        session=result.session,
        source_revision=before.revision + 1,
    )


def correction_operation(
    *,
    player_id: str,
    memory_id: str,
    request_id: str = "request_correction_one",
    content: str = "经可信复核后的公开调查记录。",
) -> MemoryCorrectionOperation:
    return MemoryCorrectionOperation(
        operation_id=stable_lifecycle_operation_id(
            "correct", player_id, memory_id, request_id
        ),
        request_id=request_id,
        player_id=player_id,
        target_memory_id=memory_id,
        reason=MemoryLifecycleReason.VERIFIED_CORRECTION,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=FIXED_TIME,
        replacement_public_content=content,
    )


def invalidation_operation(
    *,
    player_id: str,
    memory_id: str,
    request_id: str = "request_invalidate_one",
) -> MemoryInvalidationOperation:
    return MemoryInvalidationOperation(
        operation_id=stable_lifecycle_operation_id(
            "invalidate", player_id, memory_id, request_id
        ),
        request_id=request_id,
        player_id=player_id,
        target_memory_id=memory_id,
        reason=MemoryLifecycleReason.SOURCE_REVOKED,
        trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
        occurred_at=FIXED_TIME,
    )


def hard_delete_operation(
    *,
    player_id: str,
    memory_id: str,
    request_id: str = "request_delete_one",
) -> MemoryHardDeleteOperation:
    return MemoryHardDeleteOperation(
        operation_id=stable_lifecycle_operation_id(
            "hard_delete", player_id, memory_id, request_id
        ),
        request_id=request_id,
        player_id=player_id,
        target_memory_id=memory_id,
        reason=MemoryLifecycleReason.PRIVACY_REQUEST,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=FIXED_TIME,
    )


def test_repository_requires_explicit_initialization_and_creates_schema_v2_tables(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "nested" / "memory.sqlite3"
    repository = SQLiteMemoryRepository(database_path)

    assert not database_path.exists()
    with pytest.raises(MemoryStorageError):
        repository.schema_version()
    assert not database_path.exists()

    repository.initialize()
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert repository.schema_version() == MEMORY_SCHEMA_VERSION == 3
    assert repository.REQUIRED_TABLES.issubset(tables)
    assert "memory_embeddings" in tables


def test_authoritative_projection_round_trip_contains_full_source_chain(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)

    result = memory_repository.write_projection(source, memory)
    restored = memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )
    receipt = memory_repository.get_source_receipt(
        player_id=qualified_player_state.player_id,
        source_event_id=source.source_event_id,
        projection_version=source.projection_version,
        projection_ordinal=source.projection_ordinal,
    )

    assert result.disposition is ProjectionWriteDisposition.CREATED
    assert restored == memory
    assert receipt == source
    assert restored.source_session_id == "session_memory_repository"
    assert restored.source_sequence == 1
    assert restored.source_revision == 1
    assert restored.relationship_impacts == ()


def test_duplicate_projection_is_idempotent_with_one_receipt_and_memory(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)

    first = memory_repository.write_projection(source, memory)
    second = memory_repository.write_projection(source, memory)

    assert first.disposition is ProjectionWriteDisposition.CREATED
    assert second.disposition is ProjectionWriteDisposition.IDEMPOTENT
    assert memory_repository.table_counts() == {
        "memory_embeddings": 0,
        "memory_events": 1,
        "memory_lifecycle_events": 0,
        "memory_source_receipts": 1,
        "memory_tombstones": 0,
    }


def test_projection_conflict_does_not_overwrite_original(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    replacement_content = "冲突的公开内容。"
    data = memory.model_dump(mode="python")
    data["content"] = replacement_content
    data["content_hash"] = sha256_hex(
        authoritative_content_payload(
            memory_type=memory.memory_type,
            content=replacement_content,
            importance=memory.importance,
            related_case_id=memory.related_case_id,
            related_entity_ids=memory.related_entity_ids,
        )
    )
    conflicting = AuthoritativeMemoryRecord.model_validate(data)

    with pytest.raises(ProjectionConflictError) as exc_info:
        memory_repository.write_projection(source, conflicting)

    assert exc_info.value.code == "projection_conflict"
    assert memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    ) == memory
    assert memory_repository.table_counts()["memory_events"] == 1


def test_same_source_key_with_different_public_hash_is_a_conflict(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    payload_data = source.public_payload.model_dump(mode="python")
    payload_data["public_action_description"] = "另一条公开调查描述。"
    changed_payload = type(source.public_payload).model_validate(payload_data)
    source_data = source.model_dump(mode="python")
    source_data["public_payload"] = changed_payload
    source_data["public_payload_hash"] = sha256_hex(changed_payload)
    conflicting_source = VerifiedMemorySource.model_validate(source_data)
    conflicting_memory = DeterministicMemoryProjector().memory_from_verified_source(
        conflicting_source
    )

    with pytest.raises(ProjectionConflictError):
        memory_repository.write_projection(conflicting_source, conflicting_memory)

    assert memory_repository.get_source_receipt(
        player_id=qualified_player_state.player_id,
        source_event_id=source.source_event_id,
        projection_version=source.projection_version,
        projection_ordinal=source.projection_ordinal,
    ) == source
    assert memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    ) == memory


def test_projection_player_mismatch_is_rejected_before_write(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    other_player_id = "player_other"
    data = memory.model_dump(mode="python")
    data["player_id"] = other_player_id
    data["memory_id"] = stable_memory_id(
        other_player_id,
        memory.source_event_id,
        memory.projection_version,
        memory.projection_ordinal,
    )
    other_memory = AuthoritativeMemoryRecord.model_validate(data)

    with pytest.raises(MemoryPlayerIsolationError):
        memory_repository.write_projection(source, other_memory)

    assert memory_repository.table_counts()["memory_events"] == 0
    assert memory_repository.table_counts()["memory_source_receipts"] == 0


def test_projection_transaction_failure_rolls_back_receipt_and_memory(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = FailingSQLiteMemoryRepository(
        tmp_path / "memory.sqlite3",
        fail_at="projection_after_receipt",
    )
    repository.initialize()
    source, memory = first_projection(case_definition, qualified_player_state)

    with pytest.raises(MemoryStorageError):
        repository.write_projection(source, memory)

    assert repository.table_counts()["memory_source_receipts"] == 0
    assert repository.table_counts()["memory_events"] == 0


def test_correction_is_atomic_auditable_and_idempotent(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    operation = correction_operation(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )

    first = memory_repository.correct_memory(operation)
    second = memory_repository.correct_memory(operation)
    original = memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )
    replacement = memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=first.replacement_memory_id,
    )

    assert first.disposition is LifecycleDisposition.APPLIED
    assert second.disposition is LifecycleDisposition.IDEMPOTENT
    assert original.status is MemoryStatus.SUPERSEDED
    assert replacement.status is MemoryStatus.ACTIVE
    assert replacement.supersedes_memory_id == original.memory_id
    assert replacement.source_event_id != original.source_event_id
    assert replacement.content == operation.replacement_public_content
    assert memory_repository.table_counts()["memory_lifecycle_events"] == 1


def test_same_lifecycle_operation_id_with_changed_content_conflicts(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    operation = correction_operation(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )
    memory_repository.correct_memory(operation)
    changed = operation.model_copy(
        update={"replacement_public_content": "相同操作 ID 下的另一份内容。"}
    )

    with pytest.raises(MemoryLifecycleConflictError):
        memory_repository.correct_memory(changed)

    assert memory_repository.table_counts()["memory_events"] == 2
    assert memory_repository.table_counts()["memory_lifecycle_events"] == 1


def test_correction_transaction_failure_rolls_back_all_changes(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = FailingSQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.initialize()
    source, memory = first_projection(case_definition, qualified_player_state)
    repository.write_projection(source, memory)
    repository.fail_at = "lifecycle_before_commit"
    operation = correction_operation(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )

    with pytest.raises(MemoryStorageError):
        repository.correct_memory(operation)

    restored = repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )
    assert restored.status is MemoryStatus.ACTIVE
    assert repository.table_counts()["memory_events"] == 1
    assert repository.table_counts()["memory_source_receipts"] == 1
    assert repository.table_counts()["memory_lifecycle_events"] == 0


def test_invalidation_is_audited_and_idempotent(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    operation = invalidation_operation(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )

    first = memory_repository.invalidate_memory(operation)
    second = memory_repository.invalidate_memory(operation)

    assert first.disposition is LifecycleDisposition.APPLIED
    assert second.disposition is LifecycleDisposition.IDEMPOTENT
    assert memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    ).status is MemoryStatus.INVALIDATED
    assert memory_repository.list_memories(
        player_id=qualified_player_state.player_id,
        include_inactive=False,
    ) == ()


def test_hard_delete_removes_application_content_and_leaves_non_content_tombstone(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    operation = hard_delete_operation(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    )

    first = memory_repository.hard_delete_memory(operation)
    second = memory_repository.hard_delete_memory(operation)

    assert first.hard_deleted is True
    assert second.disposition is LifecycleDisposition.IDEMPOTENT
    with pytest.raises(MemoryNotFoundError):
        memory_repository.get_memory(
            player_id=qualified_player_state.player_id,
            memory_id=memory.memory_id,
        )
    with pytest.raises(MemoryNotFoundError):
        memory_repository.get_source_receipt(
            player_id=qualified_player_state.player_id,
            source_event_id=source.source_event_id,
            projection_version=source.projection_version,
            projection_ordinal=source.projection_ordinal,
        )
    assert memory_repository.table_counts() == {
        "memory_embeddings": 0,
        "memory_events": 0,
        "memory_lifecycle_events": 1,
        "memory_source_receipts": 0,
        "memory_tombstones": 1,
    }
    assert memory_repository.tombstone_exists(memory.memory_id)
    with sqlite3.connect(memory_repository.database_path) as connection:
        tombstone_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memory_tombstones)")
        }
    assert "content" not in tombstone_columns
    assert "public_payload_json" not in tombstone_columns


def test_tombstone_prevents_projection_rebuild_from_restoring_deleted_content(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    memory_repository.hard_delete_memory(
        hard_delete_operation(
            player_id=qualified_player_state.player_id,
            memory_id=memory.memory_id,
        )
    )

    with pytest.raises(MemoryTombstonedError):
        memory_repository.write_projection(source, memory)

    assert memory_repository.table_counts()["memory_events"] == 0
    assert memory_repository.table_counts()["memory_source_receipts"] == 0


def test_hard_delete_removes_correction_chain_and_all_public_payloads(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, original = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, original)
    correction = memory_repository.correct_memory(
        correction_operation(
            player_id=qualified_player_state.player_id,
            memory_id=original.memory_id,
        )
    )
    assert correction.replacement_memory_id is not None
    replacement = memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=correction.replacement_memory_id,
    )

    memory_repository.hard_delete_memory(
        hard_delete_operation(
            player_id=qualified_player_state.player_id,
            memory_id=original.memory_id,
        )
    )

    for item in (original, replacement):
        with pytest.raises(MemoryNotFoundError):
            memory_repository.get_memory(
                player_id=qualified_player_state.player_id,
                memory_id=item.memory_id,
            )
        with pytest.raises(MemoryNotFoundError):
            memory_repository.get_source_receipt(
                player_id=qualified_player_state.player_id,
                source_event_id=item.source_event_id,
                projection_version=item.projection_version,
                projection_ordinal=item.projection_ordinal,
            )
        assert memory_repository.tombstone_exists(item.memory_id)
    assert memory_repository.table_counts()["memory_events"] == 0
    assert memory_repository.table_counts()["memory_source_receipts"] == 0
    assert memory_repository.table_counts()["memory_tombstones"] == 2


def test_hard_delete_transaction_failure_restores_content_and_audit_tables(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = FailingSQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.initialize()
    source, memory = first_projection(case_definition, qualified_player_state)
    repository.write_projection(source, memory)
    repository.fail_at = "hard_delete_after_content_delete"

    with pytest.raises(MemoryStorageError):
        repository.hard_delete_memory(
            hard_delete_operation(
                player_id=qualified_player_state.player_id,
                memory_id=memory.memory_id,
            )
        )

    assert repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    ) == memory
    assert repository.get_source_receipt(
        player_id=qualified_player_state.player_id,
        source_event_id=source.source_event_id,
        projection_version=source.projection_version,
        projection_ordinal=source.projection_ordinal,
    ) == source
    assert repository.table_counts() == {
        "memory_embeddings": 0,
        "memory_events": 1,
        "memory_lifecycle_events": 0,
        "memory_source_receipts": 1,
        "memory_tombstones": 0,
    }


def test_player_cannot_read_or_mutate_another_players_memory(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    other_player = "player_other"

    with pytest.raises(MemoryPlayerIsolationError):
        memory_repository.get_memory(player_id=other_player, memory_id=memory.memory_id)
    with pytest.raises(MemoryPlayerIsolationError):
        memory_repository.invalidate_memory(
            invalidation_operation(
                player_id=other_player,
                memory_id=memory.memory_id,
                request_id="request_other_player",
            )
        )

    assert memory_repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory.memory_id,
    ).status is MemoryStatus.ACTIVE
    assert memory_repository.table_counts()["memory_lifecycle_events"] == 0


def test_same_session_identity_remains_isolated_by_player_scope(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    shared_session_id = "session_shared_external_identity"
    first_source, first_memory = first_projection(
        case_definition,
        qualified_player_state,
        session_id=shared_session_id,
    )
    other_data = qualified_player_state.model_dump(mode="python")
    other_data["player_id"] = "player_other"
    other_player = PlayerState.model_validate(other_data)
    other_source, other_memory = first_projection(
        case_definition,
        other_player,
        session_id=shared_session_id,
    )

    assert first_source.source_event_id == other_source.source_event_id
    assert first_memory.memory_id != other_memory.memory_id
    memory_repository.write_projection(first_source, first_memory)
    memory_repository.write_projection(other_source, other_memory)

    assert memory_repository.list_memories(
        player_id=qualified_player_state.player_id
    ) == (first_memory,)
    assert memory_repository.list_memories(player_id=other_player.player_id) == (
        other_memory,
    )
    assert memory_repository.table_counts()["memory_events"] == 2
    assert memory_repository.table_counts()["memory_source_receipts"] == 2


def test_unknown_schema_version_fails_safely(tmp_path: Path) -> None:
    database_path = tmp_path / "future.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 99")

    with pytest.raises(MemorySchemaVersionError):
        SQLiteMemoryRepository(database_path).initialize()


def test_corrupt_database_fails_with_explicit_error(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt.sqlite3"
    database_path.write_bytes(b"not a sqlite database")

    with pytest.raises(MemoryStoreCorruptionError):
        SQLiteMemoryRepository(database_path).initialize()


def test_new_lifecycle_operation_cannot_reapply_to_inactive_target(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    source, memory = first_projection(case_definition, qualified_player_state)
    memory_repository.write_projection(source, memory)
    memory_repository.invalidate_memory(
        invalidation_operation(
            player_id=qualified_player_state.player_id,
            memory_id=memory.memory_id,
        )
    )

    with pytest.raises(InvalidMemoryLifecycleError):
        memory_repository.invalidate_memory(
            invalidation_operation(
                player_id=qualified_player_state.player_id,
                memory_id=memory.memory_id,
                request_id="request_invalidate_two",
            )
        )


def test_hidden_case_sentinel_never_reaches_receipt_memory_database_or_error(
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    data = case_definition.model_dump(mode="python")
    data["root_cause"] = HIDDEN_SENTINEL
    data["causal_chain"] = (HIDDEN_SENTINEL,)
    data["patient"]["hidden_information"] = (HIDDEN_SENTINEL,)
    data["clues"]["broken_promise"]["description"] = HIDDEN_SENTINEL
    hidden_case = CaseDefinition.model_validate(data)
    source, memory = first_projection(hidden_case, qualified_player_state)

    memory_repository.write_projection(source, memory)

    assert HIDDEN_SENTINEL not in source.model_dump_json()
    assert HIDDEN_SENTINEL not in memory.model_dump_json()
    assert HIDDEN_SENTINEL.encode("utf-8") not in memory_repository.database_path.read_bytes()

    conflicting_data = memory.model_dump(mode="python")
    conflicting_data["content"] = "另一条公开内容。"
    conflicting_data["content_hash"] = sha256_hex(
        authoritative_content_payload(
            memory_type=memory.memory_type,
            content=conflicting_data["content"],
            importance=memory.importance,
            related_case_id=memory.related_case_id,
            related_entity_ids=memory.related_entity_ids,
        )
    )
    conflicting = AuthoritativeMemoryRecord.model_validate(conflicting_data)
    with pytest.raises(ProjectionConflictError) as exc_info:
        memory_repository.write_projection(source, conflicting)
    assert HIDDEN_SENTINEL not in str(exc_info.value)


def test_import_has_no_database_file_output_or_network_side_effect(tmp_path: Path) -> None:
    script = """
import socket
from pathlib import Path

def forbidden(*args, **kwargs):
    raise AssertionError("network access during module import")

socket.create_connection = forbidden
socket.socket.connect = forbidden
before = tuple(Path.cwd().iterdir())
import xuanyi_npc.storage.sqlite_memory
after = tuple(Path.cwd().iterdir())
assert before == after == ()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize(
    "forbidden_source",
    (
        {"type": "respond", "content": "model reply"},
        {"type": "chat", "content": "raw conversation"},
        {"type": "tool_rejection", "error_code": "diagnosis_not_ready"},
        {"type": "timeout", "elapsed_ms": 180000},
        {"type": "log", "content": "diagnostic output"},
        {"type": "unknown_future_event", "content": "must default deny"},
    ),
)
def test_forbidden_sources_are_default_denied_with_zero_writes(
    forbidden_source: dict[str, object],
    memory_repository: SQLiteMemoryRepository,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)

    with pytest.raises(UnsupportedMemorySourceError):
        DeterministicMemoryProjector().project_committed_event(
            event=forbidden_source,
            case=case_definition,
            player=qualified_player_state,
            session=results[0][1].session,
            source_revision=1,
        )

    assert memory_repository.table_counts() == {
        "memory_embeddings": 0,
        "memory_events": 0,
        "memory_lifecycle_events": 0,
        "memory_source_receipts": 0,
        "memory_tombstones": 0,
    }
