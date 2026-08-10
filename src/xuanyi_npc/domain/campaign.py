"""Deterministic, replayable cross-Episode campaign contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .cases import TreatmentOutcome


CAMPAIGN_PROJECTION_VERSION = "campaign_projection_v1"


class CampaignModel(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


class CampaignFactType(str, Enum):
    PUBLIC_CASE_RESOLUTION = "public_case_resolution"


class CompletedCaseSummary(CampaignModel):
    case_id: Identifier
    session_id: Identifier
    outcome: TreatmentOutcome
    score: Annotated[StrictInt, Field(ge=0, le=100)]
    submitted_diagnosis_id: Identifier
    selected_treatment_id: Identifier
    discovered_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    source_revision: Annotated[StrictInt, Field(ge=1)]
    source_event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(
        min_length=1
    )
    completed_at: datetime

    @model_validator(mode="after")
    def validate_source_receipt(self) -> "CompletedCaseSummary":
        expected = tuple(range(1, self.source_revision + 1))
        if self.source_event_sequences != expected:
            raise ValueError("source event sequences must be contiguous through revision")
        _require_aware(self.completed_at, "completed_at")
        return self


class CampaignFact(CampaignModel):
    fact_id: Identifier
    fact_type: CampaignFactType
    player_id: Identifier
    source_case_id: Identifier
    source_session_id: Identifier
    source_event_sequence: Annotated[StrictInt, Field(ge=1)]
    public_text: NonEmptyText
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "CampaignFact":
        _require_aware(self.occurred_at, "occurred_at")
        return self


class KnowledgeUnlock(CampaignModel):
    knowledge_id: Identifier
    player_id: Identifier
    source_case_id: Identifier
    source_session_id: Identifier
    source_event_sequence: Annotated[StrictInt, Field(ge=1)]
    public_description: NonEmptyText
    unlocked_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "KnowledgeUnlock":
        _require_aware(self.unlocked_at, "unlocked_at")
        return self


class CrossEpisodeEffect(CampaignModel):
    fact_id: Identifier
    fact_type: CampaignFactType
    fact_public_text: NonEmptyText
    knowledge_id: Identifier
    knowledge_public_description: NonEmptyText
    target_case_id: Identifier
    history_reaction: NonEmptyText
    recommended_investigation_id: Identifier
    recommendation_reason: NonEmptyText


class CrossEpisodeRule(CampaignModel):
    rule_id: Identifier
    source_case_id: Identifier
    source_treatment_id: Identifier
    source_outcome: TreatmentOutcome
    effect: CrossEpisodeEffect


class RecommendedCaseRule(CampaignModel):
    case_id: Identifier
    public_reason: NonEmptyText


class TargetCaseContext(CampaignModel):
    case_id: Identifier
    neutral_reaction: NonEmptyText


class CrossEpisodeRulesConfig(CampaignModel):
    rules_version: Literal["cross_episode_rules_v1"] = "cross_episode_rules_v1"
    projection_version: Literal["campaign_projection_v1"] = (
        CAMPAIGN_PROJECTION_VERSION
    )
    recommended_case_order: tuple[RecommendedCaseRule, ...] = Field(min_length=1)
    target_case_contexts: tuple[TargetCaseContext, ...] = Field(default_factory=tuple)
    rules: tuple[CrossEpisodeRule, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_config_ids(self) -> "CrossEpisodeRulesConfig":
        def require_unique(values: list[str], label: str) -> None:
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label}")

        require_unique(
            [entry.case_id for entry in self.recommended_case_order],
            "recommended case_id",
        )
        require_unique(
            [entry.case_id for entry in self.target_case_contexts],
            "target case context",
        )
        require_unique([rule.rule_id for rule in self.rules], "rule_id")
        require_unique(
            [rule.effect.fact_id for rule in self.rules],
            "fact_id",
        )
        require_unique(
            [rule.effect.knowledge_id for rule in self.rules],
            "knowledge_id",
        )
        return self


class CampaignEvent(CampaignModel):
    event_type: Literal["case_completion_projected"] = "case_completion_projected"
    sequence: Annotated[StrictInt, Field(ge=1)]
    player_id: Identifier
    projection_version: Literal["campaign_projection_v1"] = (
        CAMPAIGN_PROJECTION_VERSION
    )
    completed_case: CompletedCaseSummary
    new_facts: tuple[CampaignFact, ...] = Field(default_factory=tuple)
    new_knowledge: tuple[KnowledgeUnlock, ...] = Field(default_factory=tuple)
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_event_sources(self) -> "CampaignEvent":
        _require_aware(self.occurred_at, "occurred_at")
        summary = self.completed_case
        if self.occurred_at != summary.completed_at:
            raise ValueError("campaign event time must match completed case time")
        for fact in self.new_facts:
            if (
                fact.player_id != self.player_id
                or fact.source_case_id != summary.case_id
                or fact.source_session_id != summary.session_id
                or fact.source_event_sequence != summary.source_revision
                or fact.occurred_at != summary.completed_at
            ):
                raise ValueError("campaign fact source does not match event receipt")
        for knowledge in self.new_knowledge:
            if (
                knowledge.player_id != self.player_id
                or knowledge.source_case_id != summary.case_id
                or knowledge.source_session_id != summary.session_id
                or knowledge.source_event_sequence != summary.source_revision
                or knowledge.unlocked_at != summary.completed_at
            ):
                raise ValueError("knowledge source does not match event receipt")
        return self


class CampaignState(CampaignModel):
    player_id: Identifier
    projection_version: Literal["campaign_projection_v1"] = (
        CAMPAIGN_PROJECTION_VERSION
    )
    revision: Annotated[StrictInt, Field(ge=0)] = 0
    event_history: tuple[CampaignEvent, ...] = Field(default_factory=tuple)
    completed_cases: tuple[CompletedCaseSummary, ...] = Field(default_factory=tuple)
    active_facts: tuple[CampaignFact, ...] = Field(default_factory=tuple)
    unlocked_knowledge_ids: frozenset[Identifier] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_replayable_state(self) -> "CampaignState":
        expected_sequences = list(range(1, len(self.event_history) + 1))
        if [event.sequence for event in self.event_history] != expected_sequences:
            raise ValueError("campaign event sequences must be contiguous and start at 1")
        if self.revision != len(self.event_history):
            raise ValueError("campaign revision must equal event count")
        if any(event.player_id != self.player_id for event in self.event_history):
            raise ValueError("campaign event player does not match state")
        if any(
            event.projection_version != self.projection_version
            for event in self.event_history
        ):
            raise ValueError("campaign event projection version does not match state")

        expected_cases = tuple(event.completed_case for event in self.event_history)
        expected_facts = tuple(
            fact for event in self.event_history for fact in event.new_facts
        )
        expected_knowledge = frozenset(
            knowledge.knowledge_id
            for event in self.event_history
            for knowledge in event.new_knowledge
        )
        if self.completed_cases != expected_cases:
            raise ValueError("completed cases must be derived exactly from events")
        if self.active_facts != expected_facts:
            raise ValueError("active facts must be derived exactly from events")
        if self.unlocked_knowledge_ids != expected_knowledge:
            raise ValueError("knowledge IDs must be derived exactly from events")

        case_ids = [summary.case_id for summary in self.completed_cases]
        session_ids = [summary.session_id for summary in self.completed_cases]
        fact_ids = [fact.fact_id for fact in self.active_facts]
        knowledge_ids = [
            knowledge.knowledge_id
            for event in self.event_history
            for knowledge in event.new_knowledge
        ]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("a campaign cannot complete one case more than once")
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("a source session cannot be projected more than once")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("active campaign fact IDs must be unique")
        if len(knowledge_ids) != len(set(knowledge_ids)):
            raise ValueError("knowledge cannot be unlocked more than once")
        return self


class CampaignReplayError(ValueError):
    """Raised when a Campaign event stream cannot rebuild a valid state."""


class CampaignEventReplayer:
    def replay(
        self,
        initial: CampaignState,
        events: tuple[CampaignEvent, ...] | list[CampaignEvent],
    ) -> CampaignState:
        if initial.event_history or initial.revision != 0:
            raise CampaignReplayError("campaign replay requires an empty initial state")
        current = initial
        for event in events:
            if event.sequence != current.revision + 1:
                raise CampaignReplayError("campaign event sequence is not contiguous")
            if event.player_id != current.player_id:
                raise CampaignReplayError("campaign event player does not match initial state")
            try:
                current = CampaignState(
                    player_id=current.player_id,
                    projection_version=current.projection_version,
                    revision=current.revision + 1,
                    event_history=(*current.event_history, event),
                    completed_cases=(*current.completed_cases, event.completed_case),
                    active_facts=(*current.active_facts, *event.new_facts),
                    unlocked_knowledge_ids=(
                        current.unlocked_knowledge_ids
                        | {
                            knowledge.knowledge_id
                            for knowledge in event.new_knowledge
                        }
                    ),
                )
            except ValueError as exc:
                raise CampaignReplayError(
                    "campaign event stream produced invalid state"
                ) from exc
        return current
