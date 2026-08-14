from datetime import datetime, timezone
from pathlib import Path

from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
from xuanyi_npc.application.multicase import CreatePlayerInput, StartEpisodeInput
from xuanyi_npc.application.plan_evaluator import DeterministicPlanEvaluator
from xuanyi_npc.application.views import ObservedClueView
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind,
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContribution,
    PlayerContributionEvaluation,
    PlayerContributionType,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    GoalCondition,
    GoalConditionType,
    PlanEvaluationOutcome,
    PlanStep,
    PlanStepIntent,
    PlanStepStatus,
)
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalUpdateKind,
    GoalUpdateProposal,
    PlanDraft,
    PlanStepDraft,
    PlanUpdateKind,
    PlanUpdateProposal,
)
from xuanyi_npc.evaluation.m5_p4b_runner import build_service


class PlanningAgent:
    config = object()
    runtime_kind = AgentRuntimeKind.TEST_DOUBLE

    def __init__(self, proposals):
        self.proposals = list(proposals)
        self.inputs = []

    def propose_turn(self, value):
        self.inputs.append(value)
        return self.proposals.pop(0)(value)

    def repair_action_contract(self, value, prior, feedback):
        raise AssertionError("test proposal should satisfy the public action contract")

    def action_contract_fallback(self, prior):
        raise AssertionError("test proposal should not require fallback")


def opened_case(root: Path):
    service = build_service(root)
    created = service.create_player(CreatePlayerInput(display_name="M2协作玩家"))
    opened = service.start_episode(StartEpisodeInput(player_id=created.player_id, case_id="old_paper_umbrella"))
    assert opened.ok and opened.observation is not None and opened.session_id is not None
    return service, created.player_id, opened


def contribution(player_id, session_id, turn_id="turn_001", text="建议先调查患者。"):
    return PlayerContribution(
        contribution_id=turn_id,
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=session_id,
        contribution_type=PlayerContributionType.SUGGESTION,
        public_text=text,
        created_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )


def create_plan_proposal(disposition=SuggestionDisposition.ACCEPT):
    def build(value):
        option = value.case_observation.available_investigations[0]
        tool = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
        return GameNPCTurnProposal(
            goal_update=GoalUpdateProposal(update=GoalUpdateKind.KEEP, public_rationale="继续公开取证目标。"),
            plan_update=PlanUpdateProposal(
                update=PlanUpdateKind.CREATE,
                draft=PlanDraft(steps=(
                    PlanStepDraft(
                        intent=PlanStepIntent.INVESTIGATE,
                        capability=NPCCapability.USE_TOOL,
                        suggested_tool=tool,
                        public_target_id=option.investigation_id,
                        public_summary="执行一项公开调查。",
                        completion_signal=GoalCondition(condition_type=GoalConditionType.INVESTIGATION_COMPLETED, reference_id=option.investigation_id),
                    ),
                    PlanStepDraft(
                        intent=PlanStepIntent.DISCUSS_WITH_PLAYER,
                        capability=NPCCapability.EXPLAIN,
                        public_summary="与玩家核对新证据。",
                        completion_signal=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=3),
                    ),
                )),
                public_rationale="保持两步短计划。",
            ),
            decision=GameNPCDecisionProposal(
                contribution_evaluation=PlayerContributionEvaluation(
                    contribution_id=value.player_contribution.contribution_id,
                    disposition=disposition,
                    reason_code="public_direction",
                    explanation="采用可验证的公开调查方向。",
                ),
                capability=NPCCapability.USE_TOOL,
                action=AgentAction(
                    action_id=f"npc_{value.turn_id}",
                    action_type=AgentActionType.USE_TOOL,
                    dialogue="本轮只执行计划的第一项调查。",
                    tool_call=ToolCallRequest(name=tool, arguments={"investigation_id": option.investigation_id}),
                    confidence=0.8,
                ),
                explanation="执行当前 active step。",
            ),
        )
    return build


