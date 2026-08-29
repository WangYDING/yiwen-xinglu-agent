from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from xuanyi_npc.application import (
    BasicCosineMemoryRetriever,
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalConfig,
    GameNPCMemoryRetrievalService,
    MemoryIndexService,
)
from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
from xuanyi_npc.application.multicase import CreatePlayerInput, StartEpisodeInput
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind,
    CooperativeTurnStatus,
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContribution,
    PlayerContributionEvaluation,
    PlayerContributionType,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_memory import (
    AgentMemoryContext,
    AgentMemoryItem,
    AgentMemorySourceType,
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
)
from xuanyi_npc.domain.cooperative_planning import GoalCondition, GoalConditionType, PlanStepIntent
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalUpdateKind,
    GoalUpdateProposal,
    MemoryUsageProposal,
    PlanDraft,
    PlanStepDraft,
    PlanUpdateKind,
    PlanUpdateProposal,
)
from tests.cooperative_runtime_helpers import build_service
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


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


class RuntimeMemoryService:
    def __init__(self, contexts=None, *, fail=False):
        self.contexts = list(contexts or [])
        self.fail = fail
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("memory unavailable")
        return self.contexts.pop(0) if self.contexts else memory_context()


class MemoryAwarePlanningAgent:
    config = object()
    runtime_kind = AgentRuntimeKind.TEST_DOUBLE

    def __init__(self, *, mode: str) -> None:
        self.mode = mode
        self.inputs = []

    def propose_turn(self, value):
        self.inputs.append(value)
        if self.mode == "second_tool_when_memory" and value.memory_context and value.memory_context.selected_memory_ids:
            return proposal(value, index=1, use_tool=True, memory_id=value.memory_context.selected_memory_ids[0], influence="tool_priority")
        if self.mode == "plan_memory" and value.memory_context and value.memory_context.selected_memory_ids:
            return proposal(value, index=1, use_tool=False, memory_id=value.memory_context.selected_memory_ids[0], influence="plan_priority")
        if self.mode == "irrelevant":
            return proposal(value, index=0, use_tool=False)
        if self.mode == "conflicting":
            return proposal(value, index=0, use_tool=False)
        if self.mode == "treatment_bait":
            diagnosis_id = value.case_observation.diagnosis_candidates[0].diagnosis_id
            action = AgentAction(
                action_id=f"npc_{value.turn_id}",
                action_type=AgentActionType.USE_TOOL,
                dialogue="我只提出诊断协商，不执行治疗。",
                tool_call=ToolCallRequest(
                    name="submit_diagnosis",
                    arguments={"diagnosis_id": diagnosis_id, "evidence_clue_ids": []},
                ),
                confidence=0.5,
            )
            return proposal(value, index=0, use_tool=False, action=action, capability=NPCCapability.PROPOSE_DIAGNOSIS)
        return proposal(value, index=0, use_tool=False)

    def repair_action_contract(self, value, prior, feedback):
        raise AssertionError("test proposal should satisfy action contract")

    def action_contract_fallback(self, prior):
        raise AssertionError("test proposal should not need fallback")


def opened_case(root: Path):
    service = build_service(root)
    created = service.create_player(CreatePlayerInput(display_name="M3记忆玩家"))
    opened = service.start_episode(StartEpisodeInput(player_id=created.player_id, case_id="old_paper_umbrella"))
    assert opened.ok and opened.observation is not None and opened.session_id is not None
    return service, created.player_id, opened


def contribution(player_id, session_id, turn_id="turn_m3_runtime", text="建议按公开证据推进。"):
    return PlayerContribution(
        contribution_id=turn_id,
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=session_id,
        contribution_type=PlayerContributionType.SUGGESTION,
        public_text=text,
        created_at=NOW,
    )


def memory_item(memory_id: str, summary: str, *, conflict=False) -> AgentMemoryItem:
    return AgentMemoryItem(
        memory_id=memory_id,
        memory_type=MemoryType.EPISODIC,
        public_summary=summary,
        source_type=AgentMemorySourceType.INVESTIGATION_COMPLETED,
        source_episode_id=f"episode_{memory_id}",
        source_case_id="case_history",
        relevance_score=0.8,
        confidence=0.8 if not conflict else 0.3,
        reason_code="investigation_completed",
        occurred_at=NOW,
        last_verified_at=NOW,
        conflict_with_current_observation=conflict,
    )


