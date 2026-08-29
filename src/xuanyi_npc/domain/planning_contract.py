"""Model-authored M2 planning proposals; authoritative state stays deterministic."""

from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .actions import ToolName
from .base import DomainModel, Identifier, NonEmptyText
from .cooperation import GameNPCDecisionProposal, NPCCapability
from .cooperative_planning import (
    AgentGoalType,
    ExpectedInformationKind,
    GoalBlockedReason,
    GoalCondition,
    PlanStepIntent,
)


class GoalUpdateKind(str, Enum):
    KEEP = "keep"
    REPLACE = "replace"
    BLOCK = "block"
    ABANDON = "abandon"


class GoalDraft(DomainModel):
    """A bounded intent draft without authoritative identity or lifecycle fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_type: AgentGoalType
    public_description: NonEmptyText
    priority: Annotated[StrictInt, Field(ge=0, le=100)]
    evidence_requirements: tuple[GoalCondition, ...] = ()
    completion_condition: GoalCondition


class GoalUpdateProposal(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    update: GoalUpdateKind
    draft: GoalDraft | None = None
    blocked_reason: GoalBlockedReason | None = None
    public_rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_shape(self) -> "GoalUpdateProposal":
        if self.update is GoalUpdateKind.REPLACE:
            if self.draft is None or self.blocked_reason is not None:
                raise ValueError("replace requires only a goal draft")
        elif self.update is GoalUpdateKind.BLOCK:
            if self.draft is not None or self.blocked_reason is None:
                raise ValueError("block requires only a bounded reason")
        elif self.draft is not None or self.blocked_reason is not None:
            raise ValueError("keep/abandon cannot carry goal state")
        return self


class PlanUpdateKind(str, Enum):
    KEEP = "keep"
    CREATE = "create"
    REVISE = "revise"
    ABANDON = "abandon"


class PlanStepDraft(DomainModel):
    """One future candidate intent, never an executable ToolCallRequest.

    Tool-backed proposal contract: propose_diagnosis uses submit_diagnosis and
    a public diagnosis_id; propose_treatment uses execute_treatment and a public
    treatment_id. Plan and same-turn Decision must reference the same target.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: PlanStepIntent = Field(
        description="Plan intent. propose_diagnosis requires submit_diagnosis plus a public diagnosis target; propose_treatment requires execute_treatment plus a public treatment target."
    )
    capability: NPCCapability = Field(
        description="NPC capability. propose_diagnosis/propose_treatment require their matching proposal tool and public_target_id."
    )
    suggested_tool: ToolName | None = Field(
        default=None,
        description="Required as submit_diagnosis for propose_diagnosis and execute_treatment for propose_treatment; otherwise use the step tool or null for a non-tool step.",
    )
    public_target_id: Identifier | None = Field(
        default=None,
        description="For propose_diagnosis, required and must be a diagnosis_id from the public diagnosis candidates; it must equal Decision.tool_call.arguments.diagnosis_id. For propose_treatment, required and must be a public treatment_id; it must equal Decision.tool_call.arguments.treatment_id.",
    )
    public_summary: NonEmptyText
    expected_information: ExpectedInformationKind | None = None
    completion_signal: GoalCondition


class PlanDraft(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    steps: tuple[PlanStepDraft, ...] = Field(min_length=2, max_length=4)


class PlanUpdateProposal(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    update: PlanUpdateKind
    draft: PlanDraft | None = None
    public_rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_shape(self) -> "PlanUpdateProposal":
        needs_draft = self.update in {PlanUpdateKind.CREATE, PlanUpdateKind.REVISE}
        if needs_draft != (self.draft is not None):
            raise ValueError("create/revise require a draft; keep/abandon forbid one")
        return self


class MemoryUsageProposal(DomainModel):
    """Model-authored draft of selected memory references for later auditing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    used_memory_ids: tuple[Identifier, ...] = ()
    influence_types: tuple[Identifier, ...] = ()
    affected_goal: bool = False
    affected_plan: bool = False
    affected_decision: bool = False
    affected_tool_priority: bool = False
    affected_communication: bool = False
    public_effect_summary: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "MemoryUsageProposal":
        if len(set(self.used_memory_ids)) != len(self.used_memory_ids):
            raise ValueError("used memory IDs must be unique")
        if len(set(self.influence_types)) != len(self.influence_types):
            raise ValueError("influence types must be unique")
        affected = (
            self.affected_goal
            or self.affected_plan
            or self.affected_decision
            or self.affected_tool_priority
            or self.affected_communication
        )
        if not self.used_memory_ids:
            if affected or self.influence_types or self.public_effect_summary is not None:
                raise ValueError("empty memory usage cannot claim influence")
        elif self.public_effect_summary is None:
            raise ValueError("used memory requires a public effect summary")
        return self


class GameNPCTurnProposal(DomainModel):
    """One model proposal: planning intent plus exactly one M1 decision/action.

    Plan and Decision are one contract. A propose_diagnosis PlanStep must use
    suggested_tool=submit_diagnosis and a public diagnosis candidate as
    public_target_id. When Decision calls submit_diagnosis in the same turn,
    its diagnosis_id must equal the resulting active PlanStep public_target_id.
    PlanStep public_target_id must equal Decision.tool_call.arguments.diagnosis_id.
    A propose_treatment PlanStep similarly uses execute_treatment and a public
    treatment_id equal to the same-turn Decision treatment_id.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_update: GoalUpdateProposal
    plan_update: PlanUpdateProposal
    decision: GameNPCDecisionProposal
    memory_usage: MemoryUsageProposal | None = None
