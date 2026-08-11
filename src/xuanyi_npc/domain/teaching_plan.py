"""Replayable long-term R3 teaching plan, separate from growth authority."""

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .apprenticeship import AbilityId
from .base import DomainModel, Identifier
from .curriculum import RecommendationKind


TEACHING_PLAN_SCHEMA_VERSION = "teaching_plan_v1"


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("teaching plan timestamp must include a timezone")


class TeachingPlanModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TeachingRecommendation(TeachingPlanModel):
    kind: RecommendationKind
    recommendation_id: Identifier
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)


class TeachingPlanEventBase(TeachingPlanModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    player_id: Identifier
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "TeachingPlanEventBase":
        _aware(self.occurred_at)
        return self


class TeachingPlanInitialized(TeachingPlanEventBase):
    event_type: Literal["teaching_plan_initialized"] = "teaching_plan_initialized"
    schema_version: Literal["teaching_plan_v1"] = TEACHING_PLAN_SCHEMA_VERSION


class CoreLessonCompleted(TeachingPlanEventBase):
    event_type: Literal["core_lesson_completed"] = "core_lesson_completed"
    lesson_id: Identifier
    assessment_id: Identifier
    source_case_id: Identifier
    source_session_id: Identifier
    source_revision: Annotated[StrictInt, Field(ge=1)]


class RemediationAssigned(TeachingPlanEventBase):
    event_type: Literal["remediation_assigned"] = "remediation_assigned"
    remediation_id: Identifier
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)
    target_ability_ids: tuple[AbilityId, ...] = Field(min_length=1)
    source_assessment_id: Identifier


class RemediationAttempted(TeachingPlanEventBase):
    event_type: Literal["remediation_attempted"] = "remediation_attempted"
    attempt_id: Identifier
    remediation_id: Identifier
    selected_option_id: Identifier
    correct: StrictBool


class RemediationCompleted(TeachingPlanEventBase):
    event_type: Literal["remediation_completed"] = "remediation_completed"
    remediation_id: Identifier
    attempt_id: Identifier
    target_ability_ids: tuple[AbilityId, ...] = Field(min_length=1)


class TeachingRecommendationUpdated(TeachingPlanEventBase):
    event_type: Literal["teaching_recommendation_updated"] = "teaching_recommendation_updated"
    recommendation: TeachingRecommendation
    unresolved_improvement_areas: tuple[AbilityId, ...]
    last_assessment_id: Identifier | None = None
    source_references: tuple[Identifier, ...]


class RecommendationDeviationRecorded(TeachingPlanEventBase):
    event_type: Literal["recommendation_deviation_recorded"] = "recommendation_deviation_recorded"
    case_session_id: Identifier
    chosen_lesson_id: Identifier
    recommended_id: Identifier


TeachingPlanEvent: TypeAlias = Annotated[
    TeachingPlanInitialized
    | CoreLessonCompleted
    | RemediationAssigned
    | RemediationAttempted
    | RemediationCompleted
    | TeachingRecommendationUpdated
    | RecommendationDeviationRecorded,
    Field(discriminator="event_type"),
]


class TeachingPlanState(TeachingPlanModel):
    schema_version: Literal["teaching_plan_v1"] = TEACHING_PLAN_SCHEMA_VERSION
    player_id: Identifier
    current_recommendation: TeachingRecommendation | None = None
    completed_core_lessons: tuple[Identifier, ...] = ()
    completed_remediations: tuple[Identifier, ...] = ()
    unresolved_improvement_areas: tuple[AbilityId, ...] = ()
    recommendation_reason_codes: tuple[Identifier, ...] = ()
    last_assessment_id: Identifier | None = None
    source_references: tuple[Identifier, ...] = ()
    recommendation_deviations: tuple[Identifier, ...] = ()
    events: tuple[TeachingPlanEvent, ...] = Field(min_length=1)
    revision: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_aggregate(self) -> "TeachingPlanState":
        if [item.sequence for item in self.events] != list(range(1, len(self.events) + 1)):
            raise ValueError("teaching plan sequences must be contiguous")
        if self.revision != len(self.events):
            raise ValueError("teaching plan revision must equal event count")
        if not isinstance(self.events[0], TeachingPlanInitialized):
            raise ValueError("teaching plan must begin with initialization")
        if any(item.player_id != self.player_id for item in self.events):
            raise ValueError("teaching plan player mismatch")
        if len(self.completed_core_lessons) != len(set(self.completed_core_lessons)):
            raise ValueError("core lesson completion must be unique")
        if len(self.completed_remediations) != len(set(self.completed_remediations)):
            raise ValueError("remediation completion must be unique")
        _aware(self.created_at)
        _aware(self.updated_at)
        return self


class TeachingPlanReplayError(ValueError):
    pass


class TeachingPlanEventReplayer:
    def replay(self, events: tuple[TeachingPlanEvent, ...]) -> TeachingPlanState:
        if not events or not isinstance(events[0], TeachingPlanInitialized):
            raise TeachingPlanReplayError("teaching plan must begin with initialization")
        first = events[0]
        core: list[str] = []
        remediations: list[str] = []
        recommendation = None
        unresolved: tuple[AbilityId, ...] = ()
        reasons: tuple[str, ...] = ()
        last_assessment = None
        sources: tuple[str, ...] = ()
        deviations: list[str] = []
        attempts: set[str] = set()
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected or event.player_id != first.player_id:
                raise TeachingPlanReplayError("invalid teaching plan sequence")
            if expected == 1:
                continue
            if isinstance(event, CoreLessonCompleted):
                if event.lesson_id in core:
                    raise TeachingPlanReplayError("core lesson completed twice")
                core.append(event.lesson_id)
                last_assessment = event.assessment_id
            elif isinstance(event, RemediationAssigned):
                last_assessment = event.source_assessment_id
            elif isinstance(event, RemediationAttempted):
                if event.attempt_id in attempts:
                    raise TeachingPlanReplayError("remediation attempt repeated")
                attempts.add(event.attempt_id)
            elif isinstance(event, RemediationCompleted):
                if event.attempt_id not in attempts or event.remediation_id in remediations:
                    raise TeachingPlanReplayError("invalid remediation completion")
                remediations.append(event.remediation_id)
            elif isinstance(event, TeachingRecommendationUpdated):
                recommendation = event.recommendation
                unresolved = event.unresolved_improvement_areas
                reasons = event.recommendation.reason_codes
                last_assessment = event.last_assessment_id or last_assessment
                sources = event.source_references
            elif isinstance(event, RecommendationDeviationRecorded):
                if event.case_session_id in deviations:
                    raise TeachingPlanReplayError("recommendation deviation repeated")
                deviations.append(event.case_session_id)
            else:
                raise TeachingPlanReplayError("initialization may appear only once")
        return TeachingPlanState(
            player_id=first.player_id,
            current_recommendation=recommendation,
            completed_core_lessons=tuple(core),
            completed_remediations=tuple(remediations),
            unresolved_improvement_areas=unresolved,
            recommendation_reason_codes=reasons,
            last_assessment_id=last_assessment,
            source_references=sources,
            recommendation_deviations=tuple(deviations),
            events=events,
            revision=len(events),
            created_at=first.occurred_at,
            updated_at=events[-1].occurred_at,
        )
