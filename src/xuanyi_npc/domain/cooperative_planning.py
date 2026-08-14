"""M2-1 bounded Goal/Plan state for one cooperative case session."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .actions import ToolName
from .base import DomainModel, Identifier, NonEmptyText
from .cooperation import NPCCapability


class AgentGoalType(str, Enum):
    RESOLVE_CASE = "resolve_case"
    GATHER_EVIDENCE = "gather_evidence"
    VALIDATE_HYPOTHESIS = "validate_hypothesis"
    FORM_DIAGNOSIS = "form_diagnosis"
    SELECT_TREATMENT = "select_treatment"
    DISCUSS_RISK = "discuss_risk"


class AgentGoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"


class GoalBlockedReason(str, Enum):
    NO_PUBLIC_ACTION = "no_public_action"
    REQUIRED_CAPABILITY_UNAVAILABLE = "required_capability_unavailable"
    WAITING_FOR_PLAYER = "waiting_for_player"
    CASE_NO_LONGER_ACTIVE = "case_no_longer_active"


class GoalConditionType(str, Enum):
    MINIMUM_CLUE_COUNT = "minimum_clue_count"
    INVESTIGATION_COMPLETED = "investigation_completed"
    PUBLIC_REQUIREMENT_SATISFIED = "public_requirement_satisfied"
    DIAGNOSIS_READY = "diagnosis_ready"
    DIAGNOSIS_SUBMITTED = "diagnosis_submitted"
    TREATMENT_AVAILABLE = "treatment_available"
    CASE_COMPLETED = "case_completed"
    PLAYER_RISK_RESPONSE_RECEIVED = "player_risk_response_received"


class GoalCondition(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    condition_type: GoalConditionType
    reference_id: Identifier | None = None
    threshold: Annotated[StrictInt, Field(ge=1, le=100)] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "GoalCondition":
        if self.condition_type is GoalConditionType.MINIMUM_CLUE_COUNT:
            if self.threshold is None or self.reference_id is not None:
                raise ValueError("minimum clue condition requires only threshold")
        elif self.condition_type in {
            GoalConditionType.INVESTIGATION_COMPLETED,
            GoalConditionType.PUBLIC_REQUIREMENT_SATISFIED,
        }:
            if self.reference_id is None or self.threshold is not None:
                raise ValueError("referenced condition requires only reference_id")
        elif self.reference_id is not None or self.threshold is not None:
            raise ValueError("boolean condition cannot contain parameters")
        return self


class AgentGoalState(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: Identifier
    goal_type: AgentGoalType
    public_description: NonEmptyText
    status: AgentGoalStatus
    priority: Annotated[StrictInt, Field(ge=0, le=100)]
    evidence_requirements: tuple[GoalCondition, ...] = ()
    completion_condition: GoalCondition
    source_contribution_id: Identifier | None = None
    blocked_reason: GoalBlockedReason | None = None
    created_turn_id: Identifier
    updated_turn_id: Identifier
    revision: Annotated[StrictInt, Field(ge=1)] = 1

    @model_validator(mode="after")
    def validate_status(self) -> "AgentGoalState":
        if self.status is AgentGoalStatus.BLOCKED:
            if self.blocked_reason is None:
                raise ValueError("blocked goal requires blocked_reason")
        elif self.blocked_reason is not None:
            raise ValueError("only blocked goal can contain blocked_reason")
        if self.goal_type is AgentGoalType.RESOLVE_CASE and self.completion_condition.condition_type is not GoalConditionType.CASE_COMPLETED:
            raise ValueError("episode resolve goal must complete with the case")
        return self


class AgentPlanStatus(str, Enum):
    ACTIVE = "active"
    NEEDS_REVISION = "needs_revision"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    OBSOLETE = "obsolete"
    BLOCKED = "blocked"


class PlanStepIntent(str, Enum):
    OBSERVE = "observe"
    QUESTION = "question"
    INSPECT = "inspect"
    INVESTIGATE = "investigate"
    ANALYZE_EVIDENCE = "analyze_evidence"
    DISCUSS_WITH_PLAYER = "discuss_with_player"
    PROPOSE_DIAGNOSIS = "propose_diagnosis"
    DISCUSS_TREATMENT = "discuss_treatment"
    PROPOSE_TREATMENT = "propose_treatment"


class ExpectedInformationKind(str, Enum):
    PATIENT_PRESENTATION = "patient_presentation"
    TESTIMONY = "testimony"
    OBJECT_TRACE = "object_trace"
    QI_TRACE = "qi_trace"
    LOCATION_TRACE = "location_trace"
    EVIDENCE_RELATION = "evidence_relation"
    PLAYER_JUDGMENT = "player_judgment"


INVESTIGATION_TOOLS = frozenset({
    ToolName.OBSERVE_PATIENT,
    ToolName.QUESTION_PATIENT,
    ToolName.INSPECT_OBJECT,
    ToolName.OBSERVE_QI,
    ToolName.INVESTIGATE_LOCATION,
})
PLANNABLE_TOOLS = INVESTIGATION_TOOLS | {
    ToolName.SUBMIT_DIAGNOSIS,
    ToolName.EXECUTE_TREATMENT,
}
GOAL_PLANNABLE_TOOLS = {
    AgentGoalType.RESOLVE_CASE: PLANNABLE_TOOLS,
    AgentGoalType.GATHER_EVIDENCE: INVESTIGATION_TOOLS,
    AgentGoalType.VALIDATE_HYPOTHESIS: INVESTIGATION_TOOLS,
    AgentGoalType.FORM_DIAGNOSIS: frozenset({ToolName.SUBMIT_DIAGNOSIS}),
    AgentGoalType.SELECT_TREATMENT: frozenset({ToolName.EXECUTE_TREATMENT}),
    AgentGoalType.DISCUSS_RISK: frozenset({ToolName.EXECUTE_TREATMENT}),
}


class PlanStep(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: Identifier
    ordinal: Annotated[StrictInt, Field(ge=0, le=3)]
    intent: PlanStepIntent
    capability: NPCCapability
    suggested_tool: ToolName | None = None
    public_target_id: Identifier | None = None
    public_summary: NonEmptyText
    expected_information: ExpectedInformationKind | None = None
    completion_signal: GoalCondition
    status: PlanStepStatus

    @model_validator(mode="after")
    def validate_tool_capability(self) -> "PlanStep":
        if self.suggested_tool is None:
            if self.capability is NPCCapability.USE_TOOL:
                raise ValueError("tool capability requires suggested_tool")
            return self
        if self.suggested_tool not in PLANNABLE_TOOLS:
            raise ValueError("tool is not plannable")
        if self.public_target_id is None:
            raise ValueError("planned tool requires public_target_id")
        if self.suggested_tool in INVESTIGATION_TOOLS and self.capability is not NPCCapability.USE_TOOL:
            raise ValueError("investigation plan requires use_tool capability")
        if self.suggested_tool is ToolName.SUBMIT_DIAGNOSIS and self.capability is not NPCCapability.PROPOSE_DIAGNOSIS:
            raise ValueError("diagnosis plan remains a proposal")
        if self.suggested_tool is ToolName.EXECUTE_TREATMENT and self.capability is not NPCCapability.PROPOSE_TREATMENT:
            raise ValueError("treatment plan remains a proposal")
        return self


class AgentPlan(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: Identifier
    goal_id: Identifier
    status: AgentPlanStatus
    steps: tuple[PlanStep, ...] = Field(min_length=2, max_length=4)
    current_step_index: Annotated[StrictInt, Field(ge=0, le=3)]
    based_on_observation_revision: Annotated[StrictInt, Field(ge=0)]
    source_contribution_id: Identifier | None = None
    created_turn_id: Identifier
    updated_turn_id: Identifier
    revision: Annotated[StrictInt, Field(ge=1)] = 1

    @model_validator(mode="after")
    def validate_steps(self) -> "AgentPlan":
        if tuple(item.ordinal for item in self.steps) != tuple(range(len(self.steps))):
            raise ValueError("plan step ordinals must be contiguous from zero")
        if len({item.step_id for item in self.steps}) != len(self.steps):
            raise ValueError("plan step IDs must be unique")
        if self.current_step_index >= len(self.steps):
            raise ValueError("current_step_index is outside plan")
        active = tuple(index for index, item in enumerate(self.steps) if item.status is PlanStepStatus.ACTIVE)
        if self.status is AgentPlanStatus.ACTIVE:
            if active != (self.current_step_index,):
                raise ValueError("active plan requires exactly its current step active")
        elif active:
            raise ValueError("inactive plan cannot contain an active step")
        return self


class PlanEvaluationOutcome(str, Enum):
    KEEP_PLAN = "keep_plan"
    REVISE_PLAN = "revise_plan"
    COMPLETE_GOAL = "complete_goal"
    ABANDON_PLAN = "abandon_plan"


class PlanEvaluationReason(str, Enum):
    EXPECTED_EVIDENCE_FOUND = "expected_evidence_found"
    EXPECTED_EVIDENCE_MISSING = "expected_evidence_missing"
    NEW_EVIDENCE_CHANGES_DIRECTION = "new_evidence_changes_direction"
    REQUESTED_TOOL_UNAVAILABLE = "requested_tool_unavailable"
    PLAYER_CONTRIBUTION_CHANGES_PRIORITY = "player_contribution_changes_priority"
    GOAL_COMPLETED = "goal_completed"
    GOAL_BLOCKED = "goal_blocked"
    PLAN_NO_LONGER_VALID = "plan_no_longer_valid"
    STEP_COMPLETED = "step_completed"


class PlanEvaluation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_id: Identifier
    plan_id: Identifier
    outcome: PlanEvaluationOutcome
    reason_code: PlanEvaluationReason
    observation_revision_before: Annotated[StrictInt, Field(ge=0)]
    observation_revision_after: Annotated[StrictInt, Field(ge=0)]
    discovered_clue_ids: tuple[Identifier, ...] = ()
    completed_step_ids: tuple[Identifier, ...] = ()
    obsolete_step_ids: tuple[Identifier, ...] = ()
    next_goal_status: AgentGoalStatus
    public_summary: NonEmptyText
    evaluated_turn_id: Identifier

    @model_validator(mode="after")
    def validate_revisions(self) -> "PlanEvaluation":
        if self.observation_revision_after < self.observation_revision_before:
            raise ValueError("observation revision cannot move backwards")
        if set(self.completed_step_ids).intersection(self.obsolete_step_ids):
            raise ValueError("a step cannot be completed and obsolete")
        return self


class CooperativeAgentState(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["cooperative_agent_state_m2_v1"] = "cooperative_agent_state_m2_v1"
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    episode_goal: AgentGoalState
    current_goal: AgentGoalState
    current_plan: AgentPlan | None = None
    last_plan_evaluation: PlanEvaluation | None = None
    revision: Annotated[StrictInt, Field(ge=1)]
    updated_turn_id: Identifier

    @model_validator(mode="after")
    def validate_goal_plan_scope(self) -> "CooperativeAgentState":
        if self.episode_goal.goal_type is not AgentGoalType.RESOLVE_CASE:
            raise ValueError("episode_goal must resolve the case")
        if self.current_plan is not None and self.current_plan.goal_id != self.current_goal.goal_id:
            raise ValueError("current plan must belong to current goal")
        if self.current_plan is not None:
            if self.current_plan.status is AgentPlanStatus.ACTIVE and self.current_goal.status is not AgentGoalStatus.ACTIVE:
                raise ValueError("active plan requires an active current goal")
            allowed_tools = GOAL_PLANNABLE_TOOLS[self.current_goal.goal_type]
            if any(
                step.suggested_tool is not None
                and step.suggested_tool not in allowed_tools
                for step in self.current_plan.steps
            ):
                raise ValueError("plan tool is not aligned with current goal")
        if self.last_plan_evaluation is not None:
            if self.current_plan is None or self.last_plan_evaluation.plan_id != self.current_plan.plan_id:
                raise ValueError("last evaluation must belong to current plan")
        return self
