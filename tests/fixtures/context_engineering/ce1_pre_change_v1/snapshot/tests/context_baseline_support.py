"""Deterministic inputs shared by the frozen context-request baseline tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from xuanyi_npc.agents import ChatMessage, ChatRole
from xuanyi_npc.agents.game_npc import GameNPCAgentInput
from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.application.views import AgentContextFilter
from xuanyi_npc.domain import CaseDefinition, CaseSessionState, PlayerState, SkillState
from xuanyi_npc.domain.cooperation import PlayerContribution, PlayerContributionType
from xuanyi_npc.domain.cooperative_memory import (
    AgentMemoryContext,
    AgentMemoryItem,
    AgentMemorySourceType,
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    GoalCondition,
    GoalConditionType,
    PlanEvaluation,
    PlanEvaluationOutcome,
    PlanEvaluationReason,
    PlanStep,
    PlanStepIntent,
    PlanStepStatus,
)
from xuanyi_npc.domain.cooperation import NPCCapability
from xuanyi_npc.domain.memory import MemoryType


ROOT = Path(__file__).parents[1]
CASE_PATH = ROOT / "src" / "xuanyi_npc" / "resources" / "cases" / "old_paper_umbrella.json"
NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _case_and_player() -> tuple[CaseDefinition, PlayerState]:
    case = CaseDefinition.model_validate_json(CASE_PATH.read_text(encoding="utf-8"))
    player = PlayerState(
        player_id="player_context_baseline",
        display_name="上下文基线玩家",
        skills={
            "observe_form": SkillState(skill_id="observe_form", proficiency=25, unlocked=True),
            "ask_cause": SkillState(skill_id="ask_cause", proficiency=20, unlocked=True),
            "inspect_object": SkillState(
                skill_id="inspect_object",
                proficiency=15,
                unlocked=True,
                prerequisite_ids={"observe_form"},
            ),
            "observe_qi": SkillState(
                skill_id="observe_qi",
                proficiency=25,
                unlocked=True,
                prerequisite_ids={"observe_form", "inspect_object"},
            ),
        },
    )
    return case, player


def _base_input() -> GameNPCAgentInput:
    case, player = _case_and_player()
    session = CaseSessionState(
        session_id="session_context_baseline",
        case_id=case.case_id,
        player_id=player.player_id,
    )
    views = AgentContextFilter()
    return GameNPCAgentInput(
        turn_id="turn_context_baseline",
        step_index=1,
        player_view=views.player_view(player),
        case_observation=views.case_observation(case, player, session),
        player_contribution=PlayerContribution(
            contribution_id="turn_context_baseline",
            player_id=player.player_id,
            case_id=case.case_id,
            session_id=session.session_id,
            contribution_type=PlayerContributionType.SUGGESTION,
            public_text="先核对纸伞上的痕迹，再决定是否诊断。",
            created_at=NOW,
        ),
        authority_view=NPCAuthorityPolicy().view(),
        recent_messages=(
            ChatMessage(role=ChatRole.USER, content="上一轮玩家意见。"),
            ChatMessage(role=ChatRole.ASSISTANT, content="上一轮 NPC 回复。"),
        ),
        agent_state_revision=7,
    )


def action_input() -> GameNPCAgentInput:
    """A0 keeps its existing input surface even though several fields are unused."""

    return _base_input()


def planning_input() -> GameNPCAgentInput:
    """A1 input with every currently serialized optional context section populated."""

    value = _base_input()
    option = value.case_observation.available_investigations[0]
    tool = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
    goal = AgentGoalState(
        goal_id="goal_context_baseline",
        goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="收集足以支持判断的公开证据。",
        status=AgentGoalStatus.ACTIVE,
        priority=80,
        completion_condition=GoalCondition(
            condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
            threshold=2,
        ),
        created_turn_id="turn_previous",
        updated_turn_id="turn_previous",
        revision=2,
    )
    plan = AgentPlan(
        plan_id="plan_context_baseline",
        goal_id=goal.goal_id,
        status=AgentPlanStatus.ACTIVE,
        steps=(
            PlanStep(
                step_id="step_context_0",
                ordinal=0,
                intent=PlanStepIntent.INVESTIGATE,
                capability=NPCCapability.USE_TOOL,
                suggested_tool=tool,
                public_target_id=option.investigation_id,
                public_summary="检查当前公开痕迹。",
                completion_signal=GoalCondition(
                    condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
                    reference_id=option.investigation_id,
                ),
                status=PlanStepStatus.ACTIVE,
            ),
            PlanStep(
                step_id="step_context_1",
                ordinal=1,
                intent=PlanStepIntent.DISCUSS_WITH_PLAYER,
                capability=NPCCapability.EXPLAIN,
                public_summary="依据新证据与玩家核对判断。",
                completion_signal=goal.completion_condition,
                status=PlanStepStatus.PENDING,
            ),
        ),
        current_step_index=0,
        based_on_observation_revision=value.case_observation.session_revision,
        source_contribution_id=value.player_contribution.contribution_id,
        created_turn_id="turn_previous",
        updated_turn_id="turn_previous",
        revision=2,
    )
    evaluation = PlanEvaluation(
        evaluation_id="evaluation_context_baseline",
        plan_id=plan.plan_id,
        outcome=PlanEvaluationOutcome.KEEP_PLAN,
        reason_code=PlanEvaluationReason.STEP_COMPLETED,
        observation_revision_before=0,
        observation_revision_after=0,
        completed_step_ids=(),
        next_goal_status=AgentGoalStatus.ACTIVE,
        public_summary="上一轮没有执行工具。",
        evaluated_turn_id="turn_previous",
    )
    memory = AgentMemoryItem(
        memory_id="memory_context_baseline",
        memory_type=MemoryType.EPISODIC,
        public_summary="旧案中先核对物证再下判断。",
        source_type=AgentMemorySourceType.INVESTIGATION_COMPLETED,
        source_episode_id="episode_history",
        source_case_id="case_history",
        relevance_score=0.82,
        confidence=0.8,
        reason_code="investigation_completed",
        occurred_at=NOW,
        last_verified_at=NOW,
    )
    memory_context = AgentMemoryContext(
        retrieval_id="retrieval_context_baseline",
        query_basis="公开案件与玩家建议",
        normalized_query="公开案件 玩家建议",
        memories=(memory,),
        retrieval_summary="selected 1 memories",
        candidate_memory_ids=(memory.memory_id, "memory_not_selected"),
        selected_memory_ids=(memory.memory_id,),
        total_candidates=2,
        selected_count=1,
        max_selected=4,
        char_budget=900,
        selected_chars=len(memory.public_summary),
        embedding_space_id="fake_space",
        query_template_version="game_npc_memory_query_v1",
        index_status="complete",
        active_memory_count=2,
        valid_embedding_count=2,
    )
    return value.model_copy(
        update={
            "current_goal": goal,
            "current_plan": plan,
            "last_plan_evaluation": evaluation,
            "last_environment_feedback": evaluation.public_summary,
            "memory_context": memory_context,
            # This intentionally freezes the current semantic mismatch: runtime
            # supplies a pending decision ID in this field.
            "pending_confirmation_id": "decision_pending_baseline",
        }
    )
