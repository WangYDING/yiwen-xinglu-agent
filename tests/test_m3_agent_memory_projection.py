from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.application import (
    AgentContextFilter,
    BasicCosineMemoryRetriever,
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryQueryBuilder,
    GameNPCMemoryRetrievalConfig,
    GameNPCMemoryRetrievalService,
    MemoryIndexService,
)
from xuanyi_npc.domain import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    CaseDefinition,
    CaseSessionState,
    GoalCondition,
    GoalConditionType,
    MemoryType,
    NPCCapability,
    PlanEvaluation,
    PlanEvaluationOutcome,
    PlanEvaluationReason,
    PlanStep,
    PlanStepIntent,
    PlanStepStatus,
    PlayerContribution,
    PlayerContributionType,
    PlayerState,
    ToolName,
)
from xuanyi_npc.domain.cooperative_memory import AgentMemoryContext, AgentMemoryItem
from xuanyi_npc.memory import (
    DeterministicFakeEmbedding,
    DeterministicMemoryProjector,
    MemoryHardDeleteOperation,
    MemoryInvalidationOperation,
    MemoryLifecycleReason,
    MemoryRetrievalConfig,
    TrustedMemoryBoundary,
    stable_lifecycle_operation_id,
)
from xuanyi_npc.storage import SQLiteMemoryRepository

from .memory_helpers import reference_case_results


FIXED_TIME = datetime(2026, 8, 14, 8, 0, tzinfo=timezone.utc)


def repository_at(path: Path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(path, clock=lambda: FIXED_TIME)
    repository.initialize()
    return repository


def retrieval_config(adapter: DeterministicFakeEmbedding) -> MemoryRetrievalConfig:
    return MemoryRetrievalConfig(
        top_k=20,
        min_similarity=-1.0,
        embedding_space_id=adapter.embedding_space_id,
        query_template_version="memory_query_v1",
    )


def project_reference(
    repository: SQLiteMemoryRepository,
    case: CaseDefinition,
    player: PlayerState,
    *,
    session_id: str,
    index: int = 0,
) -> str:
    _, results = reference_case_results(case, player, session_id=session_id)
    before, result = results[index]
    source, memory = DeterministicMemoryProjector().project_committed_event(
        event=result.events[0],
        case=case,
        player=player,
        session=result.session,
        source_revision=before.revision + 1,
    )
    repository.write_projection(source, memory)
    return memory.memory_id


def current_observation(
    case: CaseDefinition,
    player: PlayerState,
    *,
    session_id: str = "session_current_m3",
) :
    return AgentContextFilter().case_observation(
        case,
        player,
        CaseSessionState(
            session_id=session_id,
            case_id=case.case_id,
            player_id=player.player_id,
        ),
    )


def goal(turn_id: str = "turn_m3") -> AgentGoalState:
    return AgentGoalState(
        goal_id="goal_gather_evidence",
        goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="继续收集公开证据。",
        status=AgentGoalStatus.ACTIVE,
        priority=70,
        completion_condition=GoalCondition(
            condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
            threshold=2,
        ),
        created_turn_id=turn_id,
        updated_turn_id=turn_id,
    )


def plan() -> AgentPlan:
    condition = GoalCondition(
        condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
        threshold=2,
    )
    return AgentPlan(
        plan_id="plan_m3",
        goal_id="goal_gather_evidence",
        status=AgentPlanStatus.ACTIVE,
        steps=(
            PlanStep(
                step_id="step_question",
                ordinal=0,
                intent=PlanStepIntent.QUESTION,
                capability=NPCCapability.USE_TOOL,
                suggested_tool=ToolName.QUESTION_PATIENT,
                public_target_id="patient_merchant",
                public_summary="先补充问诊。",
                completion_signal=condition,
                status=PlanStepStatus.ACTIVE,
            ),
            PlanStep(
                step_id="step_analyze",
                ordinal=1,
                intent=PlanStepIntent.ANALYZE_EVIDENCE,
                capability=NPCCapability.EXPLAIN,
                public_summary="再核对证据关系。",
                completion_signal=condition,
                status=PlanStepStatus.PENDING,
            ),
        ),
        current_step_index=0,
        based_on_observation_revision=0,
        created_turn_id="turn_m3",
        updated_turn_id="turn_m3",
    )


def evaluation() -> PlanEvaluation:
    return PlanEvaluation(
        evaluation_id="eval_m3",
        plan_id="plan_m3",
        outcome=PlanEvaluationOutcome.REVISE_PLAN,
        reason_code=PlanEvaluationReason.PLAYER_CONTRIBUTION_CHANGES_PRIORITY,
        observation_revision_before=0,
        observation_revision_after=0,
        next_goal_status=AgentGoalStatus.ACTIVE,
        public_summary="玩家提出了新的公开调查方向。",
        evaluated_turn_id="turn_m3_prev",
    )


def contribution() -> PlayerContribution:
    return PlayerContribution(
        contribution_id="contrib_m3",
        player_id="player_apprentice",
        case_id="old_paper_umbrella",
        session_id="session_current_m3",
        contribution_type=PlayerContributionType.SUGGESTION,
        public_text="我怀疑环境痕迹更重要，可以先查物件或地点。",
        created_at=FIXED_TIME,
    )


def make_service(
    repository: SQLiteMemoryRepository,
    adapter: DeterministicFakeEmbedding,
    *,
    projection_config: GameNPCMemoryRetrievalConfig | None = None,
) -> GameNPCMemoryRetrievalService:
    return GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=adapter),
        retrieval_config=retrieval_config(adapter),
        projection_policy=GameNPCMemoryProjectionPolicy(
            repository=repository,
            clock=lambda: FIXED_TIME,
        ),
        projection_config=projection_config,
    )


