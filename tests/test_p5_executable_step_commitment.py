from types import SimpleNamespace

import pytest

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime
from xuanyi_npc.application.goal_plan_policy import GoalPlanPolicy, GoalPlanPolicyError
from xuanyi_npc.domain import AgentAction, AgentActionType
from xuanyi_npc.domain.cooperation import NPCCapability
from xuanyi_npc.domain.cooperative_planning import (
    AgentPlan,
    AgentPlanStatus,
    PlanStep,
    PlanStepStatus,
)
from xuanyi_npc.domain.planning_contract import PlanUpdateKind
from tests.test_p2_plan_decision_alignment import _diagnosis_input, _proposal as diagnosis_proposal
from tests.test_p4_treatment_action_contract import _proposal as treatment_proposal, _treatment_input


def _persist_first_plan(value, proposal):
    steps = tuple(
        PlanStep(
            step_id=f"step_{index}",
            ordinal=index,
            intent=draft.intent,
            capability=draft.capability,
            suggested_tool=draft.suggested_tool,
            public_target_id=draft.public_target_id,
            public_summary=draft.public_summary,
            expected_information=draft.expected_information,
            completion_signal=draft.completion_signal,
            status=PlanStepStatus.ACTIVE if index == 0 else PlanStepStatus.PENDING,
        )
        for index, draft in enumerate(proposal.plan_update.draft.steps)
    )
    plan = AgentPlan(
        plan_id="plan_active",
        goal_id=value.current_goal.goal_id,
        status=AgentPlanStatus.ACTIVE,
        steps=steps,
        current_step_index=0,
        based_on_observation_revision=value.case_observation.session_revision,
        source_contribution_id=value.player_contribution.contribution_id,
        created_turn_id=value.turn_id,
        updated_turn_id=value.turn_id,
    )
    return value.model_copy(update={"current_plan": plan})


def _keep(proposal, *, respond=False):
    plan_update = proposal.plan_update.model_copy(update={"update": PlanUpdateKind.KEEP, "draft": None})
    if not respond:
        return proposal.model_copy(update={"plan_update": plan_update})
    action = AgentAction(
        action_id=proposal.decision.action.action_id,
        action_type=AgentActionType.RESPOND,
        dialogue="继续说明公开信息。",
        confidence=0.5,
    )
    decision = proposal.decision.model_copy(
        update={"capability": NPCCapability.EXPLAIN, "action": action}
    )
    return proposal.model_copy(update={"plan_update": plan_update, "decision": decision})


def _validate(value, proposal, *, pending=False):
    GoalPlanPolicy().validate(
        proposal,
        current_goal=value.current_goal,
        current_plan=value.current_plan,
        observation=value.case_observation,
        authority_view=value.authority_view,
        pending_confirmation=pending,
    )


def test_matching_treatment_and_diagnosis_execute_active_steps(case_definition, qualified_player_state):
    treatment_value = _treatment_input(case_definition, qualified_player_state)
    treatment = treatment_proposal(treatment_value)
    treatment_value = _persist_first_plan(treatment_value, treatment)
    _validate(treatment_value, _keep(treatment))

    diagnosis_value = _diagnosis_input(case_definition, qualified_player_state)
    diagnosis, _, _ = diagnosis_proposal(diagnosis_value)
    diagnosis_value = _persist_first_plan(diagnosis_value, diagnosis)
    _validate(diagnosis_value, _keep(diagnosis))


def test_plain_respond_on_executable_active_step_triggers_structured_repair(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    create = treatment_proposal(value)
    value = _persist_first_plan(value, create)
    invalid = _keep(create, respond=True)
    valid = _keep(create)
    llm = ScriptedFakeLLM([invalid.model_dump_json(), valid.model_dump_json()])
    agent = GameNPCAgent(llm)

    result = agent.propose_turn(value)

    assert agent.last_planning_execution().attempts == 2
    assert result.decision.action.tool_call == valid.decision.action.tool_call
    assert "executable active PlanStep" in llm.requests[1].messages[-1].content


def test_plain_respond_on_executable_active_step_is_rejected(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    create = treatment_proposal(value)
    value = _persist_first_plan(value, create)
    with pytest.raises(GoalPlanPolicyError, match="plain RESPOND"):
        _validate(value, _keep(create, respond=True))


def test_legal_plan_revision_may_respond(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    create = treatment_proposal(value)
    value = _persist_first_plan(value, create)
    revision = treatment_proposal(value, discuss=True)
    revision = revision.model_copy(update={
        "plan_update": revision.plan_update.model_copy(update={"update": PlanUpdateKind.REVISE})
    })
    _validate(value, revision)


def test_pending_confirmation_may_respond(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    create = treatment_proposal(value)
    value = _persist_first_plan(value, create)
    _validate(value, _keep(create, respond=True), pending=True)


def test_non_tool_step_may_respond_and_runtime_alignment_is_unchanged(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state)
    discussion = treatment_proposal(value, discuss=True)
    value = _persist_first_plan(value, discussion)
    response = _keep(discussion)
    _validate(value, response)
    decision = SimpleNamespace(proposal=response.decision)
    state = SimpleNamespace(current_plan=value.current_plan)
    assert CooperativeRuntime._action_matches_plan(decision, state) is True


def test_commitment_and_pending_state_are_model_visible(case_definition, qualified_player_state):
    value = _treatment_input(case_definition, qualified_player_state).model_copy(
        update={"pending_confirmation_id": "decision_pending"}
    )
    context = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(value).messages[-1].content
    assert "EXECUTABLE_ACTIVE_STEP_CONTRACT" in context
    assert "decision_pending" in context
    assert "Runtime 不会替你选择或执行 action" in context
