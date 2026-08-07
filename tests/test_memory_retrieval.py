from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.application import BasicCosineMemoryRetriever, MemoryIndexService
from xuanyi_npc.domain import CaseDefinition, PlayerState
from xuanyi_npc.memory import (
    DeterministicFakeEmbedding,
    DeterministicMemoryProjector,
    DerivedEmbeddingRecord,
    EmbeddedItem,
    EmbeddingBatchResult,
    EmbeddingRequest,
    EmbeddingSpaceMismatchError,
    EmbeddingWriteDisposition,
    FAKE_EMBEDDING_SPACE_ID,
    MemoryCorrectionOperation,
    MemoryHardDeleteOperation,
    MemoryEmbeddingConflictError,
    MemoryIndexIncompleteError,
    MemoryIndexStatus,
    MemoryInvalidationOperation,
    MemoryLifecycleReason,
    MemoryNotFoundError,
    MemoryPlayerIsolationError,
    MemoryRetrievalConfig,
    MemoryStatus,
    MemoryStorageError,
    TrustedMemoryBoundary,
    stable_lifecycle_operation_id,
)
from xuanyi_npc.storage import SQLiteMemoryRepository

from .memory_helpers import reference_case_results


FIXED_TIME = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


class ConstantEmbedding:
    algorithm_version = "constant_test_v1"
    embedding_space_id = "constant_test_v1_d2"
    dimension = 2

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        self.calls += 1
        if request.embedding_space_id != self.embedding_space_id:
            raise EmbeddingSpaceMismatchError("wrong constant test space")
        return EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=tuple(
                EmbeddedItem(item_id=item.item_id, vector=(1.0, 0.0))
                for item in request.items
            ),
        )


class OrthogonalQueryEmbedding(ConstantEmbedding):
    algorithm_version = "orthogonal_query_test_v1"
    embedding_space_id = "orthogonal_query_test_v1_d2"

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        self.calls += 1
        return EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=tuple(
                EmbeddedItem(
                    item_id=item.item_id,
                    vector=(0.0, 1.0)
                    if item.item_id == "memory_query"
                    else (1.0, 0.0),
                )
                for item in request.items
            ),
        )


class FailingVectorRepository(SQLiteMemoryRepository):
    def __init__(self, database_path: Path, *, fail_at: str) -> None:
        super().__init__(database_path, clock=lambda: FIXED_TIME)
        self.fail_at = fail_at

    def _fault_point(self, name: str) -> None:
        if name == self.fail_at:
            raise RuntimeError("injected vector transaction failure")