def test_query_builder_uses_only_public_cooperative_state(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    query = GameNPCMemoryQueryBuilder().build(
        turn_id="turn_m3",
        observation=current_observation(case_definition, qualified_player_state),
        current_goal=goal(),
        current_plan=plan(),
        player_contribution=contribution(),
        last_plan_evaluation=evaluation(),
    )
    payload = json.loads(query.text)

    assert payload["case"]["title"] == case_definition.title
    assert payload["current_goal"]["goal_type"] == "gather_evidence"
    assert payload["current_plan"]["steps"][0]["suggested_tool"] == "question_patient"
    assert payload["player_belief"]["text"] == contribution().public_text
    assert payload["last_plan_evaluation"]["outcome"] == "revise_plan"
    forbidden = (
        "root_cause",
        "causal_chain",
        "hidden_information",
        "valid_diagnosis_ids",
        "treatment_outcomes",
        "unsafe_treatment_penalty",
        "diagnosis_correct",
    )
    assert not any(item in query.text for item in forbidden)
    assert case_definition.root_cause not in query.text


def test_query_builder_bounds_long_context_without_validation_failure(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    long_text = "公开语义锚点" * 140
    observation = current_observation(case_definition, qualified_player_state).model_copy(
        update={"synopsis": long_text, "patient_public_profile": long_text}
    )
    long_goal = goal().model_copy(update={"public_description": "目标优先保留" + long_text})
    long_plan = plan().model_copy(update={
        "steps": tuple(
            item.model_copy(update={"public_summary": f"当前步骤优先保留{index}" + long_text})
            for index, item in enumerate(plan().steps)
        )
    })
    long_evaluation = evaluation().model_copy(
        update={"public_summary": "低优先级评价" + long_text}
    )
    long_contribution = contribution().model_copy(
        update={"public_text": "玩家当前意图优先保留" + long_text}
    )

    query = GameNPCMemoryQueryBuilder().build(
        turn_id="turn_long_context",
        observation=observation,
        current_goal=long_goal,
        current_plan=long_plan,
        player_contribution=long_contribution,
        last_plan_evaluation=long_evaluation,
    )

    assert len(query.text) <= 2000


def test_query_budget_preserves_player_goal_and_current_step_before_history(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    filler = "次要公开历史" * 180
    value = plan().model_copy(update={
        "steps": tuple(
            item.model_copy(update={"public_summary": "CURRENT_STEP_SENTINEL" + filler})
            if index == plan().current_step_index else item.model_copy(update={"public_summary": filler})
            for index, item in enumerate(plan().steps)
        )
    })
    query = GameNPCMemoryQueryBuilder(max_query_chars=1200).build(
        turn_id="turn_priority",
        observation=current_observation(case_definition, qualified_player_state).model_copy(
            update={"synopsis": filler, "patient_public_profile": filler}
        ),
        current_goal=goal().model_copy(update={"public_description": "GOAL_SENTINEL" + filler}),
        current_plan=value,
        player_contribution=contribution().model_copy(
            update={"public_text": "PLAYER_INTENT_SENTINEL" + filler}
        ),
        last_plan_evaluation=evaluation().model_copy(update={"public_summary": filler}),
    )
    payload = json.loads(query.text)

    assert len(query.text) <= 1200
    assert payload["player_belief"]["text"].startswith("PLAYER_INTENT_SENTINEL")
    assert payload["current_goal"]["public_description"].startswith("GOAL_SENTINEL")
    assert payload["current_plan"]["steps"][0]["public_summary"].startswith(
        "CURRENT_STEP_SENTINEL"
    )
    assert "last_plan_evaluation" not in payload


def test_retrieval_projects_bounded_context_without_raw_records(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    memory_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_history_m3",
    )
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )

    context = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            allow_conflicting_memory=True,
            min_relevance=-1.0,
        ),
    ).retrieve(
        turn_id="turn_m3",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
        current_goal=goal(),
        current_plan=plan(),
        player_contribution=contribution(),
        last_plan_evaluation=evaluation(),
    )

    assert isinstance(context, AgentMemoryContext)
    assert context.candidate_memory_ids == (memory_id,)
    assert context.selected_memory_ids == (memory_id,)
    assert context.selected_count == 1
    assert context.memories[0].source_episode_id == "session_history_m3"
    assert context.memories[0].source_case_id == case_definition.case_id
    assert context.memories[0].last_verified_at == FIXED_TIME
    assert set(AgentMemoryItem.model_fields) == {
        "memory_id",
        "memory_type",
        "public_summary",
        "source_type",
        "source_episode_id",
        "source_case_id",
        "relevance_score",
        "confidence",
        "reason_code",
        "occurred_at",
        "last_verified_at",
        "conflict_with_current_observation",
    }
    dumped = context.model_dump_json()
    assert "content_hash" not in dumped
    assert "public_payload_hash" not in dumped
    assert "source_revision" not in dumped
    assert "relationship_impacts" not in dumped


