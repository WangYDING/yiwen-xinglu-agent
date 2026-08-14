import pytest
from pydantic import ValidationError

from xuanyi_npc.domain import ToolName
from xuanyi_npc.domain.cooperation import NPCCapability
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    CooperativeAgentState,
    ExpectedInformationKind,
    GoalBlockedReason,
    GoalCondition,
    GoalConditionType,
    PlanEvaluation,
    PlanEvaluationOutcome,
    PlanEvaluationReason,
    PlanStep,
    PlanStepIntent,
    PlanStepStatus,
)


def episode_goal() -> AgentGoalState:
    return AgentGoalState(
        goal_id="goal_episode",
        goal_type=AgentGoalType.RESOLVE_CASE,
        public_description="完成当前病例并形成可验证判断。",
        status=AgentGoalStatus.ACTIVE,
        priority=100,
        completion_condition=GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED),
        created_turn_id="turn_initial",
        updated_turn_id="turn_initial",
    )


def current_goal(status=AgentGoalStatus.ACTIVE) -> AgentGoalState:
    return AgentGoalState(
        goal_id="goal_evidence",
        goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="补足当前公开病例证据。",
        status=status,
        priority=80,
        evidence_requirements=(GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=2),),
        completion_condition=GoalCondition(condition_type=GoalConditionType.DIAGNOSIS_READY),
        created_turn_id="turn_initial",
        updated_turn_id="turn_initial",
    )


def step(index: int, *, status: PlanStepStatus, tool=ToolName.OBSERVE_PATIENT) -> PlanStep:
    return PlanStep(
        step_id=f"step_{index}",
        ordinal=index,
        intent=PlanStepIntent.OBSERVE,
        capability=NPCCapability.USE_TOOL,
        suggested_tool=tool,
        public_target_id=f"investigation_{index}",
        public_summary=f"执行第 {index + 1} 项公开调查。",
        expected_information=ExpectedInformationKind.PATIENT_PRESENTATION,
        completion_signal=GoalCondition(
            condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
            reference_id=f"investigation_{index}",
        ),
        status=status,
    )


def active_plan() -> AgentPlan:
    return AgentPlan(
        plan_id="plan_evidence",
        goal_id="goal_evidence",
        status=AgentPlanStatus.ACTIVE,
        steps=(step(0, status=PlanStepStatus.ACTIVE), step(1, status=PlanStepStatus.PENDING)),
        current_step_index=0,
        based_on_observation_revision=0,
        created_turn_id="turn_initial",
        updated_turn_id="turn_initial",
    )


def test_minimal_episode_and_current_goal_are_bounded() -> None:
    state = CooperativeAgentState(
        player_id="player_one",
        case_id="case_one",
        session_id="session_one",
        episode_goal=episode_goal(),
        current_goal=current_goal(),
        current_plan=active_plan(),
        revision=1,
        updated_turn_id="turn_initial",
    )
    assert state.episode_goal.goal_type is AgentGoalType.RESOLVE_CASE
    assert state.current_plan is not None and len(state.current_plan.steps) == 2


def test_goal_is_not_an_open_todo_or_hidden_fact_container() -> None:
    payload = current_goal().model_dump(mode="python")
    payload["goal_type"] = "become_shopkeeper"
    with pytest.raises(ValidationError):
        AgentGoalState.model_validate(payload)
    payload = current_goal().model_dump(mode="python")
    payload["hidden_fact_id"] = "true_root_cause"
    with pytest.raises(ValidationError):
        AgentGoalState.model_validate(payload)


def test_blocked_goal_requires_a_finite_reason() -> None:
    payload = current_goal().model_dump(mode="python")
    payload["status"] = AgentGoalStatus.BLOCKED
    with pytest.raises(ValidationError):
        AgentGoalState.model_validate(payload)
    payload["blocked_reason"] = GoalBlockedReason.NO_PUBLIC_ACTION
    assert AgentGoalState.model_validate(payload).status is AgentGoalStatus.BLOCKED