def repository_at(path: Path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(path, clock=lambda: FIXED_TIME)
    repository.initialize()
    return repository


def write_reference_memories(
    repository: SQLiteMemoryRepository,
    case: CaseDefinition,
    player: PlayerState,
    *,
    count: int,
    session_id: str,
) -> tuple[str, ...]:
    _, results = reference_case_results(case, player, session_id=session_id)
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


def config_for(
    adapter: ConstantEmbedding | DeterministicFakeEmbedding,
    *,
    top_k: int = 20,
    minimum: float = -1.0,
) -> MemoryRetrievalConfig:
    return MemoryRetrievalConfig(
        top_k=top_k,
        min_similarity=minimum,
        embedding_space_id=adapter.embedding_space_id,
        query_template_version="memory_query_v1",
    )


def test_index_missing_is_explicit_but_no_active_memory_is_a_true_empty_result(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    adapter = ConstantEmbedding()
    retriever = BasicCosineMemoryRetriever(repository=repository, adapter=adapter)
    empty = retriever.retrieve(
        player_id=qualified_player_state.player_id,
        query_text="public query",
        config=config_for(adapter),
    )
    assert empty.index_state.status is MemoryIndexStatus.NO_ACTIVE_MEMORY
    assert empty.hits == ()
    assert adapter.calls == 0

    memory_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
        session_id="session_missing_index",
    )[0]
    with pytest.raises(MemoryIndexIncompleteError) as exc_info:
        retriever.retrieve(
            player_id=qualified_player_state.player_id,
            query_text="public query",
            config=config_for(adapter),
        )
    assert exc_info.value.index_state.status is MemoryIndexStatus.INCOMPLETE
    assert exc_info.value.index_state.missing_memory_ids == (memory_id,)
    assert adapter.calls == 0


def test_index_is_idempotent_and_top_k_uses_similarity_then_memory_id(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    memory_ids = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=8,
        session_id="session_top_k",
    )
    adapter = ConstantEmbedding()
    index = MemoryIndexService(
        repository=repository,
        adapter=adapter,
        clock=lambda: FIXED_TIME,
    )

    first = index.index_player(player_id=qualified_player_state.player_id)
    second = index.index_player(player_id=qualified_player_state.player_id)

    assert first.state.status is MemoryIndexStatus.COMPLETE
    assert {item.disposition for item in first.write_results} == {
        EmbeddingWriteDisposition.CREATED
    }
    assert {item.disposition for item in second.write_results} == {
        EmbeddingWriteDisposition.IDEMPOTENT
    }
    memories = repository.list_memories(
        player_id=qualified_player_state.player_id,
        include_inactive=False,
    )
    assert {memory.importance for memory in memories} == {2, 3, 4}
    assert len({memory.occurred_at for memory in memories}) == 8
    result = BasicCosineMemoryRetriever(
        repository=repository,
        adapter=adapter,
    ).retrieve(
        player_id=qualified_player_state.player_id,
        query_text="any query",
        config=config_for(adapter, top_k=2, minimum=1.0),
    )
    assert tuple(hit.memory_id for hit in result.hits) == tuple(sorted(memory_ids))[:2]
    assert all(hit.similarity == pytest.approx(1.0) for hit in result.hits)


def test_complete_index_with_no_score_at_threshold_returns_true_empty(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=2,
        session_id="session_threshold_empty",
    )
    adapter = OrthogonalQueryEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )

    result = BasicCosineMemoryRetriever(
        repository=repository,
        adapter=adapter,
    ).retrieve(
        player_id=qualified_player_state.player_id,
        query_text="orthogonal query",
        config=config_for(adapter, minimum=0.1),
    )

    assert result.index_state.status is MemoryIndexStatus.COMPLETE
    assert result.hits == ()


def test_player_filter_excludes_a_high_similarity_other_player_bait(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    player_a = qualified_player_state
    player_b = qualified_player_state.model_copy(
        update={"player_id": "player_other_bait", "display_name": "乙方玩家"}
    )
    memory_a = write_reference_memories(
        repository,
        case_definition,
        player_a,
        count=1,
        session_id="session_player_a",
    )[0]
    memory_b = write_reference_memories(
        repository,
        case_definition,
        player_b,
        count=1,
        session_id="session_player_b",
    )[0]
    adapter = ConstantEmbedding()
    index = MemoryIndexService(repository=repository, adapter=adapter)
    index.index_player(player_id=player_a.player_id)
    index.index_player(player_id=player_b.player_id)

    result = BasicCosineMemoryRetriever(
        repository=repository,
        adapter=adapter,
    ).retrieve(
        player_id=player_a.player_id,
        query_text="identical similarity bait",
        config=config_for(adapter),
    )

    assert tuple(hit.memory_id for hit in result.hits) == (memory_a,)
    assert memory_b not in {hit.memory_id for hit in result.hits}
    with pytest.raises(MemoryPlayerIsolationError):
        repository.get_embedding(
            player_id=player_a.player_id,
            memory_id=memory_b,
            embedding_space_id=adapter.embedding_space_id,
        )


def test_content_hash_staleness_is_rejected_then_explicitly_rebuilt(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    database_path = tmp_path / "memory.sqlite3"
    repository = repository_at(database_path)
    memory_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
        session_id="session_stale_index",
    )[0]
    adapter = ConstantEmbedding()
    index = MemoryIndexService(repository=repository, adapter=adapter)
    index.index_player(player_id=qualified_player_state.player_id)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE memory_embeddings SET content_hash=? WHERE memory_id=?",
            ("0" * 64, memory_id),
        )

    state = index.inspect_index(player_id=qualified_player_state.player_id)
    assert state.stale_memory_ids == (memory_id,)
    with pytest.raises(MemoryIndexIncompleteError):
        BasicCosineMemoryRetriever(
            repository=repository,
            adapter=adapter,
        ).retrieve(
            player_id=qualified_player_state.player_id,
            query_text="query",
            config=config_for(adapter),
        )

    rebuilt = index.index_player(player_id=qualified_player_state.player_id)
    assert rebuilt.write_results[0].disposition is EmbeddingWriteDisposition.REBUILT
    assert rebuilt.state.status is MemoryIndexStatus.COMPLETE


