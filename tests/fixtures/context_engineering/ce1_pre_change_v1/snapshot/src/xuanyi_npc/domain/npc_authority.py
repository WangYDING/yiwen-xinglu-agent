"""Deterministic authority contracts for bounded NPC autonomy."""

from pydantic import ConfigDict

from .actions import ToolName
from .base import DomainModel, Identifier
from .cooperation import AuthorityMode, NPCAuthorityView


class AuthorityDecision(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: AuthorityMode
    reason_code: Identifier


AUTONOMOUS_TOOLS = (
    ToolName.GET_PLAYER_VIEW,
    ToolName.GET_CASE_OBSERVATION,
    ToolName.OBSERVE_PATIENT,
    ToolName.QUESTION_PATIENT,
    ToolName.INSPECT_OBJECT,
    ToolName.OBSERVE_QI,
    ToolName.INVESTIGATE_LOCATION,
)

