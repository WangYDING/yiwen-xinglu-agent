import json
from types import SimpleNamespace

import pytest

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.action_contract import project_public_treatment_actions
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime
from xuanyi_npc.application.goal_plan_policy import GoalPlanPolicy, GoalPlanPolicyError
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.application.views import TreatmentOptionView
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import GameNPCDecisionProposal, NPCCapability, PlayerContributionEvaluation, SuggestionDisposition
from xuanyi_npc.domain.cooperative_planning import AgentGoalType, AgentPlanStatus, GoalCondition, GoalConditionType, PlanStepIntent
from xuanyi_npc.domain.planning_contract import GameNPCTurnProposal, GoalUpdateKind, GoalUpdateProposal, PlanDraft, PlanStepDraft, PlanUpdateKind, PlanUpdateProposal
from tests.test_m2_planning_contract import planning_input


def _treatment_input(case_definition, qualified_player_state):
    value = planning_input(case_definition, qualified_player_state, "请提出公开处置方案。")
    treatments = (
        TreatmentOptionView(treatment_id="treatment_public_a", public_description="公开处置 A"),
        TreatmentOptionView(treatment_id="treatment_public_b", public_description="公开处置 B"),
    )
    observation = value.case_observation.model_copy(update={
        "submitted_diagnosis_id": value.case_observation.diagnosis_candidates[0].diagnosis_id,
        "available_treatments": treatments,
    })
    goal = value.current_goal.model_copy(update={
        "goal_type": AgentGoalType.SELECT_TREATMENT,
        "completion_condition": GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED),
    })
    return value.model_copy(update={"case_observation": observation, "current_goal": goal})


def _proposal(value, *, step_target="treatment_public_a", decision_target="treatment_public_a",
              decision_tool=ToolName.EXECUTE_TREATMENT, discuss=False, empty=False):
    proposed = PlanStepDraft(
        intent=PlanStepIntent.PROPOSE_TREATMENT,
        capability=NPCCapability.PROPOSE_TREATMENT,
        suggested_tool=None if empty else ToolName.EXECUTE_TREATMENT,
        public_target_id=None if empty else step_target,
        public_summary="提出公开处置方案。",
        completion_signal=GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED),
    )
    discussion = PlanStepDraft(
        intent=PlanStepIntent.DISCUSS_TREATMENT,
        capability=NPCCapability.RISK_WARNING,
        public_summary="先与玩家讨论风险。",
        completion_signal=GoalCondition(condition_type=GoalConditionType.PLAYER_RISK_RESPONSE_RECEIVED),
    )
    if discuss:
        action = AgentAction(action_id=f"npc_{value.turn_id}", action_type=AgentActionType.RESPOND, dialogue="先讨论风险。", confidence=0.5)
        steps = (discussion, proposed)
        capability = NPCCapability.RISK_WARNING
    else:
        arguments = ({"treatment_id": decision_target} if decision_tool is ToolName.EXECUTE_TREATMENT else {"diagnosis_id": value.case_observation.submitted_diagnosis_id, "evidence_clue_ids": []})
        action = AgentAction(action_id=f"npc_{value.turn_id}", action_type=AgentActionType.USE_TOOL, dialogue="提出公开处置。", tool_call=ToolCallRequest(name=decision_tool, arguments=arguments), confidence=0.7)
        steps = (proposed, discussion)
        capability = NPCCapability.PROPOSE_TREATMENT
    return GameNPCTurnProposal(
        goal_update=GoalUpdateProposal(update=GoalUpdateKind.KEEP, public_rationale="保持处置目标。"),
        plan_update=PlanUpdateProposal(update=PlanUpdateKind.CREATE, draft=PlanDraft(steps=steps), public_rationale="形成处置短计划。"),
        decision=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(contribution_id=value.player_contribution.contribution_id, disposition=SuggestionDisposition.ACCEPT, reason_code="public_treatment_request", explanation="依据公开请求选择处置。"),
            capability=capability, action=action, explanation="保持计划与行动一致。",
        ),
    )


def _validate(proposal, value):
    GoalPlanPolicy().validate(proposal, current_goal=value.current_goal, current_plan=value.current_plan, observation=value.case_observation, authority_view=value.authority_view)


def test_treatment_actions_project_only_current_public_candidates(case_definition, qualified_player_state) -> None:
    value = _treatment_input(case_definition, qualified_player_state)
    actions = project_public_treatment_actions(value.case_observation)
    assert {item.treatment_id for item in actions} == {"treatment_public_a", "treatment_public_b"}
    assert all(item.tool_name is ToolName.EXECUTE_TREATMENT for item in actions)
    assert all(item.arguments == {"treatment_id": item.treatment_id} for item in actions)
    context = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(value).messages[-1].content
    assert '"tool_name": "execute_treatment"' in context
    assert '"treatment_id": "treatment_public_a"' in context
    assert "valid_treatment_ids" not in context


def test_matching_treatment_plan_decision_passes_contract_alignment_and_authority(case_definition, qualified_player_state) -> None:
    value = _treatment_input(case_definition, qualified_player_state)
    proposal = _proposal(value)
    _validate(proposal, value)
    step = proposal.plan_update.draft.steps[0]
    state = SimpleNamespace(current_plan=SimpleNamespace(status=AgentPlanStatus.ACTIVE, current_step_index=0, steps=(SimpleNamespace(suggested_tool=step.suggested_tool, public_target_id=step.public_target_id),)))
    assert CooperativeRuntime._action_matches_plan(SimpleNamespace(proposal=proposal.decision), state)
    assert NPCAuthorityPolicy().evaluate(proposal.decision.action).mode.value == "confirmation_required"


@pytest.mark.parametrize("proposal_kwargs, message", [
    ({"step_target": "treatment_public_a", "decision_target": "treatment_public_b"}, "same public target"),
    ({"decision_tool": ToolName.SUBMIT_DIAGNOSIS}, "requires execute_treatment"),
    ({"empty": True}, "propose_treatment PlanStep"),
])
def test_invalid_treatment_plan_decision_is_rejected(case_definition, qualified_player_state, proposal_kwargs, message) -> None:
    value = _treatment_input(case_definition, qualified_player_state)
    with pytest.raises(GoalPlanPolicyError, match=message):
        _validate(_proposal(value, **proposal_kwargs), value)


def test_treatment_discussion_respond_remains_legal(case_definition, qualified_player_state) -> None:
    value = _treatment_input(case_definition, qualified_player_state)
    _validate(_proposal(value, discuss=True), value)


def test_schema_exposes_treatment_tool_target_and_decision_equality() -> None:
    text = json.dumps(GameNPCTurnProposal.model_json_schema(), ensure_ascii=False)
    assert "propose_treatment" in text
    assert "execute_treatment" in text
    assert "public treatment_id" in text
    assert "Decision treatment_id" in text or "Decision.tool_call.arguments.treatment_id" in text