def test_one_embedding_space_cannot_mix_vector_dimensions(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    first_id, second_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=2,
        session_id="session_fixed_dimension",
    )
    adapter = ConstantEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )
    assert repository.get_embedding(
        player_id=qualified_player_state.player_id,
        memory_id=first_id,
        embedding_space_id=adapter.embedding_space_id,
    ).dimension == 2
    second = repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=second_id,
    )
    conflicting = DerivedEmbeddingRecord(
        memory_id=second.memory_id,
        player_id=second.player_id,
        embedding_space_id=adapter.embedding_space_id,
        content_hash=second.content_hash,
        dimension=3,
        vector=(1.0, 0.0, 0.0),
        l2_norm=1.0,
        generated_at=FIXED_TIME,
    )

    with pytest.raises(MemoryEmbeddingConflictError):
        repository.write_embeddings(
            player_id=qualified_player_state.player_id,
            records=(conflicting,),
        )


def test_delete_and_rebuild_produce_the_same_retrieval_result(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=3,
        session_id="session_rebuild",
    )
    adapter = DeterministicFakeEmbedding()
    index = MemoryIndexService(repository=repository, adapter=adapter)
    index.index_player(player_id=qualified_player_state.player_id)
    retriever = BasicCosineMemoryRetriever(repository=repository, adapter=adapter)
    config = config_for(adapter, top_k=3)
    before = retriever.retrieve(
        player_id=qualified_player_state.player_id,
        query_text="查看病患异常和物证",
        config=config,
    )

    assert repository.delete_embeddings(
        player_id=qualified_player_state.player_id,
        embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
    ) == 3
    with pytest.raises(MemoryIndexIncompleteError):
        retriever.retrieve(
            player_id=qualified_player_state.player_id,
            query_text="查看病患异常和物证",
            config=config,
        )
    index.rebuild_player(player_id=qualified_player_state.player_id)
    after = retriever.retrieve(
        player_id=qualified_player_state.player_id,
        query_text="查看病患异常和物证",
        config=config,
    )

    assert tuple((hit.memory_id, hit.similarity) for hit in after.hits) == tuple(
        (hit.memory_id, hit.similarity) for hit in before.hits
    )


def test_rebuild_and_lifecycle_failures_roll_back_vector_changes(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    database_path = tmp_path / "memory.sqlite3"
    repository = repository_at(database_path)
    memory_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
        session_id="session_vector_rollback",
    )[0]
    adapter = ConstantEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )
    before = repository.get_embedding(
        player_id=qualified_player_state.player_id,
        memory_id=memory_id,
        embedding_space_id=adapter.embedding_space_id,
    )

    rebuild_failure = FailingVectorRepository(
        database_path,
        fail_at="embedding_rebuild_after_delete",
    )
    with pytest.raises(MemoryStorageError):
        MemoryIndexService(
            repository=rebuild_failure,
            adapter=adapter,
        ).rebuild_player(player_id=qualified_player_state.player_id)
    assert repository.get_embedding(
        player_id=qualified_player_state.player_id,
        memory_id=memory_id,
        embedding_space_id=adapter.embedding_space_id,
    ) == before

    lifecycle_failure = FailingVectorRepository(
        database_path,
        fail_at="lifecycle_before_commit",
    )
    operation = MemoryInvalidationOperation(
        operation_id=stable_lifecycle_operation_id(
            "invalidate",
            qualified_player_state.player_id,
            memory_id,
            "rollback_vector_invalidation",
        ),
        request_id="rollback_vector_invalidation",
        player_id=qualified_player_state.player_id,
        target_memory_id=memory_id,
        reason=MemoryLifecycleReason.SOURCE_REVOKED,
        trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
        occurred_at=FIXED_TIME,
    )
    with pytest.raises(MemoryStorageError):
        lifecycle_failure.invalidate_memory(operation)
    assert repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=memory_id,
    ).status is MemoryStatus.ACTIVE
    assert repository.get_embedding(
        player_id=qualified_player_state.player_id,
        memory_id=memory_id,
        embedding_space_id=adapter.embedding_space_id,
    ) == before


