from __future__ import annotations

from datetime import datetime, timezone

import pytest

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent, GameNPCAgentInput
from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.application.views import AgentContextFilter
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseSessionState, ToolCallRequest
from xuanyi_npc.domain.cooperation import (
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
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    GoalCondition,
    GoalConditionType,
)
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalDraft,
    GoalUpdateKind,
    GoalUpdateProposal,
    MemoryUsageProposal,
    PlanDraft,
    PlanStepDraft,
    PlanUpdateKind,
    PlanUpdateProposal,
)


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def npc_input(case_definition, qualified_player_state, *, memory_context=None) -> GameNPCAgentInput:
    session = CaseSessionState(
        session_id="session_m3_2",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )
    views = AgentContextFilter()
    value = GameNPCAgentInput(
        turn_id="turn_m3_2",
        step_index=1,
        player_view=views.player_view(qualified_player_state),
        case_observation=views.case_observation(
            case_definition,
            qualified_player_state,
            session,
        ),
        authority_view=NPCAuthorityPolicy().view(),
        current_goal=gather_goal(),
        current_plan=None,
        player_contribution=PlayerContribution(
            contribution_id="contribution_m3_2",
            player_id=qualified_player_state.player_id,
            case_id=case_definition.case_id,
            session_id="session_m3_2",
            contribution_type=PlayerContributionType.SUGGESTION,
            public_text="我建议优先检查环境痕迹。",
            created_at=NOW,
        ),
        memory_context=memory_context,
    )
    return value


def gather_goal() -> AgentGoalState:
    return AgentGoalState(
        goal_id="goal_m3_gather",
        goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="继续收集公开证据。",
        status=AgentGoalStatus.ACTIVE,
        priority=80,
        completion_condition=GoalCondition(
            condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
            threshold=2,
        ),
        created_turn_id="turn_prev",
        updated_turn_id="turn_prev",
    )


def diagnosis_goal() -> AgentGoalState:
    return gather_goal().model_copy(
        update={
            "goal_id": "goal_m3_diagnosis",
            "goal_type": AgentGoalType.FORM_DIAGNOSIS,
            "public_description": "形成诊断假设。",
            "completion_condition": GoalCondition(
                condition_type=GoalConditionType.DIAGNOSIS_READY,
            ),
        }
    )


def memory_context(*items: AgentMemoryItem) -> AgentMemoryContext:
    ids = tuple(item.memory_id for item in items)
    return AgentMemoryContext(
        retrieval_id="memory_retrieval_m3_2",
        query_basis="public query basis",
        normalized_query="public query basis",
        memories=items,
        retrieval_summary=f"selected {len(items)} memories",
        candidate_memory_ids=(*ids, "candidate_only_memory"),
        selected_memory_ids=ids,
        total_candidates=len(ids) + 1,
        selected_count=len(ids),
        max_selected=4,
        char_budget=900,
        selected_chars=sum(len(item.public_summary) for item in items),
        embedding_space_id="fake_space",
        query_template_version="game_npc_memory_query_v1",
        index_status="complete",
        active_memory_count=len(ids),
        valid_embedding_count=len(ids),
    )


def memory_item(memory_id: str, summary: str, *, conflict: bool = False) -> AgentMemoryItem:
    return AgentMemoryItem(
        memory_id=memory_id,
        memory_type=MemoryType.EPISODIC,
        public_summary=summary,
        source_type=AgentMemorySourceType.INVESTIGATION_COMPLETED,
        source_episode_id=f"episode_{memory_id}",
        source_case_id="case_history",
        relevance_score=0.82,
        confidence=0.8 if not conflict else 0.3,
        reason_code="investigation_completed",
        occurred_at=NOW,
        last_verified_at=NOW,
        conflict_with_current_observation=conflict,
    )


def first_public_tool(value: GameNPCAgentInput, index: int = 0):
    option = value.case_observation.available_investigations[index]
    return option, INVESTIGATION_TOOL_BY_ACTION[option.action_type]


