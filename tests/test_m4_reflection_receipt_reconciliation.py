from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.application import MemoryIndexService
from xuanyi_npc.application.reflection_memory import ReflectionMemoryConsolidationService
from xuanyi_npc.domain.reflection import ReflectionTrigger, ReflectionTriggerType
from xuanyi_npc.domain.reflection_lifecycle import (
    ReflectionLifecycleResult,
    ReflectionLifecycleStatus,
    ReflectionProposalStatus,
)
from xuanyi_npc.domain.reflection_memory import ReflectionMemoryIndexStatus
from xuanyi_npc.memory import DeterministicFakeEmbedding, DeterministicMemoryProjector
from xuanyi_npc.storage import SQLiteMemoryRepository

from .memory_helpers import reference_case_results


NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)


def repository_at(path: Path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(path, clock=lambda: NOW)
    repository.initialize()
    return repository


def write_memories(repository, case, player, *, count: int, session_id: str):
    _, results = reference_case_results(case, player, session_id=session_id)
    projector = DeterministicMemoryProjector()
    memory_ids = []
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


def trigger_for(suffix: str) -> ReflectionTrigger:
    return ReflectionTrigger.create(
        trigger_type=ReflectionTriggerType.GOAL_COMPLETED,
        episode_id=f"episode_{suffix}",
        case_id="old_paper_umbrella",
        lifecycle_event_id=f"event_{suffix}",
        reason="A public goal completed.",
    )


def persist_result(repository, *, trigger, player_id, result):
    owner = f"owner_{trigger.trigger_id}"
    disposition, _ = repository.claim_reflection_trigger(
        trigger=trigger,
        player_id=player_id,
        owner_token=owner,
    )
    assert disposition == "acquired"
    repository.complete_reflection_trigger(
        trigger_id=trigger.trigger_id,
        owner_token=owner,
        result=result,
    )


def pending_result(trigger, memory_ids):
    return ReflectionLifecycleResult(
        trigger_id=trigger.trigger_id,
        trigger_type=trigger.trigger_type,
        status=ReflectionLifecycleStatus.INDEX_PENDING,
        proposal_status=ReflectionProposalStatus.VALID,
        reflection_attempt_count=1,
        written_memory_ids=memory_ids,
        index_status=ReflectionMemoryIndexStatus.PENDING,
        error_code="memory_embedding_conflict",
        generation_attempt_count=1,
    )


def reconcile(repository, player_id, adapter):
    return ReflectionMemoryConsolidationService(
        repository=repository,
        clock=lambda: NOW,
    ).reconcile_pending_index_receipts(
        player_id=player_id,
        embedding_space_id=adapter.embedding_space_id,
        embedding_dimension=adapter.dimension,
    )


def test_ready_receipt_reconciles_and_replays_without_losing_history(
    tmp_path, case_definition, qualified_player_state
):
    repository = repository_at(tmp_path / "memory.sqlite3")
    memory_id = write_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
        session_id="session_receipt_ready",
    )[0]
    trigger = trigger_for("ready")
    original = pending_result(trigger, (memory_id,))
    persist_result(
        repository,
        trigger=trigger,
        player_id=qualified_player_state.player_id,
        result=original,
    )
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )

    first = reconcile(repository, qualified_player_state.player_id, adapter)
    second = reconcile(repository, qualified_player_state.player_id, adapter)
    disposition, replay = repository.claim_reflection_trigger(
        trigger=trigger,
        player_id=qualified_player_state.player_id,
        owner_token="new_owner",
    )

    assert len(first) == 1
    assert second == ()
    assert first[0].status is ReflectionLifecycleStatus.COMPLETED
    assert first[0].index_status is ReflectionMemoryIndexStatus.COMPLETE
    assert first[0].error_code is None
    assert first[0].previous_error_code == "memory_embedding_conflict"
    assert first[0].previous_index_status is ReflectionMemoryIndexStatus.PENDING
    assert first[0].index_reconciled_memory_ids == (memory_id,)
    assert first[0].reflection_attempt_count == original.reflection_attempt_count
    assert first[0].generation_attempt_count == original.generation_attempt_count
    assert disposition == "replay"
    assert replay == first[0]
    assert len(repository.list_memories(player_id=qualified_player_state.player_id)) == 1