def test_inactive_superseded_invalidated_and_tombstoned_memory_do_not_enter_context(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    invalid_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_invalid_m3",
        index=0,
    )
    deleted_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_deleted_m3",
        index=1,
    )
    kept_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_kept_m3",
        index=2,
    )
    repository.invalidate_memory(
        MemoryInvalidationOperation(
            operation_id=stable_lifecycle_operation_id(
                "invalidate",
                qualified_player_state.player_id,
                invalid_id,
                "request_invalid_m3",
            ),
            request_id="request_invalid_m3",
            player_id=qualified_player_state.player_id,
            target_memory_id=invalid_id,
            reason=MemoryLifecycleReason.SOURCE_REVOKED,
            trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
            occurred_at=FIXED_TIME,
        )
    )
    repository.hard_delete_memory(
        MemoryHardDeleteOperation(
            operation_id=stable_lifecycle_operation_id(
                "hard_delete",
                qualified_player_state.player_id,
                deleted_id,
                "request_delete_m3",
            ),
            request_id="request_delete_m3",
            player_id=qualified_player_state.player_id,
            target_memory_id=deleted_id,
            reason=MemoryLifecycleReason.PRIVACY_REQUEST,
            trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
            occurred_at=FIXED_TIME,
        )
    )
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )

    context = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            allow_conflicting_memory=True,
            min_relevance=-1.0,
        ),
    ).retrieve(
        turn_id="turn_m3",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )

    assert kept_id in context.candidate_memory_ids
    assert invalid_id not in context.candidate_memory_ids
    assert deleted_id not in context.candidate_memory_ids
    assert context.selected_memory_ids == (kept_id,)


