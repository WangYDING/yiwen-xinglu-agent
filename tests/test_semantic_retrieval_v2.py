from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.agents import ScriptedFakeLLM, V1DoctorAgent
from xuanyi_npc.application import (
    AgentContextFilter,
    BasicCosineMemoryRetriever,
    MemoryIndexService,
    RetrievalQueryV2Builder,
)
from xuanyi_npc.application.memory_context import V1AgentContextService
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseDefinition, PlayerState
from xuanyi_npc.memory import (
    ConservativeRetrievalConfigV2,
    DeterministicFakeEmbedding,
    DeterministicMemoryProjector,
    EmbeddingBatchResult,
    EmbeddedItem,
    EmbeddingDocumentV2Builder,
    EmbeddingRequest,
    MemoryCorrectionOperation,
    MemoryLifecycleReason,
    RepresentationIndexStatus,
    TrustedMemoryBoundary,
    bge_m3_embedding_space_id,
    stable_lifecycle_operation_id,
)
from xuanyi_npc.storage import SQLiteMemoryRepository

from .memory_helpers import reference_case_results


FIXED_TIME = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
V2_SPACE = bge_m3_embedding_space_id(
    device="cuda",
    max_input_length=512,
    representation_version="retrieval_v2",
)


class ConstantV2Embedding:
    algorithm_version = "constant_semantic_v2_test"
    embedding_space_id = V2_SPACE
    dimension = 2

    def __init__(self) -> None:
        self.text_batches: list[tuple[str, ...]] = []

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        self.text_batches.append(tuple(item.text for item in request.items))
        return EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=tuple(
                EmbeddedItem(item_id=item.item_id, vector=(1.0, 0.0))
                for item in request.items
            ),
        )


