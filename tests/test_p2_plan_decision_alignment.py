import pytest
from types import SimpleNamespace

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.goal_plan_policy import GoalPlanPolicy, GoalPlanPolicyError
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import (
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContributionEvaluation,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalType,
    AgentPlanStatus,
    GoalCondition,
    GoalConditionType,
    PlanStepIntent,
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
from tests.test_m2_planning_contract import planning_input


def _diagnosis_input(case_definition, qualified_player_state):
    value = planning_input(case_definition, qualified_player_state, "请根据公开证据形成诊断。")
    observation = value.case_observation.model_copy(update={"can_submit_diagnosis": True})
    goal = value.current_goal.model_copy(update={
        "goal_type": AgentGoalType.FORM_DIAGNOSIS,
        "completion_condition": GoalCondition(
            condition_type=GoalConditionType.DIAGNOSIS_SUBMITTED
        ),
    })
    return value.model_copy(update={"case_observation": observation, "current_goal": goal})


def _proposal(value, *, step_tool=ToolName.SUBMIT_DIAGNOSIS, step_target=None,
              decision_tool=ToolName.SUBMIT_DIAGNOSIS, decision_target=None,
              respond=False):
    diagnosis_a = value.case_observation.diagnosis_candidates[0].diagnosis_id
    diagnosis_b = value.case_observation.diagnosis_candidates[1].diagnosis_id
    step_target = diagnosis_a if step_target is None else step_target
    decision_target = diagnosis_a if decision_target is None else decision_target
    first = PlanStepDraft(
        intent=PlanStepIntent.PROPOSE_DIAGNOSIS,
        capability=NPCCapability.PROPOSE_DIAGNOSIS,
        suggested_tool=step_tool,
        public_target_id=step_target,
        public_summary="提出一个公开诊断候选。",
        completion_signal=GoalCondition(
            condition_type=GoalConditionType.DIAGNOSIS_SUBMITTED
        ),
    )
    second = PlanStepDraft(
        intent=PlanStepIntent.DISCUSS_WITH_PLAYER,
        capability=NPCCapability.EXPLAIN,
        public_summary="与玩家核对诊断依据。",
        completion_signal=GoalCondition(
            condition_type=GoalConditionType.PLAYER_RISK_RESPONSE_RECEIVED
        ),
    )
    action = (
        AgentAction(
            action_id=f"npc_{value.turn_id}",
            action_type=AgentActionType.RESPOND,
            dialogue="先继续解释公开证据。",
            confidence=0.5,
        )
        if respond
        else AgentAction(
            action_id=f"npc_{value.turn_id}",
            action_type=AgentActionType.USE_TOOL,
            dialogue="提出公开诊断候选。",
            tool_call=ToolCallRequest(
                name=decision_tool,
                arguments=(
                    {"diagnosis_id": decision_target, "evidence_clue_ids": []}
                    if decision_tool is ToolName.SUBMIT_DIAGNOSIS
                    else {"investigation_id": value.case_observation.available_investigations[0].investigation_id}
                ),
            ),
            confidence=0.7,
        )
    )
    return GameNPCTurnProposal(
        goal_update=GoalUpdateProposal(
            update=GoalUpdateKind.KEEP, public_rationale="保持诊断目标。"
        ),
        plan_update=PlanUpdateProposal(
            update=PlanUpdateKind.CREATE,
            draft=PlanDraft(steps=(first, second)),
            public_rationale="形成诊断短计划。",
        ),
        decision=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=value.player_contribution.contribution_id,
                disposition=SuggestionDisposition.ACCEPT,
                reason_code="public_diagnosis_request",
                explanation="依据公开请求形成诊断提案。",
            ),
            capability=(NPCCapability.EXPLAIN if respond else NPCCapability.PROPOSE_DIAGNOSIS),
            action=action,
            explanation="保持计划与行动一致。",
        ),
    ), diagnosis_a, diagnosis_b


def _validate(proposal, value):
    GoalPlanPolicy().validate(
        proposal,
        current_goal=value.current_goal,
        current_plan=value.current_plan,
        observation=value.case_observation,
        authority_view=value.authority_view,
    )