def test_player_ownership_isolation_and_current_episode_exclusion(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    other_player = qualified_player_state.model_copy(
        update={"player_id": "player_other_m3", "display_name": "Other"}
    )
    own_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_own_m3",
    )
    current_episode_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_current_m3",
        index=1,
    )
    other_id = project_reference(
        repository,
        case_definition,
        other_player,
        session_id="session_other_m3",
    )
    adapter = DeterministicFakeEmbedding()
    index = MemoryIndexService(repository=repository, adapter=adapter)
    index.index_player(player_id=qualified_player_state.player_id)
    index.index_player(player_id=other_player.player_id)

    context = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            allow_conflicting_memory=True,
            min_relevance=-1.0,
        ),
    ).retrieve(
        turn_id="turn_m3",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )

    assert own_id in context.candidate_memory_ids
    assert current_episode_id not in context.candidate_memory_ids
    assert other_id not in context.candidate_memory_ids


def test_top_k_char_budget_duplicate_and_irrelevant_filtering(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    first_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_dup_a_m3",
    )
    duplicate_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_dup_b_m3",
    )
    project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_extra_m3",
        index=1,
    )
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )

    bounded = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            max_selected=1,
            char_budget=120,
            min_relevance=-1.0,
            allow_conflicting_memory=True,
        ),
    ).retrieve(
        turn_id="turn_m3",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )

    assert bounded.selected_count == 1
    assert bounded.selected_chars <= 120
    assert len(bounded.selected_memory_ids) == 1

    deduped = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            max_selected=4,
            char_budget=900,
            min_relevance=-1.0,
            allow_conflicting_memory=True,
        ),
    ).retrieve(
        turn_id="turn_m3_dedup",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )
    assert not ({first_id, duplicate_id} <= set(deduped.selected_memory_ids))

    irrelevant_filtered = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            max_selected=4,
            char_budget=900,
            min_relevance=0.99,
        ),
    ).retrieve(
        turn_id="turn_m3_irrelevant",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )
    assert irrelevant_filtered.selected_count == 0
    assert irrelevant_filtered.selected_memory_ids == ()


def test_memory_conflicting_with_current_observation_is_not_promoted_to_fact(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    memory_id = project_reference(
        repository,
        case_definition,
        qualified_player_state,
        session_id="session_same_case_history_m3",
        index=0,
    )
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=qualified_player_state.player_id
    )

    filtered = make_service(repository, adapter).retrieve(
        turn_id="turn_m3_conflict",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )
    assert memory_id in filtered.candidate_memory_ids
    assert filtered.selected_memory_ids == ()

    marked = make_service(
        repository,
        adapter,
        projection_config=GameNPCMemoryRetrievalConfig(
            allow_conflicting_memory=True,
            min_relevance=-1.0,
        ),
    ).retrieve(
        turn_id="turn_m3_conflict_debug",
        player_id=qualified_player_state.player_id,
        current_session_id="session_current_m3",
        observation=current_observation(case_definition, qualified_player_state),
    )
    assert marked.selected_memory_ids == (memory_id,)
    assert marked.memories[0].conflict_with_current_observation is True
    assert marked.memories[0].confidence <= 0.35
    assert "不能作为当前事实" in marked.memories[0].public_summary