@pytest.mark.parametrize("mode", ("missing", "partial", "stale", "other_space"))
def test_receipt_remains_pending_until_every_written_memory_is_current_space_valid(
    tmp_path, case_definition, qualified_player_state, mode
):
    repository = repository_at(tmp_path / f"{mode}.sqlite3")
    memory_ids = write_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=2 if mode == "partial" else 1,
        session_id=f"session_{mode}",
    )
    trigger = trigger_for(mode)
    persist_result(
        repository,
        trigger=trigger,
        player_id=qualified_player_state.player_id,
        result=pending_result(trigger, memory_ids),
    )
    adapter = DeterministicFakeEmbedding()
    if mode == "partial":
        memory = repository.get_memory(
            player_id=qualified_player_state.player_id,
            memory_id=memory_ids[0],
        )
        records = MemoryIndexService(
            repository=repository,
            adapter=adapter,
        )._embed_memories(
            player_id=qualified_player_state.player_id,
            memories=(memory,),
        )
        repository.write_embeddings(
            player_id=qualified_player_state.player_id,
            records=records,
        )
    elif mode in {"stale", "other_space"}:
        MemoryIndexService(repository=repository, adapter=adapter).index_player(
            player_id=qualified_player_state.player_id
        )
        if mode == "stale":
            with sqlite3.connect(repository.database_path) as connection:
                connection.execute(
                    "UPDATE memory_embeddings SET content_hash=? WHERE memory_id=?",
                    ("0" * 64, memory_ids[0]),
                )

    space = "other_current_space" if mode == "other_space" else adapter.embedding_space_id
    dimension = adapter.dimension
    result = ReflectionMemoryConsolidationService(
        repository=repository,
        clock=lambda: NOW,
    ).reconcile_pending_index_receipts(
        player_id=qualified_player_state.player_id,
        embedding_space_id=space,
        embedding_dimension=dimension,
    )

    assert result == ()
    assert repository.list_pending_reflection_index_receipts(
        player_id=qualified_player_state.player_id
    )[0].status is ReflectionLifecycleStatus.INDEX_PENDING


def test_wrong_player_and_non_pending_receipts_cannot_be_upgraded(
    tmp_path, case_definition, qualified_player_state
):
    repository = repository_at(tmp_path / "memory.sqlite3")
    other = qualified_player_state.model_copy(update={"player_id": "player_other"})
    memory_id = write_memories(
        repository,
        case_definition,
        other,
        count=1,
        session_id="session_other_player",
    )[0]
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=other.player_id
    )
    pending_trigger = trigger_for("wrong_player")
    persist_result(
        repository,
        trigger=pending_trigger,
        player_id=qualified_player_state.player_id,
        result=pending_result(pending_trigger, (memory_id,)),
    )
    fallback_trigger = trigger_for("fallback")
    fallback = pending_result(fallback_trigger, (memory_id,)).model_copy(
        update={"status": ReflectionLifecycleStatus.FALLBACK}
    )
    persist_result(
        repository,
        trigger=fallback_trigger,
        player_id=qualified_player_state.player_id,
        result=fallback,
    )
    processing_trigger = trigger_for("processing")
    repository.claim_reflection_trigger(
        trigger=processing_trigger,
        player_id=qualified_player_state.player_id,
        owner_token="processing_owner",
    )

    assert reconcile(repository, qualified_player_state.player_id, adapter) == ()
    pending = repository.list_pending_reflection_index_receipts(
        player_id=qualified_player_state.player_id
    )
    assert tuple(item.trigger_id for item in pending) == (pending_trigger.trigger_id,)


def test_normal_success_receipt_is_a_reconciliation_noop(
    tmp_path, qualified_player_state
):
    repository = repository_at(tmp_path / "memory.sqlite3")
    trigger = trigger_for("already_complete")
    completed = ReflectionLifecycleResult(
        trigger_id=trigger.trigger_id,
        trigger_type=trigger.trigger_type,
        status=ReflectionLifecycleStatus.COMPLETED,
        proposal_status=ReflectionProposalStatus.VALID,
        reflection_attempt_count=1,
        written_memory_ids=("memory_already_complete",),
        index_status=ReflectionMemoryIndexStatus.COMPLETE,
        generation_attempt_count=1,
    )
    persist_result(
        repository,
        trigger=trigger,
        player_id=qualified_player_state.player_id,
        result=completed,
    )

    assert reconcile(
        repository,
        qualified_player_state.player_id,
        DeterministicFakeEmbedding(),
    ) == ()
    disposition, replay = repository.claim_reflection_trigger(
        trigger=trigger,
        player_id=qualified_player_state.player_id,
        owner_token="replay_owner",
    )
    assert disposition == "replay"
    assert replay == completed
