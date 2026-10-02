"""Public, non-authoritative CE-2A context projections."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt

from .actions import AgentAction
from .base import DomainModel, Identifier, NonEmptyText
from .cooperation import AuthorityMode


class PendingConfirmationContextView(DomainModel):
    """A read-only view of a currently valid in-process confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmation_id: Identifier
    decision_id: Identifier
    action: AgentAction
    authority_mode: AuthorityMode
    public_rationale: NonEmptyText
    case_revision: Annotated[StrictInt, Field(ge=0)]
    responds_to_current_contribution: bool


class HistoryOmissionView(DomainModel):
    """Exact omission facts for completed turns before the current operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    omitted_completed_turn_count: Annotated[StrictInt, Field(ge=1)]
    reason: Literal["turn_limit", "character_budget"]
    public_notice: NonEmptyText


class CooperativeContextSnapshot(DomainModel):
    """One immutable snapshot reused by the initial request and all repairs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["cooperative_context_v2a_v1"] = "cooperative_context_v2a_v1"
    selected_history_operation_ids: tuple[Identifier, ...] = ()
    history_omission: HistoryOmissionView | None = None
    pending_confirmations: tuple[PendingConfirmationContextView, ...] = ()