def test_correction_invalidation_and_hard_delete_clean_derived_vectors(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    original_id, delete_id = write_reference_memories(
        repository,
        case_definition,
        qualified_player_state,
        count=2,
        session_id="session_lifecycle_vectors",
    )
    adapter = ConstantEmbedding()
    index = MemoryIndexService(repository=repository, adapter=adapter)
    index.index_player(player_id=qualified_player_state.player_id)

    correction = MemoryCorrectionOperation(
        operation_id=stable_lifecycle_operation_id(
            "correct",
            qualified_player_state.player_id,
            original_id,
            "correct_vector",
        ),
        request_id="correct_vector",
        player_id=qualified_player_state.player_id,
        target_memory_id=original_id,
        reason=MemoryLifecycleReason.VERIFIED_CORRECTION,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=FIXED_TIME,
        replacement_public_content="经可信复核的公开调查记录。",
    )
    corrected = repository.correct_memory(correction)
    assert corrected.replacement_memory_id is not None
    with pytest.raises(MemoryNotFoundError):
        repository.get_embedding(
            player_id=qualified_player_state.player_id,
            memory_id=original_id,
            embedding_space_id=adapter.embedding_space_id,
        )
    assert index.inspect_index(
        player_id=qualified_player_state.player_id
    ).missing_memory_ids == (corrected.replacement_memory_id,)

    index.index_player(player_id=qualified_player_state.player_id)
    invalidation = MemoryInvalidationOperation(
        operation_id=stable_lifecycle_operation_id(
            "invalidate",
            qualified_player_state.player_id,
            corrected.replacement_memory_id,
            "invalidate_vector",
        ),
        request_id="invalidate_vector",
        player_id=qualified_player_state.player_id,
        target_memory_id=corrected.replacement_memory_id,
        reason=MemoryLifecycleReason.SOURCE_REVOKED,
        trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
        occurred_at=FIXED_TIME,
    )
    repository.invalidate_memory(invalidation)
    with pytest.raises(MemoryNotFoundError):
        repository.get_embedding(
            player_id=qualified_player_state.player_id,
            memory_id=corrected.replacement_memory_id,
            embedding_space_id=adapter.embedding_space_id,
        )

    deletion = MemoryHardDeleteOperation(
        operation_id=stable_lifecycle_operation_id(
            "hard_delete",
            qualified_player_state.player_id,
            delete_id,
            "delete_vector",
        ),
        request_id="delete_vector",
        player_id=qualified_player_state.player_id,
        target_memory_id=delete_id,
        reason=MemoryLifecycleReason.PRIVACY_REQUEST,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=FIXED_TIME,
    )
    repository.hard_delete_memory(deletion)
    assert repository.list_embeddings(
        player_id=qualified_player_state.player_id,
        embedding_space_id=adapter.embedding_space_id,
    ) == ()
    assert repository.tombstone_exists(delete_id)
    assert index.inspect_index(
        player_id=qualified_player_state.player_id
    ).status is MemoryIndexStatus.NO_ACTIVE_MEMORY


def test_retrieval_rejects_embedding_space_mismatch_before_adapter_use(
    tmp_path: Path,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    adapter = ConstantEmbedding()
    config = config_for(adapter).model_copy(update={"embedding_space_id": "other_space"})

    with pytest.raises(EmbeddingSpaceMismatchError):
        BasicCosineMemoryRetriever(repository=repository, adapter=adapter).retrieve(
            player_id=qualified_player_state.player_id,
            query_text="query",
            config=config,
        )
    assert adapter.calls == 0