def test_completed_goal_has_explicit_terminal_status() -> None:
    payload = current_goal().model_dump(mode="python")
    payload.update({"status": AgentGoalStatus.COMPLETED, "updated_turn_id": "turn_complete", "revision": 2})
    completed = AgentGoalState.model_validate(payload)
    assert completed.status is AgentGoalStatus.COMPLETED


@pytest.mark.parametrize("count", (1, 5))
def test_plan_requires_two_to_four_steps(count: int) -> None:
    payload = active_plan().model_dump(mode="python")
    values = []
    for index in range(count):
        item = step(min(index, 3), status=PlanStepStatus.ACTIVE if index == 0 else PlanStepStatus.PENDING).model_dump(mode="python")
        item.update({"step_id": f"step_{index}", "ordinal": index})
        values.append(item)
    payload["steps"] = values
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_plan_step_keeps_diagnosis_and_treatment_as_proposals() -> None:
    diagnosis = step(0, status=PlanStepStatus.ACTIVE).model_dump(mode="python")
    diagnosis["suggested_tool"] = ToolName.SUBMIT_DIAGNOSIS
    with pytest.raises(ValidationError):
        PlanStep.model_validate(diagnosis)
    diagnosis.update({"capability": NPCCapability.PROPOSE_DIAGNOSIS, "intent": PlanStepIntent.PROPOSE_DIAGNOSIS})
    assert PlanStep.model_validate(diagnosis).capability is NPCCapability.PROPOSE_DIAGNOSIS

    treatment = diagnosis | {"suggested_tool": ToolName.EXECUTE_TREATMENT, "capability": NPCCapability.PROPOSE_TREATMENT, "intent": PlanStepIntent.PROPOSE_TREATMENT}
    assert PlanStep.model_validate(treatment).capability is NPCCapability.PROPOSE_TREATMENT


def test_active_plan_has_one_current_step_and_cannot_encode_tool_queue() -> None:
    payload = active_plan().model_dump(mode="python")
    payload["steps"][1]["status"] = PlanStepStatus.ACTIVE
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)
    assert "tool_call" not in PlanStep.model_fields
    assert "arguments" not in PlanStep.model_fields


def test_last_evaluation_must_belong_to_current_plan() -> None:
    evaluation = PlanEvaluation(
        evaluation_id="evaluation_one",
        plan_id="plan_other",
        outcome=PlanEvaluationOutcome.KEEP_PLAN,
        reason_code=PlanEvaluationReason.STEP_COMPLETED,
        observation_revision_before=0,
        observation_revision_after=1,
        completed_step_ids=("step_0",),
        next_goal_status=AgentGoalStatus.ACTIVE,
        public_summary="完成当前调查，计划仍然有效。",
        evaluated_turn_id="turn_one",
    )
    with pytest.raises(ValidationError):
        CooperativeAgentState(
            player_id="player_one", case_id="case_one", session_id="session_one",
            episode_goal=episode_goal(), current_goal=current_goal(),
            current_plan=active_plan(), last_plan_evaluation=evaluation,
            revision=2, updated_turn_id="turn_one",
        )


def test_current_goal_rejects_unaligned_plan_tools() -> None:
    payload = active_plan().model_dump(mode="python")
    payload["steps"][1].update({
        "suggested_tool": ToolName.EXECUTE_TREATMENT,
        "capability": NPCCapability.PROPOSE_TREATMENT,
        "intent": PlanStepIntent.PROPOSE_TREATMENT,
    })
    treatment_plan = AgentPlan.model_validate(payload)
    with pytest.raises(ValidationError, match="aligned"):
        CooperativeAgentState(
            player_id="player_one", case_id="case_one", session_id="session_one",
            episode_goal=episode_goal(), current_goal=current_goal(),
            current_plan=treatment_plan, revision=1, updated_turn_id="turn_initial",
        )


def test_terminal_current_goal_cannot_keep_an_active_plan() -> None:
    with pytest.raises(ValidationError, match="active current goal"):
        CooperativeAgentState(
            player_id="player_one", case_id="case_one", session_id="session_one",
            episode_goal=episode_goal(), current_goal=current_goal(AgentGoalStatus.COMPLETED),
            current_plan=active_plan(), revision=2, updated_turn_id="turn_complete",
        )