def plan_for(value: GameNPCAgentInput, *, index: int = 0, summary: str = "执行公开调查。") -> PlanDraft:
    option, tool = first_public_tool(value, index)
    return PlanDraft(
        steps=(
            PlanStepDraft(
                intent="investigate",
                capability=NPCCapability.USE_TOOL,
                suggested_tool=tool,
                public_target_id=option.investigation_id,
                public_summary=summary,
                completion_signal=GoalCondition(
                    condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
                    reference_id=option.investigation_id,
                ),
            ),
            PlanStepDraft(
                intent="discuss_with_player",
                capability=NPCCapability.EXPLAIN,
                public_summary="与玩家核对公开证据。",
                completion_signal=value.current_goal.completion_condition,
            ),
        )
    )


def decision_for(
    value: GameNPCAgentInput,
    *,
    capability: NPCCapability = NPCCapability.EXPLAIN,
    action=None,
) -> GameNPCDecisionProposal:
    return GameNPCDecisionProposal(
        contribution_evaluation=PlayerContributionEvaluation(
            contribution_id=value.player_contribution.contribution_id,
            disposition=SuggestionDisposition.PARTIAL_ACCEPT,
            reason_code="memory_is_non_authoritative",
            explanation="我会参考历史经验，但仍只依据当前公开事实行动。",
        ),
        capability=capability,
        action=action
        or AgentAction(
            action_id=f"npc_{value.turn_id}",
            action_type=AgentActionType.RESPOND,
            dialogue="我会参考这条历史经验调整公开调查顺序。",
            confidence=0.7,
        ),
        explanation="本轮仍只有一个行动。",
    )


def proposal_for(
    value: GameNPCAgentInput,
    *,
    plan_index: int = 0,
    memory_usage: MemoryUsageProposal | None = None,
    goal_update: GoalUpdateProposal | None = None,
    decision: GameNPCDecisionProposal | None = None,
) -> GameNPCTurnProposal:
    return GameNPCTurnProposal(
        goal_update=goal_update
        or GoalUpdateProposal(
            update=GoalUpdateKind.KEEP,
            public_rationale="当前目标仍有效。",
        ),
        plan_update=PlanUpdateProposal(
            update=PlanUpdateKind.CREATE,
            draft=plan_for(value, index=plan_index),
            public_rationale="形成两步短计划。",
        ),
        decision=decision or decision_for(value),
        memory_usage=memory_usage,
    )


def test_input_accepts_safe_agent_memory_context_and_prompt_roles(case_definition, qualified_player_state) -> None:
    context = memory_context(memory_item("memory_env", "过去类似情境中环境痕迹影响了调查顺序。"))
    value = npc_input(case_definition, qualified_player_state, memory_context=context)
    usage = MemoryUsageProposal(
        used_memory_ids=("memory_env",),
        influence_types=("plan_priority",),
        affected_plan=True,
        public_effect_summary="参考历史经验，优先安排环境相关调查。",
    )
    proposal = proposal_for(value, memory_usage=usage)
    fake = ScriptedFakeLLM([proposal.model_dump_json()])

    result = GameNPCAgent(fake).propose_turn(value)

    assert result.memory_usage == usage
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "AUTHORITATIVE_WORLD_case_observation" in prompt
    assert "AUTHORITATIVE_CONSTRAINTS_authority_view" in prompt
    assert "AGENT_INTENT_current_goal" in prompt
    assert "HISTORICAL_NON_AUTHORITATIVE_CONTEXT_memory_context" in prompt
    assert "PLAYER_BELIEF_player_contribution" in prompt
    assert "TRUST_1" not in prompt
    assert "memory_env" in prompt
    assert "memory_context 是经过确定性安全投影的历史经验" in prompt