def memory_context(*items: AgentMemoryItem) -> AgentMemoryContext:
    ids = tuple(item.memory_id for item in items)
    return AgentMemoryContext(
        retrieval_id="retrieval_m3_runtime",
        query_basis="public runtime query",
        normalized_query="public runtime query",
        memories=items,
        retrieval_summary=f"selected {len(items)} memories",
        candidate_memory_ids=ids,
        selected_memory_ids=ids,
        total_candidates=len(items),
        selected_count=len(items),
        max_selected=4,
        char_budget=900,
        selected_chars=sum(len(item.public_summary) for item in items),
        embedding_space_id="fake_space",
        query_template_version="game_npc_memory_query_v1",
        index_status="complete",
        active_memory_count=len(items),
        valid_embedding_count=len(items),
    )


def proposal(value, *, index: int, use_tool: bool, memory_id=None, influence=None, action=None, capability=None):
    option = value.case_observation.available_investigations[index]
    tool = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
    plan = PlanDraft(steps=(
        PlanStepDraft(
            intent=PlanStepIntent.INVESTIGATE,
            capability=NPCCapability.USE_TOOL,
            suggested_tool=tool,
            public_target_id=option.investigation_id,
            public_summary=f"调查公开目标 {option.investigation_id}",
            completion_signal=GoalCondition(
                condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
                reference_id=option.investigation_id,
            ),
        ),
        PlanStepDraft(
            intent=PlanStepIntent.DISCUSS_WITH_PLAYER,
            capability=NPCCapability.EXPLAIN,
            public_summary="与玩家核对证据。",
            completion_signal=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=3),
        ),
    ))
    if action is None:
        action = AgentAction(
            action_id=f"npc_{value.turn_id}",
            action_type=AgentActionType.USE_TOOL if use_tool else AgentActionType.RESPOND,
            dialogue="按当前公开计划推进。",
            tool_call=(
                ToolCallRequest(name=tool, arguments={"investigation_id": option.investigation_id})
                if use_tool
                else None
            ),
            confidence=0.7,
        )
    usage = None
    if memory_id is not None:
        usage = MemoryUsageProposal(
            used_memory_ids=(memory_id,),
            influence_types=(influence,),
            affected_plan=influence == "plan_priority",
            affected_tool_priority=influence == "tool_priority",
            affected_decision=influence == "tool_priority",
            public_effect_summary="根据历史经验调整公开行动优先级。",
        )
    return GameNPCTurnProposal(
        goal_update=GoalUpdateProposal(update=GoalUpdateKind.KEEP, public_rationale="保持当前目标。"),
        plan_update=PlanUpdateProposal(update=PlanUpdateKind.CREATE, draft=plan, public_rationale="形成短计划。"),
        decision=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=value.player_contribution.contribution_id,
                disposition=SuggestionDisposition.PARTIAL_ACCEPT,
                reason_code="public_memory_context",
                explanation="历史经验只作为非权威参考。",
            ),
            capability=capability or (NPCCapability.USE_TOOL if use_tool else NPCCapability.EXPLAIN),
            action=action,
            explanation="本轮仍最多一个行动。",
        ),
        memory_usage=usage,
    )


