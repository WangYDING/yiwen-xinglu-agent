"""Deterministic validation for untrusted M2 Goal/Plan proposals."""

from xuanyi_npc.application.views import CaseObservation
from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.domain.actions import ToolName
from xuanyi_npc.domain.cases import CaseSessionStatus
from xuanyi_npc.domain.cooperation import NPCAuthorityView, NPCCapability
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    GOAL_PLANNABLE_TOOLS,
    INVESTIGATION_TOOLS,
)
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalUpdateKind,
    PlanUpdateKind,
)


class GoalPlanPolicyError(ValueError):
    pass


class GoalPlanPolicy:
    """Reject invalid drafts before they can become authoritative state."""

    def validate(
        self,
        proposal: GameNPCTurnProposal,
        *,
        current_goal: AgentGoalState | None,
        current_plan: AgentPlan | None,
        observation: CaseObservation,
        authority_view: NPCAuthorityView,
    ) -> None:
        goal_type = self._goal_type(proposal, current_goal)
        if (
            current_goal is not None
            and current_goal.status is not AgentGoalStatus.ACTIVE
            and proposal.goal_update.update not in {GoalUpdateKind.REPLACE, GoalUpdateKind.ABANDON}
        ):
            raise GoalPlanPolicyError("a terminal or blocked goal cannot be kept")
        self._validate_goal_phase(proposal, goal_type, observation)
        self._validate_goal_references(proposal, observation)
        self._validate_plan_operation(proposal, current_plan)
        self._validate_steps(proposal, goal_type, observation, authority_view)

    @staticmethod
    def _goal_type(
        proposal: GameNPCTurnProposal,
        current_goal: AgentGoalState | None,
    ) -> AgentGoalType:
        update = proposal.goal_update
        if update.update is GoalUpdateKind.REPLACE:
            assert update.draft is not None
            return update.draft.goal_type
        if current_goal is None:
            raise GoalPlanPolicyError("a current goal is required unless replacing it")
        return current_goal.goal_type

    @staticmethod
    def _validate_goal_phase(
        proposal: GameNPCTurnProposal,
        goal_type: AgentGoalType,
        observation: CaseObservation,
    ) -> None:
        if observation.session_status is not CaseSessionStatus.ACTIVE:
            if proposal.goal_update.update not in {GoalUpdateKind.BLOCK, GoalUpdateKind.ABANDON}:
                raise GoalPlanPolicyError("inactive case cannot keep or create an active goal")
            return
        if goal_type in {AgentGoalType.GATHER_EVIDENCE, AgentGoalType.VALIDATE_HYPOTHESIS}:
            if not observation.available_investigations:
                raise GoalPlanPolicyError("evidence goal has no public investigation")
        elif goal_type is AgentGoalType.FORM_DIAGNOSIS:
            if not observation.can_submit_diagnosis:
                raise GoalPlanPolicyError("diagnosis goal is inconsistent with case phase")
        elif goal_type in {AgentGoalType.SELECT_TREATMENT, AgentGoalType.DISCUSS_RISK}:
            if observation.submitted_diagnosis_id is None or not observation.available_treatments:
                raise GoalPlanPolicyError("treatment goal is inconsistent with case phase")

    @staticmethod
    def _validate_goal_references(
        proposal: GameNPCTurnProposal,
        observation: CaseObservation,
    ) -> None:
        draft = proposal.goal_update.draft
        if draft is None:
            return
        public_ids = {
            observation.case_id,
            observation.patient_id,
            *(item.clue_id for item in observation.discovered_clues),
            *(item.investigation_id for item in observation.available_investigations),
            *(item.target_id for item in observation.available_investigations),
            *(item.diagnosis_id for item in observation.diagnosis_candidates),
            *(item.treatment_id for item in observation.available_treatments),
        }
        conditions = (*draft.evidence_requirements, draft.completion_condition)
        if any(item.reference_id is not None and item.reference_id not in public_ids for item in conditions):
            raise GoalPlanPolicyError("goal references a hidden, stale, or unavailable target")

    @staticmethod
    def _validate_plan_operation(
        proposal: GameNPCTurnProposal,
        current_plan: AgentPlan | None,
    ) -> None:
        update = proposal.plan_update.update
        goal_update = proposal.goal_update.update
        if goal_update in {GoalUpdateKind.BLOCK, GoalUpdateKind.ABANDON} and update is not PlanUpdateKind.ABANDON:
            raise GoalPlanPolicyError("blocked or abandoned goal requires abandoning its plan")
        if goal_update is GoalUpdateKind.REPLACE and current_plan is not None and update is not PlanUpdateKind.REVISE:
            raise GoalPlanPolicyError("replacing a goal requires revising its existing plan")
        if update is PlanUpdateKind.KEEP and (
            current_plan is None or current_plan.status is not AgentPlanStatus.ACTIVE
        ):
            raise GoalPlanPolicyError("can only keep an active current plan")
        if update is PlanUpdateKind.CREATE and current_plan is not None:
            raise GoalPlanPolicyError("cannot create over an existing plan")
        if update is PlanUpdateKind.REVISE and current_plan is None:
            raise GoalPlanPolicyError("cannot revise a missing plan")

    @staticmethod
    def _validate_steps(
        proposal: GameNPCTurnProposal,
        goal_type: AgentGoalType,
        observation: CaseObservation,
        authority_view: NPCAuthorityView,
    ) -> None:
        draft = proposal.plan_update.draft
        if draft is None:
            return
        public_investigations = {
            item.investigation_id: item for item in observation.available_investigations
        }
        public_diagnoses = {item.diagnosis_id for item in observation.diagnosis_candidates}
        public_treatments = {item.treatment_id for item in observation.available_treatments}
        public_entities = {
            observation.patient_id,
            *(item.clue_id for item in observation.discovered_clues),
            *(item.target_id for item in observation.available_investigations),
            *public_diagnoses,
            *public_treatments,
        }
        seen_investigations: set[str] = set()
        allowed_by_authority = {
            *authority_view.autonomous_tools,
            *authority_view.proposal_only_tools,
            *authority_view.confirmation_required_tools,
        }
        for step in draft.steps:
            tool = step.suggested_tool
            if tool is None:
                if step.capability is NPCCapability.USE_TOOL:
                    raise GoalPlanPolicyError("use_tool step requires a suggested tool")
                if step.public_target_id is not None and step.public_target_id not in public_entities:
                    raise GoalPlanPolicyError("non-tool plan target is not public")
                continue
            if tool not in GOAL_PLANNABLE_TOOLS[goal_type]:
                raise GoalPlanPolicyError("planned tool is not aligned with goal type")
            if tool not in allowed_by_authority:
                raise GoalPlanPolicyError("planned tool is outside the authority view")
            target = step.public_target_id
            if target is None:
                raise GoalPlanPolicyError("planned tool requires a public target")
            if tool in INVESTIGATION_TOOLS:
                option = public_investigations.get(target)
                if option is None:
                    raise GoalPlanPolicyError("investigation target is hidden, stale, or unavailable")
                if INVESTIGATION_TOOL_BY_ACTION[option.action_type] is not tool:
                    raise GoalPlanPolicyError("investigation tool does not match its public target")
                if target in seen_investigations:
                    raise GoalPlanPolicyError("plan repeats an investigation without purpose")
                seen_investigations.add(target)
                if step.capability is not NPCCapability.USE_TOOL:
                    raise GoalPlanPolicyError("investigation requires use_tool capability")
            elif tool is ToolName.SUBMIT_DIAGNOSIS:
                if target not in public_diagnoses or step.capability is not NPCCapability.PROPOSE_DIAGNOSIS:
                    raise GoalPlanPolicyError("diagnosis step must remain a public proposal")
            elif tool is ToolName.EXECUTE_TREATMENT:
                if target not in public_treatments or step.capability is not NPCCapability.PROPOSE_TREATMENT:
                    raise GoalPlanPolicyError("treatment step must remain a public proposal")