def revise_plan_proposal(value):
    option = value.case_observation.available_investigations[0]
    tool = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
    return GameNPCTurnProposal(
        goal_update=GoalUpdateProposal(update=GoalUpdateKind.KEEP, public_rationale="目标未被玩家覆盖。"),
        plan_update=PlanUpdateProposal(
            update=PlanUpdateKind.REVISE,
            draft=PlanDraft(steps=(
                PlanStepDraft(
                    intent=PlanStepIntent.INVESTIGATE, capability=NPCCapability.USE_TOOL,
                    suggested_tool=tool, public_target_id=option.investigation_id,
                    public_summary="按玩家的新方向调查公开目标。",
                    completion_signal=GoalCondition(condition_type=GoalConditionType.INVESTIGATION_COMPLETED, reference_id=option.investigation_id),
                ),
                PlanStepDraft(
                    intent=PlanStepIntent.DISCUSS_WITH_PLAYER, capability=NPCCapability.EXPLAIN,
                    public_summary="讨论新调查结果。",
                    completion_signal=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=3),
                ),
            )),
            public_rationale="合理玩家贡献改变了短期顺序。",
        ),
        decision=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=value.player_contribution.contribution_id,
                disposition=SuggestionDisposition.PARTIAL_ACCEPT,
                reason_code="player_changes_priority",
                explanation="接受公开且可验证的部分。",
            ),
            capability=NPCCapability.USE_TOOL,
            action=AgentAction(
                action_id=f"npc_{value.turn_id}", action_type=AgentActionType.USE_TOOL,
                dialogue="本轮执行修订后第一步。",
                tool_call=ToolCallRequest(name=tool, arguments={"investigation_id": option.investigation_id}),
                confidence=0.7,
            ),
            explanation="修订计划后仍只执行一个工具。",
        ),
    )


def test_runtime_initializes_state_executes_one_step_and_keeps_plan(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    agent = PlanningAgent([create_plan_proposal()])

    result = CooperativeRuntime(service=service, agent=agent).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )
    state = service.state_store.load_cooperative_agent_state(opened.session_id)
    session = service.state_store.load_case_session(opened.session_id)

    assert state.episode_goal.goal_type is AgentGoalType.RESOLVE_CASE
    assert state.current_plan is not None and len(state.current_plan.steps) == 2
    assert state.current_plan.steps[0].status is PlanStepStatus.COMPLETED
    assert state.current_plan.steps[1].status is PlanStepStatus.ACTIVE
    assert state.current_plan.revision == 2
    assert state.last_plan_evaluation.outcome is PlanEvaluationOutcome.KEEP_PLAN
    assert state.last_plan_evaluation.observation_revision_before == 0
    assert state.last_plan_evaluation.observation_revision_after == 1
    assert result.plan_evaluation_outcome == "keep_plan"
    assert result.decision.goal_id == state.current_goal.goal_id
    assert result.decision.plan_step_id == state.current_plan.steps[0].step_id
    assert len(session.action_history) == 1
    assert len(agent.inputs) == 1


def test_world_commit_survives_agent_projection_failure(tmp_path: Path, monkeypatch) -> None:
    service, player_id, opened = opened_case(tmp_path)
    agent = PlanningAgent([create_plan_proposal()])

    def fail_projection(*args, **kwargs):
        raise StorageError("projection unavailable")

    from xuanyi_npc.storage import StorageError
    monkeypatch.setattr(service.state_store, "save_cooperative_agent_state", fail_projection)
    result = CooperativeRuntime(service=service, agent=agent).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )

    assert result.error_code == "agent_state_projection_pending"
    assert service.state_store.load_case_session(opened.session_id).revision == 1


def test_player_contribution_revises_persisted_plan_on_next_turn(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    agent = PlanningAgent([create_plan_proposal(), revise_plan_proposal])
    runtime = CooperativeRuntime(service=service, agent=agent)
    runtime.handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id)))
    before = service.state_store.load_cooperative_agent_state(opened.session_id)

    runtime.handle(CooperativeTurnInput(contribution=contribution(
        player_id, opened.session_id, "turn_002", "我建议改变调查方向，但由你判断。"
    )))
    after = service.state_store.load_cooperative_agent_state(opened.session_id)

    assert after.revision == before.revision + 1
    assert after.current_plan.revision > before.current_plan.revision
    assert after.current_plan.source_contribution_id == "turn_002"
    assert len(service.state_store.load_case_session(opened.session_id).action_history) == 2


