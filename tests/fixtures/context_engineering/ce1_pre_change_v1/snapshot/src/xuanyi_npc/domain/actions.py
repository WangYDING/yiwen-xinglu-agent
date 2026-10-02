"""Safe structured output accepted from the V0 Agent boundary."""

from enum import Enum
from typing import Annotated

from pydantic import Field, JsonValue, StrictFloat, model_validator

from .base import DomainModel, Identifier, NonEmptyText


class AgentActionType(str, Enum):
    RESPOND = "respond"
    USE_TOOL = "use_tool"


class ToolName(str, Enum):
    GET_PLAYER_VIEW = "get_player_view"
    GET_CASE_OBSERVATION = "get_case_observation"
    OBSERVE_PATIENT = "observe_patient"
    QUESTION_PATIENT = "question_patient"
    INSPECT_OBJECT = "inspect_object"
    OBSERVE_QI = "observe_qi"
    INVESTIGATE_LOCATION = "investigate_location"
    SUBMIT_DIAGNOSIS = "submit_diagnosis"
    EXECUTE_TREATMENT = "execute_treatment"


class ToolCallRequest(DomainModel):
    name: ToolName
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class AgentAction(DomainModel):
    action_id: Identifier
    action_type: AgentActionType
    dialogue: NonEmptyText
    tool_call: ToolCallRequest | None = None
    confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_action_shape(self) -> "AgentAction":
        if self.action_type is AgentActionType.RESPOND:
            if self.tool_call is not None:
                raise ValueError("respond actions cannot contain tool calls")
        elif self.action_type is AgentActionType.USE_TOOL:
            if self.tool_call is None:
                raise ValueError("use_tool actions require tool_call")
        return self