def test_consistent_diagnosis_plan_and_decision_pass_contract(case_definition, qualified_player_state) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    proposal, diagnosis_a, _ = _proposal(value)

    _validate(proposal, value)

    step = proposal.plan_update.draft.steps[0]
    assert step.suggested_tool is ToolName.SUBMIT_DIAGNOSIS
    assert step.public_target_id == diagnosis_a
    assert proposal.decision.action.tool_call.arguments["diagnosis_id"] == diagnosis_a
    decision = SimpleNamespace(proposal=proposal.decision)
    state = SimpleNamespace(current_plan=SimpleNamespace(
        status=AgentPlanStatus.ACTIVE,
        current_step_index=0,
        steps=(SimpleNamespace(
            suggested_tool=step.suggested_tool,
            public_target_id=step.public_target_id,
        ),),
    ))
    assert CooperativeRuntime._action_matches_plan(decision, state) is True
    assert NPCAuthorityPolicy().evaluate(proposal.decision.action).mode.value == "proposal_only"


def test_empty_diagnosis_step_is_repaired_before_runtime_alignment(case_definition, qualified_player_state) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    invalid, _, _ = _proposal(value, step_tool=None, step_target=None)
    invalid_step = invalid.plan_update.draft.steps[0].model_copy(update={
        "suggested_tool": None,
        "public_target_id": None,
    })
    invalid = invalid.model_copy(update={
        "plan_update": invalid.plan_update.model_copy(update={
            "draft": invalid.plan_update.draft.model_copy(update={
                "steps": (invalid_step, invalid.plan_update.draft.steps[1])
            })
        })
    })
    valid, diagnosis_a, _ = _proposal(value)
    agent = GameNPCAgent(ScriptedFakeLLM([
        invalid.model_dump_json(),
        valid.model_dump_json(),
    ]))

    result = agent.propose_turn(value)

    execution = agent.last_planning_execution()
    assert execution.attempts == 2
    assert result.plan_update.draft.steps[0].suggested_tool is ToolName.SUBMIT_DIAGNOSIS
    assert result.plan_update.draft.steps[0].public_target_id == diagnosis_a


def test_wrong_diagnosis_target_is_rejected(case_definition, qualified_player_state) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    base, diagnosis_a, diagnosis_b = _proposal(value)
    wrong, _, _ = _proposal(value, step_target=diagnosis_a, decision_target=diagnosis_b)

    _validate(base, value)
    with pytest.raises(GoalPlanPolicyError, match="same public target"):
        _validate(wrong, value)


def test_wrong_diagnosis_tool_is_rejected(case_definition, qualified_player_state) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    option = value.case_observation.available_investigations[0]
    wrong_tool = {
        "observe_patient": ToolName.OBSERVE_PATIENT,
        "question_patient": ToolName.QUESTION_PATIENT,
        "inspect_object": ToolName.INSPECT_OBJECT,
        "observe_qi": ToolName.OBSERVE_QI,
        "investigate_location": ToolName.INVESTIGATE_LOCATION,
    }[option.action_type.value]
    proposal, _, _ = _proposal(value, decision_tool=wrong_tool)

    with pytest.raises(GoalPlanPolicyError, match="requires submit_diagnosis"):
        _validate(proposal, value)


def test_respond_is_not_globally_forbidden_in_diagnosis_phase(case_definition, qualified_player_state) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    proposal, _, _ = _proposal(value, respond=True)

    _validate(proposal, value)


def test_respond_cannot_persist_a_structurally_empty_diagnosis_step(
    case_definition, qualified_player_state
) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    proposal, _, _ = _proposal(value, respond=True)
    empty = proposal.plan_update.draft.steps[0].model_copy(update={
        "suggested_tool": None,
        "public_target_id": None,
    })
    proposal = proposal.model_copy(update={
        "plan_update": proposal.plan_update.model_copy(update={
            "draft": proposal.plan_update.draft.model_copy(update={
                "steps": (empty, proposal.plan_update.draft.steps[1])
            })
        })
    })

    with pytest.raises(GoalPlanPolicyError, match="propose_diagnosis PlanStep"):
        _validate(proposal, value)
