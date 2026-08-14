"""M1 contracts for one-turn human/NPC cooperation."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .actions import AgentAction, ToolName
from .base import DomainModel, Identifier, NonEmptyText


class PlayerContributionType(str, Enum):
    SUGGESTION = "suggestion"
    HYPOTHESIS = "hypothesis"
    QUESTION = "question"
    CHALLENGE = "challenge"
    EVIDENCE_INTERPRETATION = "evidence_interpretation"
    APPROVAL = "approval"
    REJECTION = "rejection"
    GENERAL_MESSAGE = "general_message"


class PlayerContribution(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    contribution_id: Identifier
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    contribution_type: PlayerContributionType
    public_text: NonEmptyText
    suggested_tool: ToolName | None = None
    referenced_public_entity_ids: tuple[Identifier, ...] = ()
    referenced_clue_ids: tuple[Identifier, ...] = ()
    responds_to_decision_id: Identifier | None = None
    created_at: datetime


class SuggestionDisposition(str, Enum):
    ACCEPT = "accept"
    PARTIAL_ACCEPT = "partial_accept"
    REJECT = "reject"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    PROPOSE_ALTERNATIVE = "propose_alternative"


class PlayerContributionEvaluation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    contribution_id: Identifier
    disposition: SuggestionDisposition
    reason_code: Identifier
    explanation: NonEmptyText


class NPCCapability(str, Enum):
    SPEAK = "speak"
    EXPLAIN = "explain"
    ASK_PLAYER = "ask_player"
    CLARIFY = "clarify"
    GIVE_HINT = "give_hint"
    CHALLENGE_REASONING = "challenge_reasoning"
    EXPLAIN_EVIDENCE_GAP = "explain_evidence_gap"
    ASK_REFLECTION = "ask_reflection"
    RISK_WARNING = "risk_warning"
    USE_TOOL = "use_tool"
    PROPOSE_DIAGNOSIS = "propose_diagnosis"
    PROPOSE_TREATMENT = "propose_treatment"


class AuthorityMode(str, Enum):
    AUTONOMOUS = "autonomous"
    PROPOSAL_ONLY = "proposal_only"
    CONFIRMATION_REQUIRED = "confirmation_required"
    FORBIDDEN = "forbidden"


class NPCAuthorityView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    autonomous_tools: tuple[ToolName, ...]
    proposal_only_tools: tuple[ToolName, ...]
    confirmation_required_tools: tuple[ToolName, ...]
    forbidden_tools: tuple[ToolName, ...]


class GameNPCDecisionProposal(DomainModel):
    """The model-authored, structured portion of an M1 decision."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    contribution_evaluation: PlayerContributionEvaluation | None
    capability: NPCCapability
    action: AgentAction
    explanation: NonEmptyText

    @model_validator(mode="after")
    def require_evaluation_for_contribution(self) -> "GameNPCDecisionProposal":
        return self


class GameNPCDecision(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: Identifier
    turn_id: Identifier
    proposal: GameNPCDecisionProposal
    llm_attempts: Annotated[StrictInt, Field(ge=1, le=2)]
    used_fallback: StrictBool
    repair_kind: str | None = None
    usages: tuple[object, ...] = ()


class PendingActionConfirmation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    confirmation_id: Identifier
    decision_id: Identifier
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    action: AgentAction
    authority_mode: AuthorityMode
    public_rationale: NonEmptyText
    case_revision: Annotated[StrictInt, Field(ge=0)]


class CooperativeTurnStatus(str, Enum):
    RESPONDED = "responded"
    ACTION_EXECUTED = "action_executed"
    PROPOSAL_PENDING = "proposal_pending"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ACTION_REJECTED = "action_rejected"


class CooperativeTurnResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: Identifier
    status: CooperativeTurnStatus
    decision: GameNPCDecision
    authority_mode: AuthorityMode | None = None
    pending_action: PendingActionConfirmation | None = None
    environment_message: NonEmptyText | None = None
    event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = ()
    error_code: Identifier | None = None