def evaluator_plan(observation, *, second_target=None):
    first = observation.available_investigations[0]
    tool = INVESTIGATION_TOOL_BY_ACTION[first.action_type]
    second_target = second_target or first.investigation_id
    return AgentPlan(
        plan_id="plan_eval", goal_id="goal_eval", status=AgentPlanStatus.ACTIVE,
        steps=(
            PlanStep(
                step_id="step_0", ordinal=0, intent=PlanStepIntent.INVESTIGATE,
                capability=NPCCapability.USE_TOOL, suggested_tool=tool,
                public_target_id=first.investigation_id, public_summary="第一步",
                completion_signal=GoalCondition(condition_type=GoalConditionType.INVESTIGATION_COMPLETED, reference_id=first.investigation_id),
                status=PlanStepStatus.ACTIVE,
            ),
            PlanStep(
                step_id="step_1", ordinal=1, intent=PlanStepIntent.INVESTIGATE,
                capability=NPCCapability.USE_TOOL, suggested_tool=tool,
                public_target_id=second_target, public_summary="第二步",
                completion_signal=GoalCondition(condition_type=GoalConditionType.INVESTIGATION_COMPLETED, reference_id=second_target),
                status=PlanStepStatus.PENDING,
            ),
        ),
        current_step_index=0, based_on_observation_revision=observation.session_revision,
        created_turn_id="turn_0", updated_turn_id="turn_0",
    )


def test_evaluator_marks_revise_without_running_another_step(tmp_path: Path) -> None:
    _, _, opened = opened_case(tmp_path)
    observation = opened.observation
    plan = evaluator_plan(observation, second_target="stale_public_target")
    goal = AgentGoalState(
        goal_id="goal_eval", goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="继续取证", status=AgentGoalStatus.ACTIVE, priority=80,
        completion_condition=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=99),
        created_turn_id="turn_0", updated_turn_id="turn_0",
    )
    option = observation.available_investigations[0]
    action = AgentAction(
        action_id="npc_turn_eval", action_type=AgentActionType.USE_TOOL, dialogue="调查",
        tool_call=ToolCallRequest(name=INVESTIGATION_TOOL_BY_ACTION[option.action_type], arguments={"investigation_id": option.investigation_id}),
        confidence=0.5,
    )

    transition = DeterministicPlanEvaluator().evaluate(
        pre_observation=observation, post_observation=observation,
        goal=goal, plan=plan, executed_action=action, tool_succeeded=True,
        turn_id="turn_eval",
    )

    assert transition.evaluation.outcome is PlanEvaluationOutcome.REVISE_PLAN
    assert transition.plan.status is AgentPlanStatus.NEEDS_REVISION
    assert transition.plan.steps[0].status is PlanStepStatus.COMPLETED
    assert transition.plan.steps[1].status is PlanStepStatus.OBSOLETE
    assert transition.plan.revision == plan.revision + 1


def test_goal_completion_is_deterministic_and_does_not_create_next_goal(tmp_path: Path) -> None:
    _, _, opened = opened_case(tmp_path)
    pre = opened.observation
    post = pre.model_copy(update={
        "session_revision": pre.session_revision + 1,
        "discovered_clues": (*pre.discovered_clues, ObservedClueView(clue_id="public_new", description="公开新线索")),
    })
    plan = evaluator_plan(pre)
    goal = AgentGoalState(
        goal_id="goal_eval", goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="获得一条证据", status=AgentGoalStatus.ACTIVE, priority=80,
        completion_condition=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=1),
        created_turn_id="turn_0", updated_turn_id="turn_0",
    )
    option = pre.available_investigations[0]
    action = AgentAction(
        action_id="npc_turn_complete", action_type=AgentActionType.USE_TOOL, dialogue="调查",
        tool_call=ToolCallRequest(name=INVESTIGATION_TOOL_BY_ACTION[option.action_type], arguments={"investigation_id": option.investigation_id}),
        confidence=0.5,
    )

    transition = DeterministicPlanEvaluator().evaluate(
        pre_observation=pre, post_observation=post, goal=goal, plan=plan,
        executed_action=action, tool_succeeded=True, turn_id="turn_complete",
    )

    assert transition.evaluation.outcome is PlanEvaluationOutcome.COMPLETE_GOAL
    assert transition.goal.goal_id == goal.goal_id
    assert transition.goal.status is AgentGoalStatus.COMPLETED
    assert transition.plan.status is AgentPlanStatus.COMPLETED
