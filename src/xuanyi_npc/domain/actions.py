"""Schema for constrained future Agent output."""

from enum import Enum
from typing import Annotated

from pydantic import Field, JsonValue, StrictFloat, model_validator

from .base import DomainModel, Identifier, NonEmptyText


class AgentActionType(str, Enum):
    RESPOND = "respond"
    USE_TOOL = "use_tool"
    PROPOSE_STATE_CHANGE = "propose_state_change"


class ToolName(str, Enum):
    GET_PLAYER_STATE = "get_player_state"
    OBSERVE_PATIENT = "observe_patient"
    QUESTION_PATIENT = "question_patient"
    INSPECT_OBJECT = "inspect_object"
    SUBMIT_DIAGNOSIS = "submit_diagnosis"
    RECORD_MEMORY = "record_memory"


class ProposedChangeTarget(str, Enum):
    AFFINITY = "affinity"
    TRUST = "trust"
    RECOGNITION = "recognition"
    SKILL_PROFICIENCY = "skill_proficiency"


class ToolCallRequest(DomainModel):
    name: ToolName
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class StateChangeProposal(DomainModel):
    """A suggestion only; no absolute value or unlock request is accepted."""

    target: ProposedChangeTarget
    delta: Annotated[int, Field(strict=True, ge=-10, le=10)]
    reason: NonEmptyText
    skill_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_skill_target(self) -> "StateChangeProposal":
        is_skill = self.target is ProposedChangeTarget.SKILL_PROFICIENCY
        if is_skill and self.skill_id is None:
            raise ValueError("skill proficiency proposals require skill_id")
        if not is_skill and self.skill_id is not None:
            raise ValueError("skill_id is only valid for skill proficiency proposals")
        return self


class AgentAction(DomainModel):
    action_id: Identifier
    action_type: AgentActionType
    dialogue: NonEmptyText
    tool_call: ToolCallRequest | None = None
    proposed_changes: tuple[StateChangeProposal, ...] = Field(default_factory=tuple)
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_action_shape(self) -> "AgentAction":
        if self.action_type is AgentActionType.RESPOND:
            if self.tool_call is not None or self.proposed_changes:
                raise ValueError("respond actions cannot contain tool calls or state proposals")
        elif self.action_type is AgentActionType.USE_TOOL:
            if self.tool_call is None:
                raise ValueError("use_tool actions require tool_call")
            if self.proposed_changes:
                raise ValueError("use_tool actions cannot contain state proposals")
        elif self.action_type is AgentActionType.PROPOSE_STATE_CHANGE:
            if self.tool_call is not None:
                raise ValueError("state proposals cannot contain a tool call")
            if not self.proposed_changes:
                raise ValueError("propose_state_change actions require at least one proposal")
        return self