def test_unknown_or_candidate_only_memory_id_is_rejected_then_fallback_is_safe(case_definition, qualified_player_state) -> None:
    context = memory_context(memory_item("memory_selected", "已选择的安全记忆。"))
    value = npc_input(case_definition, qualified_player_state, memory_context=context)
    invalid = proposal_for(
        value,
        memory_usage=MemoryUsageProposal(
            used_memory_ids=("candidate_only_memory",),
            influence_types=("plan_priority",),
            affected_plan=True,
            public_effect_summary="错误引用未选择的候选记忆。",
        ),
    )
    fake = ScriptedFakeLLM([invalid.model_dump_json(), invalid.model_dump_json()])

    result = GameNPCAgent(fake).propose_turn(value)

    assert len(fake.requests) == 2
    assert result.memory_usage is None
    assert result.decision.action.action_type is AgentActionType.RESPOND
    assert all(step.suggested_tool is None for step in result.plan_update.draft.steps)


def test_relevant_memory_can_change_plan_proposal(case_definition, qualified_player_state) -> None:
    no_memory = npc_input(case_definition, qualified_player_state)
    with_memory = npc_input(
        case_definition,
        qualified_player_state,
        memory_context=memory_context(memory_item("memory_env", "过去类似情境中先检查环境异常更有效。")),
    )
    no_memory_result = GameNPCAgent(
        ScriptedFakeLLM([proposal_for(no_memory, plan_index=0).model_dump_json()])
    ).propose_turn(no_memory)
    usage = MemoryUsageProposal(
        used_memory_ids=("memory_env",),
        influence_types=("plan_priority",),
        affected_plan=True,
        public_effect_summary="将历史经验作为非权威参考，调整调查顺序。",
    )
    with_memory_result = GameNPCAgent(
        ScriptedFakeLLM([proposal_for(with_memory, plan_index=1, memory_usage=usage).model_dump_json()])
    ).propose_turn(with_memory)

    assert no_memory_result.plan_update.draft.steps[0].public_target_id != with_memory_result.plan_update.draft.steps[0].public_target_id
    assert with_memory_result.memory_usage.used_memory_ids == ("memory_env",)


def test_relevant_memory_can_change_goal_proposal(case_definition, qualified_player_state) -> None:
    value = npc_input(
        case_definition,
        qualified_player_state,
        memory_context=memory_context(memory_item("memory_early_dx", "过去过早诊断导致遗漏公开证据。")),
    ).model_copy(update={"current_goal": diagnosis_goal()})
    goal_update = GoalUpdateProposal(
        update=GoalUpdateKind.REPLACE,
        draft=GoalDraft(
            goal_type=AgentGoalType.GATHER_EVIDENCE,
            public_description="先回到公开证据收集。",
            priority=90,
            completion_condition=GoalCondition(
                condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
                threshold=2,
            ),
        ),
        public_rationale="历史经验提示过早诊断容易遗漏证据。",
    )
    usage = MemoryUsageProposal(
        used_memory_ids=("memory_early_dx",),
        influence_types=("goal_selection",),
        affected_goal=True,
        public_effect_summary="参考历史经验，提议先补证据再诊断。",
    )

    result = GameNPCAgent(
        ScriptedFakeLLM([proposal_for(value, memory_usage=usage, goal_update=goal_update).model_dump_json()])
    ).propose_turn(value)

    assert result.goal_update.update is GoalUpdateKind.REPLACE
    assert result.goal_update.draft.goal_type is AgentGoalType.GATHER_EVIDENCE
    assert result.memory_usage.affected_goal is True


