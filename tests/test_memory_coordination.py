from __future__ import annotations

from pathlib import Path

from xuanyi_npc.application import V1MemoryCoordinator
from xuanyi_npc.domain import CaseDefinition, PlayerState
from xuanyi_npc.memory import MemoryCommitStatus, MemoryStorageError, ProjectionWriteDisposition
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository

from .memory_helpers import reference_case_results


class FailFirstProjectionRepository:
    def __init__(self, delegate: SQLiteMemoryRepository) -> None:
        self.delegate = delegate
        self.failed = False

    def write_projection(self, source, memory):
        if not self.failed:
            self.failed = True
            raise MemoryStorageError("injected projection failure")
        return self.delegate.write_projection(source, memory)


def test_committed_session_reconciles_pending_projection_idempotently(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    state_store = JsonStateStore(tmp_path / "state")
    state_store.save_player(qualified_player_state)
    repository = SQLiteMemoryRepository(tmp_path / "memories.sqlite3")
    repository.initialize()
    before, result = reference_case_results(case_definition, qualified_player_state)[1][0]

    pending = V1MemoryCoordinator(
        state_store=state_store,
        memory_repository=FailFirstProjectionRepository(repository),
    ).commit_engine_result(
        case=case_definition,
        player=qualified_player_state,
        previous_session=before,
        result=result,
    )

    assert pending.status is MemoryCommitStatus.MEMORY_PROJECTION_PENDING
    assert pending.error_code == "memory_storage_error"
    assert state_store.load_case_session(result.session.session_id) == result.session
    assert repository.table_counts()["memory_events"] == 0

    coordinator = V1MemoryCoordinator(
        state_store=state_store,
        memory_repository=repository,
    )
    first = coordinator.reconcile_committed_session(
        case=case_definition,
        player_id=qualified_player_state.player_id,
        session_id=result.session.session_id,
    )
    second = coordinator.reconcile_committed_session(
        case=case_definition,
        player_id=qualified_player_state.player_id,
        session_id=result.session.session_id,
    )

    assert first.status is MemoryCommitStatus.COMPLETE
    assert first.projections[0].disposition is ProjectionWriteDisposition.CREATED
    assert second.status is MemoryCommitStatus.COMPLETE
    assert second.projections[0].disposition is ProjectionWriteDisposition.IDEMPOTENT
    assert repository.table_counts()["memory_events"] == 1
    assert repository.table_counts()["memory_source_receipts"] == 1
