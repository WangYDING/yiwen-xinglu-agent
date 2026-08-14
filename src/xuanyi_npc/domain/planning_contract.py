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
    """One future candidate intent, never an executable ToolCallRequest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: PlanStepIntent
    capability: NPCCapability
    suggested_tool: ToolName | None = None
    public_target_id: Identifier | None = None
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


class GameNPCTurnProposal(DomainModel):
    """One model proposal: planning intent plus exactly one M1 decision/action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_update: GoalUpdateProposal
    plan_update: PlanUpdateProposal
    decision: GameNPCDecisionProposal