def test_runtime_retrieves_memory_before_agent_and_relevant_memory_changes_plan(tmp_path: Path) -> None:
    service_a, player_a, opened_a = opened_case(tmp_path / "a")
    service_b, player_b, opened_b = opened_case(tmp_path / "b")
    empty = RuntimeMemoryService([memory_context()])
    relevant = RuntimeMemoryService([memory_context(memory_item("memory_plan", "过去类似情况先检查环境更有效。"))])

    baseline = CooperativeRuntime(service=service_a, agent=MemoryAwarePlanningAgent(mode="plan_memory"), memory_service=empty).handle(
        CooperativeTurnInput(contribution=contribution(player_a, opened_a.session_id))
    )
    changed = CooperativeRuntime(service=service_b, agent=MemoryAwarePlanningAgent(mode="plan_memory"), memory_service=relevant).handle(
        CooperativeTurnInput(contribution=contribution(player_b, opened_b.session_id))
    )

    assert len(empty.calls) == 1
    assert len(relevant.calls) == 1
    assert baseline.plan_public_summary[0] != changed.plan_public_summary[0]
    assert changed.memory_retrieval_status is MemoryRetrievalStatus.SUCCESS
    assert changed.memory_usage_trace.accepted_used_memory_ids == ("memory_plan",)
    assert changed.memory_usage_trace.plan_changed is True


def test_runtime_relevant_memory_changes_legal_tool_priority(tmp_path: Path) -> None:
    service_a, player_a, opened_a = opened_case(tmp_path / "tool_a")
    service_b, player_b, opened_b = opened_case(tmp_path / "tool_b")
    baseline_agent = MemoryAwarePlanningAgent(mode="default")
    memory_agent = MemoryAwarePlanningAgent(mode="second_tool_when_memory")

    baseline = CooperativeRuntime(service=service_a, agent=baseline_agent, memory_service=RuntimeMemoryService([memory_context()])).handle(
        CooperativeTurnInput(contribution=contribution(player_a, opened_a.session_id))
    )
    changed = CooperativeRuntime(
        service=service_b,
        agent=memory_agent,
        memory_service=RuntimeMemoryService([memory_context(memory_item("memory_tool", "过去第二项公开调查更有效。"))]),
    ).handle(CooperativeTurnInput(contribution=contribution(player_b, opened_b.session_id)))

    assert baseline.status is CooperativeTurnStatus.RESPONDED
    assert changed.status is CooperativeTurnStatus.ACTION_EXECUTED
    assert changed.selected_tool is not None
    assert changed.memory_usage_trace.tool_priority_influenced is True
    assert changed.memory_usage_trace.accepted_used_memory_ids == ("memory_tool",)
    assert len(service_b.state_store.load_case_session(opened_b.session_id).action_history) == 1


def test_runtime_irrelevant_memory_is_noop_and_declares_no_usage(tmp_path: Path) -> None:
    service_a, player_a, opened_a = opened_case(tmp_path / "noop_a")
    service_b, player_b, opened_b = opened_case(tmp_path / "noop_b")
    agent_a = MemoryAwarePlanningAgent(mode="irrelevant")
    agent_b = MemoryAwarePlanningAgent(mode="irrelevant")

    baseline = CooperativeRuntime(service=service_a, agent=agent_a, memory_service=RuntimeMemoryService([memory_context()])).handle(
        CooperativeTurnInput(contribution=contribution(player_a, opened_a.session_id))
    )
    irrelevant = CooperativeRuntime(
        service=service_b,
        agent=agent_b,
        memory_service=RuntimeMemoryService([memory_context(memory_item("memory_irrelevant", "过去玩家喜欢先观察颜色。"))]),
    ).handle(CooperativeTurnInput(contribution=contribution(player_b, opened_b.session_id)))

    assert baseline.plan_public_summary == irrelevant.plan_public_summary
    assert irrelevant.memory_usage_trace.declared_used_memory_ids == ()
    assert irrelevant.memory_usage_trace.accepted_used_memory_ids == ()
    assert irrelevant.memory_usage_trace.attribution_status is MemoryUsageAttributionStatus.REJECTED


def test_runtime_conflicting_memory_is_not_current_fact(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    context = memory_context(
        memory_item("memory_a", "过去先检查环境有效。"),
        memory_item("memory_b", "过去先问诊有效。", conflict=True),
    )

    result = CooperativeRuntime(
        service=service,
        agent=MemoryAwarePlanningAgent(mode="conflicting"),
        memory_service=RuntimeMemoryService([context]),
    ).handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id)))

    assert result.status is CooperativeTurnStatus.RESPONDED
    assert result.memory_usage_trace.selected_memory_ids == ("memory_a", "memory_b")
    assert result.memory_usage_trace.accepted_used_memory_ids == ()
    assert service.state_store.load_case_session(opened.session_id).revision == 0


