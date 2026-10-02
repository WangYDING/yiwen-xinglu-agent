from types import SimpleNamespace

import pytest

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime
from xuanyi_npc.application.goal_plan_policy import GoalPlanPolicy, GoalPlanPolicyError
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.domain import AgentActionType
from xuanyi_npc.domain.cooperative_planning import AgentGoalStatus, AgentPlanStatus, PlanStepStatus
from xuanyi_npc.domain.planning_contract import GoalUpdateKind, PlanUpdateKind
from tests.test_p2_plan_decision_alignment import _diagnosis_input, _proposal as diagnosis_proposal
from tests.test_p4_treatment_action_contract import _proposal as treatment_proposal, _treatment_input
from tests.test_p5_executable_step_commitment import _keep, _persist_first_plan


def _validate(value, proposal):
    GoalPlanPolicy().validate(
        proposal,
        current_goal=value.current_goal,
        current_plan=value.current_plan,
        observation=value.case_observation,
        authority_view=value.authority_view,
        pending_confirmation=value.pending_confirmation_id is not None,
    )


@pytest.mark.parametrize("kind", ["diagnosis", "treatment"])
def test_exhausted_executable_step_fallback_is_policy_valid_and_non_acting(
    case_definition, qualified_player_state, kind
):
    if kind == "diagnosis":
        value = _diagnosis_input(case_definition, qualified_player_state)
        create, _, _ = diagnosis_proposal(value)
    else:
        value = _treatment_input(case_definition, qualified_player_state)
        create = treatment_proposal(value)
    value = _persist_first_plan(value, create)
    llm = ScriptedFakeLLM(["{}", "{}"])
    agent = GameNPCAgent(llm)

    fallback = agent.propose_turn(value)

    assert agent.last_planning_execution().attempts == 2
    assert fallback.goal_update.update is GoalUpdateKind.ABANDON
    assert fallback.plan_update.update is PlanUpdateKind.ABANDON
    assert fallback.decision.action.action_type is AgentActionType.RESPOND
    assert fallback.decision.action.tool_call is None
    _validate(value, fallback)
    assert NPCAuthorityPolicy().evaluate(fallback.decision.action).mode.value == "autonomous"
    assert fallback.decision.action.tool_call is None  # no pending-producing action


def test_non_tool_plan_fallback_keeps_existing_safe_behavior(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    discussion = treatment_proposal(value, discuss=True)
    value = _persist_first_plan(value, discussion)
    fallback = GameNPCAgent(ScriptedFakeLLM([]))._fallback_turn_proposal(value)

    assert fallback.goal_update.update is GoalUpdateKind.KEEP
    assert fallback.plan_update.update is PlanUpdateKind.KEEP
    assert fallback.decision.action.tool_call is None
    _validate(value, fallback)


def test_pending_confirmation_preserves_plan_and_remains_policy_valid(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    create = treatment_proposal(value)
    value = _persist_first_plan(value, create).model_copy(
        update={"pending_confirmation_id": "decision_pending"}
    )
    fallback = GameNPCAgent(ScriptedFakeLLM([]))._fallback_turn_proposal(value)

    assert fallback.goal_update.update is GoalUpdateKind.KEEP
    assert fallback.plan_update.update is PlanUpdateKind.KEEP
    assert fallback.decision.action.tool_call is None
    _validate(value, fallback)


@pytest.mark.parametrize(
    "status, expected_plan_update, expected_goal_update",
    [
        (AgentPlanStatus.NEEDS_REVISION, PlanUpdateKind.REVISE, GoalUpdateKind.KEEP),
        (AgentPlanStatus.COMPLETED, PlanUpdateKind.REVISE, GoalUpdateKind.KEEP),
        (AgentPlanStatus.ABANDONED, PlanUpdateKind.ABANDON, GoalUpdateKind.ABANDON),
    ],
)
def test_fallback_is_legal_for_each_inactive_plan_status(
    case_definition, qualified_player_state, status, expected_plan_update, expected_goal_update
):
    value = _treatment_input(case_definition, qualified_player_state)
    value = _persist_first_plan(value, treatment_proposal(value))
    steps = tuple(step.model_copy(update={
        "status": (
            PlanStepStatus.COMPLETED if status is AgentPlanStatus.COMPLETED
            else PlanStepStatus.OBSOLETE
        )
    }) for step in value.current_plan.steps)
    value = value.model_copy(update={
        "current_plan": value.current_plan.model_copy(update={"status": status, "steps": steps})
    })

    fallback = GameNPCAgent(ScriptedFakeLLM([]))._fallback_turn_proposal(value)

    assert fallback.goal_update.update is expected_goal_update
    assert fallback.plan_update.update is expected_plan_update
    assert fallback.decision.action.tool_call is None
    _validate(value, fallback)


def test_fallback_safely_ends_when_goal_is_already_terminal(
    case_definition, qualified_player_state
):
    value = _treatment_input(case_definition, qualified_player_state)
    value = _persist_first_plan(value, treatment_proposal(value))
    value = value.model_copy(update={
        "current_goal": value.current_goal.model_copy(
            update={"status": AgentGoalStatus.COMPLETED}
        )
    })

    fallback = GameNPCAgent(ScriptedFakeLLM([]))._fallback_turn_proposal(value)

    assert fallback.goal_update.update is GoalUpdateKind.ABANDON
    assert fallback.plan_update.update is PlanUpdateKind.ABANDON
    _validate(value, fallback)


def test_p5_contract_and_runtime_alignment_semantics_are_unchanged(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    create = treatment_proposal(value)
    value = _persist_first_plan(value, create)
    illegal = _keep(create, respond=True)

    with pytest.raises(GoalPlanPolicyError, match="plain RESPOND"):
        _validate(value, illegal)
    decision = SimpleNamespace(proposal=illegal.decision)
    state = SimpleNamespace(current_plan=value.current_plan)
    assert CooperativeRuntime._action_matches_plan(decision, state) is True