def repository_at(path: Path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(path, clock=lambda: FIXED_TIME)
    repository.initialize()
    return repository


def project_reference(
    repository: SQLiteMemoryRepository,
    case: CaseDefinition,
    player: PlayerState,
    *,
    count: int,
    session_id: str,
) -> tuple[str, ...]:
    _, results = reference_case_results(case, player, session_id=session_id)
    projector = DeterministicMemoryProjector()
    ids: list[str] = []
    for before, result in results[:count]:
        source, memory = projector.project_committed_event(
            event=result.events[0],
            case=case,
            player=player,
            session=result.session,
            source_revision=before.revision + 1,
        )
        repository.write_projection(source, memory)
        ids.append(memory.memory_id)
    return tuple(ids)


def test_retrieval_query_v2_has_a_frozen_public_only_snapshot(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(
        case_definition,
        qualified_player_state,
        session_id="episode_query_v2",
    )
    observation = AgentContextFilter().case_observation(
        case_definition,
        qualified_player_state,
        results[0][1].session,
    )

    query = RetrievalQueryV2Builder().build(
        current_user_message="  我想回忆　影子异常的旧记录。  ",
        case_observation=observation,
        fixed_lesson="固定课程绝不能进入向量查询",
    )

    assert query.model_dump() == {
        "version": "retrieval_query_v2",
        "text": (
            "我想回忆 影子异常的旧记录。 已发现线索:书生近来昼夜读书,神色疲惫。"
            "疲惫能解释困倦,却不能解释契痕。;灯火稳定时,书生的影缘仍比身体动作慢半拍。"
        ),
    }
    forbidden = (
        case_definition.synopsis,
        "固定课程",
        "fixed_lesson",
        "case_synopsis",
        "root_cause",
    )
    assert all(item not in query.text for item in forbidden)


def test_embedding_document_v2_uses_receipts_without_changing_authority(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    memory_ids = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        count=8,
        session_id="episode_document_v2",
    )
    authority_before = repository.list_memories(
        player_id=qualified_player_state.player_id,
        include_inactive=True,
    )
    builder = EmbeddingDocumentV2Builder()
    documents = []
    for memory in sorted(authority_before, key=lambda item: item.source_sequence):
        source = repository.get_source_receipt(
            player_id=memory.player_id,
            source_event_id=memory.source_event_id,
            projection_version=memory.projection_version,
            projection_ordinal=memory.projection_ordinal,
        )
        documents.append(builder.build(memory=memory, source=source).text)

    assert documents[0] == (
        "观察书生的神色、动作、影子与周围灯火表现。"
        "发现。书生近来昼夜读书,神色疲惫。疲惫能解释困倦,却不能解释契痕;"
        "灯火稳定时,书生的影缘仍比身体动作慢半拍"
    )
    assert "observe_patient" not in documents[0]
    assert "未发现新线索" not in "\n".join(documents)
    assert "玩家曾提交假设" in documents[-2]
    assert "可观察结果" in documents[-1]

    adapter = ConstantV2Embedding()
    MemoryIndexService(
        repository=repository,
        adapter=adapter,
        document_builder=builder,
    ).index_player(player_id=qualified_player_state.player_id)
    assert repository.list_memories(
        player_id=qualified_player_state.player_id,
        include_inactive=True,
    ) == authority_before
    assert set(memory_ids) == {item.memory_id for item in authority_before}


def test_v2_space_marks_old_vectors_stale_then_rebuilds_idempotently(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    project_reference(
        repository,
        case_definition,
        qualified_player_state,
        count=2,
        session_id="episode_representation_migration",
    )
    MemoryIndexService(
        repository=repository,
        adapter=DeterministicFakeEmbedding(),
    ).index_player(player_id=qualified_player_state.player_id)
    adapter = ConstantV2Embedding()
    service = MemoryIndexService(
        repository=repository,
        adapter=adapter,
        document_builder=EmbeddingDocumentV2Builder(),
    )
    memories = repository.list_memories(
        player_id=qualified_player_state.player_id,
        include_inactive=False,
    )

    stale = service.inspect_representation_candidates(
        player_id=qualified_player_state.player_id,
        memories=memories,
    )
    assert stale.status is RepresentationIndexStatus.STALE_REPRESENTATION
    assert stale.stale_representation_memory_ids == tuple(
        sorted(memory.memory_id for memory in memories)
    )
    first = service.rebuild_player(player_id=qualified_player_state.player_id)
    second = service.rebuild_player(player_id=qualified_player_state.player_id)
    assert first.state.valid_embedding_count == len(memories)
    assert second.state.valid_embedding_count == len(memories)
    ready = service.inspect_representation_candidates(
        player_id=qualified_player_state.player_id,
        memories=memories,
    )
    assert ready.status is RepresentationIndexStatus.READY
    assert repository.list_embeddings(
        player_id=qualified_player_state.player_id,
        embedding_space_id=DeterministicFakeEmbedding.embedding_space_id,
    )


def test_corrected_short_memory_is_not_expanded_by_a_code_template(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    original_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        count=1,
        session_id="episode_short_correction",
    )[0]
    operation = MemoryCorrectionOperation(
        operation_id=stable_lifecycle_operation_id(
            "correct",
            qualified_player_state.player_id,
            original_id,
            "short_correction",
        ),
        request_id="short_correction",
        player_id=qualified_player_state.player_id,
        target_memory_id=original_id,
        reason=MemoryLifecycleReason.VERIFIED_CORRECTION,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=FIXED_TIME,
        replacement_public_content="践诺",
    )
    replacement_id = repository.correct_memory(operation).replacement_memory_id
    assert replacement_id is not None
    replacement = repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=replacement_id,
    )
    source = repository.get_source_receipt(
        player_id=replacement.player_id,
        source_event_id=replacement.source_event_id,
        projection_version=replacement.projection_version,
        projection_ordinal=replacement.projection_ordinal,
    )

    document = EmbeddingDocumentV2Builder().build(
        memory=replacement,
        source=source,
    )

    assert document.text == "践诺"


def test_conservative_margin_gate_is_deterministic_and_keeps_authority_content_in_prompt(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    ids = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        count=2,
        session_id="episode_v2_prompt_history",
    )
    adapter = ConstantV2Embedding()
    document_builder = EmbeddingDocumentV2Builder()
    index = MemoryIndexService(
        repository=repository,
        adapter=adapter,
        document_builder=document_builder,
    )
    index.rebuild_player(player_id=qualified_player_state.player_id)
    retriever = BasicCosineMemoryRetriever(
        repository=repository,
        adapter=adapter,
        document_builder=document_builder,
    )
    config = ConservativeRetrievalConfigV2(
        min_similarity=-1.0,
        max_results=2,
        minimum_margin=0.1,
        embedding_space_id=V2_SPACE,
    )
    scope = AgentContextFilter().memory_scope(
        qualified_player_state,
        reference_case_results(
            case_definition,
            qualified_player_state,
            session_id="episode_v2_current",
        )[0],
    )
    assert retriever.retrieve_conservative_scoped(
        scope=scope,
        query_text="回忆过去的公开观察",
        config=config,
    ).hits == ()

    fake = ScriptedFakeLLM(
        [
            AgentAction(
                action_id="agent_v2_memory_001",
                action_type=AgentActionType.RESPOND,
                dialogue="继续。",
                confidence=0.7,
            ).model_dump_json()
        ]
    )
    no_margin = config.model_copy(update={"minimum_margin": 0.0})
    service = V1AgentContextService(
        doctor_agent=V1DoctorAgent(fake),
        retriever=retriever,
        retrieval_config=no_margin,
        query_builder=RetrievalQueryV2Builder(),
    )
    current = reference_case_results(
        case_definition,
        qualified_player_state,
        session_id="episode_v2_current",
    )[0]
    result = service.decide(
        step_index=1,
        case=case_definition,
        player=qualified_player_state,
        session=current,
        current_user_message="回忆过去的公开观察",
    )
    assert result.decision is not None
    prompt = fake.requests[0].messages[-1].content
    authority = repository.get_memory(
        player_id=qualified_player_state.player_id,
        memory_id=ids[0],
    ).content
    assert authority in prompt
    assert "embedding_document_v2" not in prompt