def test_runtime_retrieval_failure_fails_safe_and_turn_continues(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)

    result = CooperativeRuntime(
        service=service,
        agent=MemoryAwarePlanningAgent(mode="default"),
        memory_service=RuntimeMemoryService(fail=True),
    ).handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id)))

    assert result.status is CooperativeTurnStatus.RESPONDED
    assert result.memory_retrieval_status is MemoryRetrievalStatus.FAILED_SAFE
    assert result.memory_usage_trace.error_code == "memory_retrieval_failed_safe"


def repository_at(path: Path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(path, clock=lambda: NOW)
    repository.initialize()
    return repository


def project_reference(repository, case, player, *, session_id: str, index: int = 0) -> str:
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


def real_memory_service(repository, adapter):
    return GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=adapter),
        retrieval_config=MemoryRetrievalConfig(
            top_k=20,
            min_similarity=-1.0,
            embedding_space_id=adapter.embedding_space_id,
            query_template_version="memory_query_v1",
        ),
        projection_policy=GameNPCMemoryProjectionPolicy(repository=repository, clock=lambda: NOW),
        projection_config=GameNPCMemoryRetrievalConfig(allow_conflicting_memory=True, min_relevance=-1.0),
    )


def test_runtime_real_retrieval_filters_invalidated_and_tombstoned_memory(tmp_path: Path, case_definition, qualified_player_state) -> None:
    service, player_id, opened = opened_case(tmp_path / "runtime_case")
    player = qualified_player_state.model_copy(update={"player_id": player_id})
    repository = repository_at(tmp_path / "memory.sqlite3")
    invalid_id = project_reference(repository, case_definition, player, session_id="session_invalid_m3_runtime", index=0)
    deleted_id = project_reference(repository, case_definition, player, session_id="session_deleted_m3_runtime", index=1)
    repository.invalidate_memory(MemoryInvalidationOperation(
        operation_id=stable_lifecycle_operation_id("invalidate", player_id, invalid_id, "request_invalid_runtime"),
        request_id="request_invalid_runtime",
        player_id=player_id,
        target_memory_id=invalid_id,
        reason=MemoryLifecycleReason.SOURCE_REVOKED,
        trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
        occurred_at=NOW,
    ))
    repository.hard_delete_memory(MemoryHardDeleteOperation(
        operation_id=stable_lifecycle_operation_id("hard_delete", player_id, deleted_id, "request_delete_runtime"),
        request_id="request_delete_runtime",
        player_id=player_id,
        target_memory_id=deleted_id,
        reason=MemoryLifecycleReason.PRIVACY_REQUEST,
        trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR,
        occurred_at=NOW,
    ))
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(player_id=player_id)

    result = CooperativeRuntime(
        service=service,
        agent=MemoryAwarePlanningAgent(mode="irrelevant"),
        memory_service=real_memory_service(repository, adapter),
    ).handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id)))

    assert result.memory_usage_trace.candidate_memory_ids == ()
    assert result.memory_usage_trace.selected_memory_ids == ()
    assert invalid_id not in result.memory_usage_trace.declared_used_memory_ids
    assert deleted_id not in result.memory_usage_trace.declared_used_memory_ids


def test_memory_cannot_bypass_diagnosis_or_treatment_authority(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)

    result = CooperativeRuntime(
        service=service,
        agent=MemoryAwarePlanningAgent(mode="treatment_bait"),
        memory_service=RuntimeMemoryService([memory_context(memory_item("memory_treatment", "过去某治疗有效。"))]),
    ).handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id, text="直接治疗吧。")))

    assert result.status in {
        CooperativeTurnStatus.RESPONDED,
        CooperativeTurnStatus.PROPOSAL_PENDING,
        CooperativeTurnStatus.ACTION_REJECTED,
    }
    assert service.state_store.load_case_session(opened.session_id).revision == 0
    assert result.memory_usage_trace.accepted_used_memory_ids == ()
