"""Version-neutral episode result shared by V0, V1, and V2 evaluations."""

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from xuanyi_npc.config import AgentVariant
from xuanyi_npc.domain.actions import AgentAction, AgentActionType
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseSessionState, CaseSessionStatus
from xuanyi_npc.domain.events import CaseEvent
from xuanyi_npc.engine.replay import CaseEventReplayer, EventReplayError
from xuanyi_npc.engine.results import ScoreBreakdown


CurrencyCode = Annotated[
    StrictStr,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    ),
]


class EpisodeStatus(str, Enum):
    COMPLETED = "completed"
    MAX_STEPS_REACHED = "max_steps_reached"
    FAILED = "failed"


class ModelUsage(DomainModel):
    """Measured usage only. Omit the object when no model call was measured."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider_model: NonEmptyText
    input_tokens: Annotated[StrictInt, Field(ge=0)]
    output_tokens: Annotated[StrictInt, Field(ge=0)]
    cache_hit_input_tokens: Annotated[StrictInt, Field(ge=0)]
    cache_miss_input_tokens: Annotated[StrictInt, Field(ge=0)]
    reasoning_tokens: Annotated[StrictInt, Field(ge=0)]
    latency_ms: Annotated[StrictFloat, Field(ge=0)]
    estimated_cost: Annotated[Decimal, Field(ge=0)] | None = None
    cost_currency: CurrencyCode | None = None
    provider_request_id: NonEmptyText | None = None
    system_fingerprint: NonEmptyText | None = None
    measurement_complete: StrictBool = True

    @model_validator(mode="after")
    def validate_usage_consistency(self) -> "ModelUsage":
        if self.cache_hit_input_tokens + self.cache_miss_input_tokens != self.input_tokens:
            raise ValueError(
                "cache hit and miss input tokens must sum to input_tokens"
            )
        if (self.estimated_cost is None) != (self.cost_currency is None):
            raise ValueError(
                "estimated_cost and cost_currency must both be present or absent"
            )
        return self


class EpisodeStep(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: Annotated[StrictInt, Field(ge=1)]
    action: AgentAction
    accepted: StrictBool
    event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(
        default_factory=tuple
    )
    error_code: Identifier | None = None
    llm_attempts: Annotated[StrictInt, Field(ge=1, le=2)] = 1
    used_fallback: StrictBool = False
    provider_usages: tuple[ModelUsage, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_step_outcome(self) -> "EpisodeStep":
        if self.accepted and self.error_code is not None:
            raise ValueError("accepted steps cannot have error_code")
        if not self.accepted and self.error_code is None:
            raise ValueError("rejected steps require error_code")
        if not self.accepted and self.event_sequences:
            raise ValueError("rejected steps cannot emit domain events")
        if self.used_fallback and self.action.action_type is not AgentActionType.RESPOND:
            raise ValueError("fallback steps must use a non-tool respond action")
        if len(set(self.event_sequences)) != len(self.event_sequences):
            raise ValueError("event_sequences cannot contain duplicates")
        if len(self.provider_usages) > self.llm_attempts:
            raise ValueError("step model usages cannot exceed LLM attempts")
        return self


class EpisodeResult(DomainModel):
    """One stable result contract for baseline and later capability variants."""

    episode_id: Identifier
    variant: AgentVariant
    status: EpisodeStatus
    max_steps: Annotated[StrictInt, Field(ge=1, le=100)]
    initial_session: CaseSessionState
    final_session: CaseSessionState
    steps: tuple[EpisodeStep, ...] = Field(default_factory=tuple)
    events: tuple[CaseEvent, ...] = Field(default_factory=tuple)
    score_breakdown: ScoreBreakdown | None = None
    failure_code: Identifier | None = None
    usage: ModelUsage | None = None

    @model_validator(mode="after")
    def validate_episode_consistency(self) -> "EpisodeResult":
        if len(self.steps) > self.max_steps:
            raise ValueError("episode steps exceed max_steps")
        if [step.step_index for step in self.steps] != list(
            range(1, len(self.steps) + 1)
        ):
            raise ValueError("episode step indexes must be contiguous and start at 1")
        if len({step.action.action_id for step in self.steps}) != len(self.steps):
            raise ValueError("Agent action_id values must be unique within an episode")

        session_identity = (
            self.initial_session.session_id,
            self.initial_session.case_id,
            self.initial_session.player_id,
        )
        final_identity = (
            self.final_session.session_id,
            self.final_session.case_id,
            self.final_session.player_id,
        )
        if session_identity != final_identity:
            raise ValueError("initial and final session identities must match")

        event_sequences = [event.sequence for event in self.events]
        expected_sequences = list(
            range(
                len(self.initial_session.action_history) + 1,
                len(self.initial_session.action_history) + len(self.events) + 1,
            )
        )
        if event_sequences != expected_sequences:
            raise ValueError("episode event sequences must be contiguous")
        if any(
            event.session_id != self.initial_session.session_id for event in self.events
        ):
            raise ValueError("episode events must belong to the episode session")
        referenced_sequences = [
            sequence for step in self.steps for sequence in step.event_sequences
        ]
        if referenced_sequences != event_sequences:
            raise ValueError("episode steps must reference every event exactly once and in order")
        if self.final_session.revision != (
            self.initial_session.revision + len(self.events)
        ):
            raise ValueError("final session revision must match emitted event count")
        try:
            replayed_session = CaseEventReplayer().replay(
                self.initial_session,
                self.events,
            )
        except EventReplayError as exc:
            raise ValueError("episode events cannot be replayed") from exc
        if replayed_session != self.final_session:
            raise ValueError("final_session must equal the event-replayed state")

        if self.status is EpisodeStatus.COMPLETED:
            if self.final_session.status is not CaseSessionStatus.COMPLETED:
                raise ValueError("completed episodes require a completed final session")
            if self.score_breakdown is None:
                raise ValueError("completed episodes require score_breakdown")
            if self.failure_code is not None:
                raise ValueError("completed episodes cannot have failure_code")
            if self.score_breakdown.total != self.final_session.score:
                raise ValueError("score_breakdown must match final session score")
        elif self.status is EpisodeStatus.MAX_STEPS_REACHED:
            if len(self.steps) != self.max_steps:
                raise ValueError("max_steps_reached requires exactly max_steps steps")
            if self.final_session.status is CaseSessionStatus.COMPLETED:
                raise ValueError("a completed session is not a max-step termination")
            if self.score_breakdown is not None:
                raise ValueError("max-step termination cannot have a final score")
        elif self.status is EpisodeStatus.FAILED:
            if self.failure_code is None:
                raise ValueError("failed episodes require failure_code")
            if self.score_breakdown is not None:
                raise ValueError("failed episodes cannot have a final score")
        return self