def test_relevant_memory_can_change_legal_tool_priority(case_definition, qualified_player_state) -> None:
    value = npc_input(
        case_definition,
        qualified_player_state,
        memory_context=memory_context(memory_item("memory_tool", "过去类似公开局面中第二项调查更快获得证据。")),
    )
    option, tool = first_public_tool(value, 1)
    action = AgentAction(
        action_id=f"npc_{value.turn_id}",
        action_type=AgentActionType.USE_TOOL,
        dialogue="我先执行这一项公开调查。",
        tool_call=ToolCallRequest(name=tool, arguments={"investigation_id": option.investigation_id}),
        confidence=0.8,
    )
    usage = MemoryUsageProposal(
        used_memory_ids=("memory_tool",),
        influence_types=("tool_priority",),
        affected_tool_priority=True,
        affected_decision=True,
        public_effect_summary="参考历史经验，在多个合法工具中优先选择第二项公开调查。",
    )

    result = GameNPCAgent(
        ScriptedFakeLLM([
            proposal_for(
                value,
                plan_index=1,
                memory_usage=usage,
                decision=decision_for(value, capability=NPCCapability.USE_TOOL, action=action),
            ).model_dump_json()
        ])
    ).propose_turn(value)

    assert result.decision.action.tool_call.name is tool
    assert result.decision.action.tool_call.arguments["investigation_id"] == option.investigation_id
    assert result.memory_usage.affected_tool_priority is True


def test_irrelevant_memory_can_remain_unused_without_behavior_change(case_definition, qualified_player_state) -> None:
    no_memory = npc_input(case_definition, qualified_player_state)
    irrelevant = npc_input(
        case_definition,
        qualified_player_state,
        memory_context=memory_context(memory_item("memory_irrelevant", "过去玩家喜欢先观察颜色。")),
    )

    first = GameNPCAgent(ScriptedFakeLLM([proposal_for(no_memory).model_dump_json()])).propose_turn(no_memory)
    second = GameNPCAgent(ScriptedFakeLLM([proposal_for(irrelevant).model_dump_json()])).propose_turn(irrelevant)

    assert second.memory_usage is None
    assert first.plan_update == second.plan_update
    assert first.decision.action.action_type is second.decision.action.action_type


def test_conflicting_memory_is_not_treated_as_current_fact(case_definition, qualified_player_state) -> None:
    context = memory_context(
        memory_item("memory_question", "过去类似情境先问诊有效。"),
        memory_item("memory_object", "另一次类似情境先验物有效。", conflict=True),
    )
    value = npc_input(case_definition, qualified_player_state, memory_context=context)
    usage = MemoryUsageProposal(
        used_memory_ids=("memory_question",),
        influence_types=("communication_strategy",),
        affected_communication=True,
        public_effect_summary="只把非冲突历史作为讨论参考，请求当前证据继续区分。",
    )
    decision = decision_for(
        value,
        capability=NPCCapability.EXPLAIN_EVIDENCE_GAP,
        action=AgentAction(
            action_id=f"npc_{value.turn_id}",
            action_type=AgentActionType.RESPOND,
            dialogue="两段历史只能作为参考，我仍需要当前病例的公开证据来区分。",
            confidence=0.7,
        ),
    )

    result = GameNPCAgent(
        ScriptedFakeLLM([proposal_for(value, memory_usage=usage, decision=decision).model_dump_json()])
    ).propose_turn(value)

    assert result.memory_usage.used_memory_ids == ("memory_question",)
    assert "当前病例的公开证据" in result.decision.action.dialogue
    assert "memory_object" not in result.memory_usage.used_memory_ids


def test_memory_usage_claim_must_match_goal_plan_decision_shape(case_definition, qualified_player_state) -> None:
    value = npc_input(
        case_definition,
        qualified_player_state,
        memory_context=memory_context(memory_item("memory_bad_claim", "一条相关但不能空泛使用的历史。")),
    )
    invalid = proposal_for(
        value,
        memory_usage=MemoryUsageProposal(
            used_memory_ids=("memory_bad_claim",),
            influence_types=("goal_selection",),
            affected_goal=True,
            public_effect_summary="声称影响目标但目标保持不变。",
        ),
    )
    fake = ScriptedFakeLLM([invalid.model_dump_json(), invalid.model_dump_json()])

    result = GameNPCAgent(fake).propose_turn(value)

    assert result.memory_usage is None
    assert result.goal_update.update is GoalUpdateKind.KEEP
    assert result.decision.action.action_type is AgentActionType.RESPOND
