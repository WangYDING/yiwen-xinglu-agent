"""Independent replayable R2 teaching-session aggregate."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .assessment import AssessmentReport
from .base import DomainModel, Identifier, NonEmptyText
from .mentor import MentorAction


TEACHING_SCHEMA_VERSION = "teaching_session_v1"


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("teaching timestamp must include a timezone")


class TeachingModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TeachingPhase(str, Enum):
    ASSIGNED = "assigned"
    ACTIVE = "active"
    CASE_COMPLETED = "case_completed"
    REVIEWED = "reviewed"
    COMPLETED = "completed"


class ReflectionStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    SUBMITTED = "submitted"


class ReviewStatus(str, Enum):
    NOT_READY = "not_ready"
    ASSESSMENT_READY = "assessment_ready"
    REVIEWED = "reviewed"


class TeachingEventBase(TeachingModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    teaching_session_id: Identifier
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "TeachingEventBase":
        _aware(self.occurred_at)
        return self


class LessonAssigned(TeachingEventBase):
    event_type: Literal["lesson_assigned"] = "lesson_assigned"
    schema_version: Literal["teaching_session_v1"] = TEACHING_SCHEMA_VERSION
    player_id: Identifier
    mentor_id: Identifier
    lesson_id: Identifier
    case_session_id: Identifier


class MentorBriefingIssued(TeachingEventBase):
    event_type: Literal["mentor_briefing_issued"] = "mentor_briefing_issued"
    action: MentorAction


class ReflectionRequested(TeachingEventBase):
    event_type: Literal["reflection_requested"] = "reflection_requested"
    action: MentorAction


class PlayerReflectionSubmitted(TeachingEventBase):
    event_type: Literal["player_reflection_submitted"] = "player_reflection_submitted"
    display_text: NonEmptyText


class HintDelivered(TeachingEventBase):
    event_type: Literal["hint_delivered"] = "hint_delivered"
    hint_id: Identifier
    action: MentorAction


class CaseCompletionObserved(TeachingEventBase):
    event_type: Literal["case_completion_observed"] = "case_completion_observed"
    case_revision: Annotated[StrictInt, Field(ge=1)]


class AssessmentAttached(TeachingEventBase):
    event_type: Literal["assessment_attached"] = "assessment_attached"
    assessment: AssessmentReport


class MentorReviewIssued(TeachingEventBase):
    event_type: Literal["mentor_review_issued"] = "mentor_review_issued"
    action: MentorAction
    fixed_next_step_action: MentorAction
    used_fallback: bool = False


class TeachingSessionCompleted(TeachingEventBase):
    event_type: Literal["teaching_session_completed"] = "teaching_session_completed"


TeachingEvent: TypeAlias = Annotated[
    LessonAssigned
    | MentorBriefingIssued
    | ReflectionRequested
    | PlayerReflectionSubmitted
    | HintDelivered
    | CaseCompletionObserved
    | AssessmentAttached
    | MentorReviewIssued
    | TeachingSessionCompleted,
    Field(discriminator="event_type"),
]


class TeachingSessionState(TeachingModel):
    schema_version: Literal["teaching_session_v1"] = TEACHING_SCHEMA_VERSION
    teaching_session_id: Identifier
    player_id: Identifier
    mentor_id: Identifier
    lesson_id: Identifier
    case_session_id: Identifier
    phase: TeachingPhase
    used_hint_ids: tuple[Identifier, ...] = ()
    reflection_status: ReflectionStatus = ReflectionStatus.NOT_REQUESTED
    review_status: ReviewStatus = ReviewStatus.NOT_READY
    assessment: AssessmentReport | None = None
    mentor_review: MentorAction | None = None
    events: tuple[TeachingEvent, ...] = Field(min_length=1)
    revision: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_aggregate(self) -> "TeachingSessionState":
        if [event.sequence for event in self.events] != list(range(1, len(self.events) + 1)):
            raise ValueError("teaching event sequences must be contiguous")
        if self.revision != len(self.events):
            raise ValueError("teaching revision must equal event count")
        if not isinstance(self.events[0], LessonAssigned):
            raise ValueError("teaching stream must begin with lesson assignment")
        if any(event.teaching_session_id != self.teaching_session_id for event in self.events):
            raise ValueError("teaching event session mismatch")
        if len(self.used_hint_ids) != len(set(self.used_hint_ids)):
            raise ValueError("a hint may be delivered only once")
        _aware(self.created_at)
        _aware(self.updated_at)
        return self


class TeachingReplayError(ValueError):
    pass


class TeachingEventReplayer:
    def replay(self, events: tuple[TeachingEvent, ...]) -> TeachingSessionState:
        if not events or not isinstance(events[0], LessonAssigned):
            raise TeachingReplayError("teaching stream must begin with assignment")
        first = events[0]
        phase = TeachingPhase.ASSIGNED
        hints: list[str] = []
        reflection = ReflectionStatus.NOT_REQUESTED
        review = ReviewStatus.NOT_READY
        assessment = None
        mentor_review = None
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected or event.teaching_session_id != first.teaching_session_id:
                raise TeachingReplayError("invalid teaching event sequence")
            if expected == 1:
                continue
            if isinstance(event, MentorBriefingIssued):
                if phase is not TeachingPhase.ASSIGNED:
                    raise TeachingReplayError("briefing is out of order")
                phase = TeachingPhase.ACTIVE
            elif isinstance(event, ReflectionRequested):
                if phase is not TeachingPhase.ACTIVE or reflection is not ReflectionStatus.NOT_REQUESTED:
                    raise TeachingReplayError("reflection request is out of order")
                reflection = ReflectionStatus.REQUESTED
            elif isinstance(event, PlayerReflectionSubmitted):
                if reflection is not ReflectionStatus.REQUESTED:
                    raise TeachingReplayError("reflection was not requested")
                reflection = ReflectionStatus.SUBMITTED
            elif isinstance(event, HintDelivered):
                if phase is not TeachingPhase.ACTIVE or event.hint_id in hints:
                    raise TeachingReplayError("hint event is invalid")
                hints.append(event.hint_id)
            elif isinstance(event, CaseCompletionObserved):
                if phase is not TeachingPhase.ACTIVE:
                    raise TeachingReplayError("case completion is out of order")
                phase = TeachingPhase.CASE_COMPLETED
            elif isinstance(event, AssessmentAttached):
                if phase is not TeachingPhase.CASE_COMPLETED or assessment is not None:
                    raise TeachingReplayError("assessment is out of order")
                assessment = event.assessment
                review = ReviewStatus.ASSESSMENT_READY
            elif isinstance(event, MentorReviewIssued):
                if assessment is None or mentor_review is not None:
                    raise TeachingReplayError("mentor review is out of order")
                mentor_review = event.action
                review = ReviewStatus.REVIEWED
                phase = TeachingPhase.REVIEWED
            elif isinstance(event, TeachingSessionCompleted):
                if phase is not TeachingPhase.REVIEWED:
                    raise TeachingReplayError("teaching completion is out of order")
                phase = TeachingPhase.COMPLETED
            else:
                raise TeachingReplayError("assignment may appear only once")
        try:
            return TeachingSessionState(
                teaching_session_id=first.teaching_session_id,
                player_id=first.player_id,
                mentor_id=first.mentor_id,
                lesson_id=first.lesson_id,
                case_session_id=first.case_session_id,
                phase=phase,
                used_hint_ids=tuple(hints),
                reflection_status=reflection,
                review_status=review,
                assessment=assessment,
                mentor_review=mentor_review,
                events=events,
                revision=len(events),
                created_at=first.occurred_at,
                updated_at=events[-1].occurred_at,
            )
        except ValueError as exc:
            raise TeachingReplayError("replayed teaching state is invalid") from exc
