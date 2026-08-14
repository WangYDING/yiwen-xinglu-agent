"""Replayable cross-Episode apprenticeship growth aggregate."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .player import TeachingStage
from .relationship import RelationshipState


APPRENTICESHIP_SCHEMA_VERSION = "apprenticeship_state_v2"
PROGRESSION_POLICY_VERSION = "apprenticeship_progression_v2"


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")


class ApprenticeshipModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AbilityId(str, Enum):
    OBSERVE_FORM = "observe_form"
    ASK_CAUSE = "ask_cause"
    INSPECT_EVIDENCE = "inspect_evidence"
    OBSERVE_QI = "observe_qi"
    REASON_DIAGNOSIS = "reason_diagnosis"
    APPLY_TREATMENT = "apply_treatment"
    ETHICAL_PRACTICE = "ethical_practice"


class AbilityLevel(str, Enum):
    UNLEARNED = "unlearned"
    INTRODUCED = "introduced"
    NOVICE = "novice"
    # Kept only to deserialize v1 event streams during migration.
    APPRENTICE = "apprentice"
    COMPETENT = "competent"
    ADVANCED = "advanced"
    EXPERT = "expert"
    MASTERED = "mastered"


class EvidencePolarity(str, Enum):
    DEMONSTRATED = "demonstrated"
    NEEDS_IMPROVEMENT = "needs_improvement"


class RelationshipDimension(str, Enum):
    AFFINITY = "affinity"
    TRUST = "trust"
    RECOGNITION = "recognition"


class AbilityState(ApprenticeshipModel):
    ability_id: AbilityId
    proficiency: Annotated[StrictInt, Field(ge=0, le=100)]
    level: AbilityLevel
    evidence_count: Annotated[StrictInt, Field(ge=0)] = 0
    latest_evidence_at: datetime | None = None
    unlocked: StrictBool = True

    @model_validator(mode="after")
    def validate_timestamp(self) -> "AbilityState":
        if self.latest_evidence_at is not None:
            _aware(self.latest_evidence_at, "latest_evidence_at")
        return self


class AbilityEvidence(ApprenticeshipModel):
    evidence_id: Identifier
    player_id: Identifier
    ability_id: AbilityId
    polarity: EvidencePolarity
    strength: Annotated[StrictInt, Field(ge=1, le=5)]
    public_reason_code: Identifier
    public_description: NonEmptyText
    source_case_id: Identifier
    source_session_id: Identifier
    source_event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(
        min_length=1
    )
    source_revision: Annotated[StrictInt, Field(ge=1)]
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_source(self) -> "AbilityEvidence":
        if tuple(sorted(set(self.source_event_sequences))) != self.source_event_sequences:
            raise ValueError("evidence source sequences must be unique and ordered")
        if self.source_event_sequences[-1] > self.source_revision:
            raise ValueError("evidence source sequence exceeds source revision")
        _aware(self.occurred_at, "occurred_at")
        return self


class ApprenticeshipEventBase(ApprenticeshipModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    player_id: Identifier
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "ApprenticeshipEventBase":
        _aware(self.occurred_at, "occurred_at")
        return self


class ApprenticeshipInitialized(ApprenticeshipEventBase):
    event_type: Literal["apprenticeship_initialized"] = "apprenticeship_initialized"
    schema_version: Literal["apprenticeship_state_v1","apprenticeship_state_v2"] = APPRENTICESHIP_SCHEMA_VERSION
    progression_version: Literal["apprenticeship_progression_v1","apprenticeship_progression_v2"] = (
        PROGRESSION_POLICY_VERSION
    )
    teaching_stage: TeachingStage
    initial_abilities: tuple[AbilityState, ...]
    initial_relationship: RelationshipState

    @model_validator(mode="after")
    def validate_initial_abilities(self) -> "ApprenticeshipInitialized":
        if (
            len(self.initial_abilities) != len(AbilityId)
            or {item.ability_id for item in self.initial_abilities} != set(AbilityId)
        ):
            raise ValueError("initialization must define each ability exactly once")
        return self


class AbilityEvidenceRecorded(ApprenticeshipEventBase):
    event_type: Literal["ability_evidence_recorded"] = "ability_evidence_recorded"
    evidence: AbilityEvidence

    @model_validator(mode="after")
    def validate_evidence_owner(self) -> "AbilityEvidenceRecorded":
        if self.evidence.player_id != self.player_id:
            raise ValueError("evidence player does not match event player")
        if self.evidence.occurred_at != self.occurred_at:
            raise ValueError("evidence time does not match event time")
        return self


class AbilityProgressed(ApprenticeshipEventBase):
    event_type: Literal["ability_progressed"] = "ability_progressed"
    ability_id: AbilityId
    delta: Annotated[StrictInt, Field(ge=1, le=10)]
    proficiency_before: Annotated[StrictInt, Field(ge=0, le=100)]
    proficiency_after: Annotated[StrictInt, Field(ge=0, le=100)]
    level_before: AbilityLevel
    level_after: AbilityLevel
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    public_reason_code: Identifier
    public_description: NonEmptyText

    @model_validator(mode="after")
    def validate_delta(self) -> "AbilityProgressed":
        if self.proficiency_after - self.proficiency_before != self.delta:
            raise ValueError("ability progression values do not match delta")
        return self


class AbilityUnlocked(ApprenticeshipEventBase):
    event_type: Literal["ability_unlocked"] = "ability_unlocked"
    ability_id: AbilityId
    source_exercise_id: Identifier
    public_description: NonEmptyText


class AbilityFoundationGranted(ApprenticeshipEventBase):
    event_type: Literal["ability_foundation_granted"] = "ability_foundation_granted"
    ability_id: AbilityId
    proficiency_before: Annotated[StrictInt, Field(ge=0, le=100)]
    proficiency_after: Annotated[StrictInt, Field(ge=1, le=100)]
    source_exercise_id: Identifier
    source_event_id: Identifier
    public_description: NonEmptyText

    @model_validator(mode="after")
    def validate_foundation(self) -> "AbilityFoundationGranted":
        if self.proficiency_after <= self.proficiency_before:
            raise ValueError("foundation grant must increase proficiency")
        return self


class AbilitySchemaMigrated(ApprenticeshipEventBase):
    event_type: Literal["ability_schema_migrated"] = "ability_schema_migrated"
    from_schema_version: NonEmptyText
    added_ability_id: AbilityId
    migrated_proficiency: Annotated[StrictInt, Field(ge=0,le=100)]=0
    migrated_unlocked: StrictBool=False
    trusted_source_event_ids: tuple[Identifier,...]=()
    public_description: NonEmptyText


class RelationshipChanged(ApprenticeshipEventBase):
    event_type: Literal["relationship_changed"] = "relationship_changed"
    dimension: RelationshipDimension
    delta: Annotated[StrictInt, Field(ge=-2, le=2)]
    value_before: Annotated[StrictInt, Field(ge=0, le=100)]
    value_after: Annotated[StrictInt, Field(ge=0, le=100)]
    public_reason_code: Identifier
    public_description: NonEmptyText
    source_case_id: Identifier
    source_session_id: Identifier
    source_event_sequence: Annotated[StrictInt, Field(ge=1)]

    @model_validator(mode="after")
    def validate_delta(self) -> "RelationshipChanged":
        if self.delta == 0 or self.value_after - self.value_before != self.delta:
            raise ValueError("relationship change values do not match delta")
        return self


class EpisodeGrowthApplied(ApprenticeshipEventBase):
    event_type: Literal["episode_growth_applied"] = "episode_growth_applied"
    source_case_id: Identifier
    source_session_id: Identifier
    source_revision: Annotated[StrictInt, Field(ge=1)]
    source_event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(
        min_length=1
    )
    source_fingerprint: Identifier
    evidence_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    ability_change_count: Annotated[StrictInt, Field(ge=0)]
    relationship_change_count: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def validate_receipt(self) -> "EpisodeGrowthApplied":
        if self.source_event_sequences != tuple(range(1, self.source_revision + 1)):
            raise ValueError("episode source sequences must cover the full revision")
        return self


ApprenticeshipEvent: TypeAlias = Annotated[
    ApprenticeshipInitialized
    | AbilityEvidenceRecorded
    | AbilityProgressed
    | AbilityUnlocked
    | AbilityFoundationGranted
    | AbilitySchemaMigrated
    | RelationshipChanged
    | EpisodeGrowthApplied,
    Field(discriminator="event_type"),
]


class ApprenticeshipState(ApprenticeshipModel):
    schema_version: Literal["apprenticeship_state_v1","apprenticeship_state_v2"] = APPRENTICESHIP_SCHEMA_VERSION
    progression_version: Literal["apprenticeship_progression_v1","apprenticeship_progression_v2"] = (
        PROGRESSION_POLICY_VERSION
    )
    player_id: Identifier
    teaching_stage: TeachingStage
    abilities: dict[AbilityId, AbilityState]
    relationship: RelationshipState
    evidence_history: tuple[AbilityEvidence, ...] = Field(default_factory=tuple)
    completed_source_sessions: tuple[Identifier, ...] = Field(default_factory=tuple)
    events: tuple[ApprenticeshipEvent, ...] = Field(min_length=1)
    revision: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_aggregate(self) -> "ApprenticeshipState":
        expected_abilities = set(AbilityId)
        if set(self.abilities) != expected_abilities:
            raise ValueError("apprenticeship must contain exactly seven abilities")
        for key, ability in self.abilities.items():
            if key != ability.ability_id:
                raise ValueError("ability map key does not match ability_id")
        if [event.sequence for event in self.events] != list(
            range(1, len(self.events) + 1)
        ):
            raise ValueError("apprenticeship event sequences must be contiguous")
        if self.revision != len(self.events):
            raise ValueError("apprenticeship revision must equal event count")
        if not isinstance(self.events[0], ApprenticeshipInitialized):
            raise ValueError("first apprenticeship event must initialize the aggregate")
        if any(event.player_id != self.player_id for event in self.events):
            raise ValueError("apprenticeship event player mismatch")
        derived_evidence = tuple(
            event.evidence
            for event in self.events
            if isinstance(event, AbilityEvidenceRecorded)
        )
        if self.evidence_history != derived_evidence:
            raise ValueError("evidence history must be derived from events")
        derived_sessions = tuple(
            event.source_session_id
            for event in self.events
            if isinstance(event, EpisodeGrowthApplied)
        )
        if len(derived_sessions) != len(set(derived_sessions)):
            raise ValueError("source session may be applied only once")
        if self.completed_source_sessions != derived_sessions:
            raise ValueError("completed source sessions must be derived from events")
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.created_at != self.events[0].occurred_at:
            raise ValueError("created_at must match initialization event")
        if self.updated_at != self.events[-1].occurred_at:
            raise ValueError("updated_at must match latest event")
        return self


class ApprenticeshipReplayError(ValueError):
    """Raised when an event stream cannot reproduce its stored state."""


class ApprenticeshipEventReplayer:
    def replay(self, events: tuple[ApprenticeshipEvent, ...]) -> ApprenticeshipState:
        if not events or not isinstance(events[0], ApprenticeshipInitialized):
            raise ApprenticeshipReplayError("event stream must begin with initialization")
        first = events[0]
        abilities = {item.ability_id: item for item in first.initial_abilities}
        relationship = first.initial_relationship
        evidence: list[AbilityEvidence] = []
        sessions: list[str] = []
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected or event.player_id != first.player_id:
                raise ApprenticeshipReplayError("invalid apprenticeship event sequence")
            if expected == 1:
                continue
            if isinstance(event, AbilityEvidenceRecorded):
                evidence.append(event.evidence)
                ability = abilities[event.evidence.ability_id]
                abilities[event.evidence.ability_id] = ability.model_copy(
                    update={
                        "evidence_count": ability.evidence_count + 1,
                        "latest_evidence_at": event.occurred_at,
                    }
                )
            elif isinstance(event, AbilityProgressed):
                ability = abilities[event.ability_id]
                if (
                    ability.proficiency != event.proficiency_before
                    or ability.level != event.level_before
                ):
                    raise ApprenticeshipReplayError("ability progression source mismatch")
                abilities[event.ability_id] = ability.model_copy(
                    update={
                        "proficiency": event.proficiency_after,
                        "level": event.level_after,
                    }
                )
            elif isinstance(event, AbilityUnlocked):
                ability = abilities[event.ability_id]
                if ability.unlocked:
                    raise ApprenticeshipReplayError("ability may only be unlocked once")
                abilities[event.ability_id] = ability.model_copy(update={"unlocked": True})
            elif isinstance(event, AbilityFoundationGranted):
                ability = abilities[event.ability_id]
                if not ability.unlocked or ability.proficiency != event.proficiency_before:
                    raise ApprenticeshipReplayError("ability foundation source mismatch")
                abilities[event.ability_id] = ability.model_copy(update={
                    "proficiency": event.proficiency_after,
                    "level": AbilityLevel.NOVICE,
                })
            elif isinstance(event, AbilitySchemaMigrated):
                if event.added_ability_id not in abilities:
                    raise ApprenticeshipReplayError("migration ability is missing from initialized schema")
                ability=abilities[event.added_ability_id]
                abilities[event.added_ability_id]=ability.model_copy(update={"proficiency":event.migrated_proficiency,"unlocked":event.migrated_unlocked,"level":(AbilityLevel.NOVICE if event.migrated_proficiency>=10 else AbilityLevel.INTRODUCED if event.migrated_proficiency else AbilityLevel.UNLEARNED)})
            elif isinstance(event, RelationshipChanged):
                current = getattr(relationship, event.dimension.value)
                if current != event.value_before:
                    raise ApprenticeshipReplayError("relationship change source mismatch")
                relationship = relationship.model_copy(
                    update={event.dimension.value: event.value_after}
                )
            elif isinstance(event, EpisodeGrowthApplied):
                if event.source_session_id in sessions:
                    raise ApprenticeshipReplayError("source session applied twice")
                sessions.append(event.source_session_id)
            else:
                raise ApprenticeshipReplayError("initialization event may appear only once")
        try:
            return ApprenticeshipState(
                schema_version=first.schema_version,
                progression_version=first.progression_version,
                player_id=first.player_id,
                teaching_stage=first.teaching_stage,
                abilities=abilities,
                relationship=relationship,
                evidence_history=tuple(evidence),
                completed_source_sessions=tuple(sessions),
                events=events,
                revision=len(events),
                created_at=first.occurred_at,
                updated_at=events[-1].occurred_at,
            )
        except ValueError as exc:
            raise ApprenticeshipReplayError("replayed apprenticeship state is invalid") from exc
