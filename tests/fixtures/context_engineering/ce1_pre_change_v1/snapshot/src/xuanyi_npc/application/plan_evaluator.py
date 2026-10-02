"""Deterministic post-environment evaluation for cooperative short plans."""

from pydantic import ConfigDict

from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.views import CaseObservation
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseSessionStatus, ToolName
from xuanyi_npc.domain.base import DomainModel, Identifier
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentPlan,
    AgentPlanStatus,
    GoalCondition,
    GoalConditionType,
    GoalBlockedReason,
    PlanEvaluation,
    PlanEvaluationOutcome,
    PlanEvaluationReason,
    PlanStep,
    PlanStepStatus,
)


class PlanEvaluationTransition(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation: PlanEvaluation
    goal: AgentGoalState
    plan: AgentPlan


class DeterministicPlanEvaluator:
    def condition_met(self, condition: GoalCondition, observation: CaseObservation) -> bool:
        kind = condition.condition_type
        if kind is GoalConditionType.MINIMUM_CLUE_COUNT:
            return len(observation.discovered_clues) >= condition.threshold
        if kind in {GoalConditionType.INVESTIGATION_COMPLETED, GoalConditionType.PUBLIC_REQUIREMENT_SATISFIED}:
            return condition.reference_id not in {
                item.investigation_id for item in observation.available_investigations
            }
        if kind is GoalConditionType.DIAGNOSIS_READY:
            return observation.can_submit_diagnosis
        if kind is GoalConditionType.DIAGNOSIS_SUBMITTED:
            return observation.submitted_diagnosis_id is not None
        if kind is GoalConditionType.TREATMENT_AVAILABLE:
            return bool(observation.available_treatments)
        if kind is GoalConditionType.CASE_COMPLETED:
            return observation.session_status is CaseSessionStatus.COMPLETED
        return False

    def plan_compatible(self, plan: AgentPlan, observation: CaseObservation) -> bool:
        if plan.status is not AgentPlanStatus.ACTIVE:
            return False
        return self.step_compatible(plan.steps[plan.current_step_index], observation)

    @staticmethod
    def step_compatible(step: PlanStep, observation: CaseObservation) -> bool:
        tool = step.suggested_tool
        target = step.public_target_id
        if tool is None:
            return True
        if tool in INVESTIGATION_TOOL_BY_ACTION.values():
            return any(
                item.investigation_id == target
                and INVESTIGATION_TOOL_BY_ACTION[item.action_type] is tool
                for item in observation.available_investigations
            )
        if tool is ToolName.SUBMIT_DIAGNOSIS:
            return observation.can_submit_diagnosis and target in {
                item.diagnosis_id for item in observation.diagnosis_candidates
            }
        if tool is ToolName.EXECUTE_TREATMENT:
            return target in {item.treatment_id for item in observation.available_treatments}
        return False

    def evaluate(
        self,
        *,
        pre_observation: CaseObservation,
        post_observation: CaseObservation,
        goal: AgentGoalState,
        plan: AgentPlan,
        executed_action: AgentAction,
        tool_succeeded: bool,
        turn_id: Identifier,
        environment_message: str | None = None,
        event_sequences: tuple[int, ...] = (),
        pending_confirmation: object | None = None,
    ) -> PlanEvaluationTransition:
        del executed_action, environment_message, event_sequences, pending_confirmation
        active = plan.steps[plan.current_step_index]
        completed_goal = self.condition_met(goal.completion_condition, post_observation)
        if completed_goal:
            outcome = PlanEvaluationOutcome.COMPLETE_GOAL
            reason = PlanEvaluationReason.GOAL_COMPLETED
        elif post_observation.session_status is CaseSessionStatus.COMPLETED:
            outcome = PlanEvaluationOutcome.ABANDON_PLAN
            reason = PlanEvaluationReason.GOAL_BLOCKED
        elif not tool_succeeded:
            outcome = PlanEvaluationOutcome.REVISE_PLAN
            reason = PlanEvaluationReason.REQUESTED_TOOL_UNAVAILABLE
        else:
            remaining = plan.steps[plan.current_step_index + 1 :]
            if not remaining:
                outcome = PlanEvaluationOutcome.REVISE_PLAN
                reason = PlanEvaluationReason.PLAN_NO_LONGER_VALID
            elif not self.step_compatible(remaining[0], post_observation):
                outcome = PlanEvaluationOutcome.REVISE_PLAN
                reason = PlanEvaluationReason.NEW_EVIDENCE_CHANGES_DIRECTION
            else:
                outcome = PlanEvaluationOutcome.KEEP_PLAN
                reason = (
                    PlanEvaluationReason.EXPECTED_EVIDENCE_FOUND
                    if len(post_observation.discovered_clues) > len(pre_observation.discovered_clues)
                    else PlanEvaluationReason.STEP_COMPLETED
                )

        updated_steps = list(plan.steps)
        completed_ids: tuple[str, ...] = ()
        obsolete_ids: tuple[str, ...] = ()
        if tool_succeeded:
            updated_steps[plan.current_step_index] = active.model_copy(update={"status": PlanStepStatus.COMPLETED})
            completed_ids = (active.step_id,)
        else:
            updated_steps[plan.current_step_index] = active.model_copy(update={"status": PlanStepStatus.BLOCKED})

        if outcome is PlanEvaluationOutcome.KEEP_PLAN:
            next_index = plan.current_step_index + 1
            updated_steps[next_index] = updated_steps[next_index].model_copy(update={"status": PlanStepStatus.ACTIVE})
            plan_status = AgentPlanStatus.ACTIVE
        elif outcome is PlanEvaluationOutcome.COMPLETE_GOAL:
            next_index = min(plan.current_step_index, len(updated_steps) - 1)
            obsolete = []
            for index in range(plan.current_step_index + 1, len(updated_steps)):
                updated_steps[index] = updated_steps[index].model_copy(update={"status": PlanStepStatus.OBSOLETE})
                obsolete.append(updated_steps[index].step_id)
            obsolete_ids = tuple(obsolete)
            plan_status = AgentPlanStatus.COMPLETED
        elif outcome is PlanEvaluationOutcome.ABANDON_PLAN:
            next_index = min(plan.current_step_index, len(updated_steps) - 1)
            obsolete = []
            for index in range(plan.current_step_index + 1, len(updated_steps)):
                updated_steps[index] = updated_steps[index].model_copy(update={"status": PlanStepStatus.OBSOLETE})
                obsolete.append(updated_steps[index].step_id)
            obsolete_ids = tuple(obsolete)
            plan_status = AgentPlanStatus.ABANDONED
        else:
            next_index = min(plan.current_step_index, len(updated_steps) - 1)
            obsolete = []
            for index in range(plan.current_step_index + 1, len(updated_steps)):
                updated_steps[index] = updated_steps[index].model_copy(update={"status": PlanStepStatus.OBSOLETE})
                obsolete.append(updated_steps[index].step_id)
            obsolete_ids = tuple(obsolete)
            plan_status = AgentPlanStatus.NEEDS_REVISION

        next_goal_status = (
            AgentGoalStatus.COMPLETED if completed_goal
            else AgentGoalStatus.BLOCKED if outcome is PlanEvaluationOutcome.ABANDON_PLAN
            else goal.status
        )
        evaluation = PlanEvaluation(
            evaluation_id=f"evaluation_{turn_id}",
            plan_id=plan.plan_id,
            outcome=outcome,
            reason_code=reason,
            observation_revision_before=pre_observation.session_revision,
            observation_revision_after=post_observation.session_revision,
            discovered_clue_ids=tuple(
                sorted(
                    {item.clue_id for item in post_observation.discovered_clues}
                    - {item.clue_id for item in pre_observation.discovered_clues}
                )
            ),
            completed_step_ids=completed_ids,
            obsolete_step_ids=obsolete_ids,
            next_goal_status=next_goal_status,
            public_summary=self._summary(outcome),
            evaluated_turn_id=turn_id,
        )
        goal_changed = completed_goal or outcome is PlanEvaluationOutcome.ABANDON_PLAN
        updated_goal = (
            goal.model_copy(update={
                "status": next_goal_status,
                "blocked_reason": (
                    GoalBlockedReason.CASE_NO_LONGER_ACTIVE
                    if next_goal_status is AgentGoalStatus.BLOCKED else None
                ),
                "updated_turn_id": turn_id,
                "revision": goal.revision + 1,
            })
            if goal_changed else goal
        )
        updated_plan = plan.model_copy(update={
            "status": plan_status,
            "steps": tuple(updated_steps),
            "current_step_index": next_index,
            "based_on_observation_revision": post_observation.session_revision,
            "updated_turn_id": turn_id,
            "revision": plan.revision + 1,
        })
        return PlanEvaluationTransition(evaluation=evaluation, goal=updated_goal, plan=updated_plan)

    @staticmethod
    def _summary(outcome: PlanEvaluationOutcome) -> str:
        return {
            PlanEvaluationOutcome.KEEP_PLAN: "当前步骤已完成，下一步骤仍可继续。",
            PlanEvaluationOutcome.REVISE_PLAN: "环境已变化，当前计划需要在下一轮修订。",
            PlanEvaluationOutcome.COMPLETE_GOAL: "确定性完成条件已经满足。",
            PlanEvaluationOutcome.ABANDON_PLAN: "当前计划已无法继续。",
        }[outcome]
