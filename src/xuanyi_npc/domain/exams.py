"""Frozen deterministic R4 examination contracts and replayable attempts."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .apprenticeship import AbilityId
from .base import DomainModel, Identifier, NonEmptyText


class ExamModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ExamSection(str, Enum):
    EVIDENCE_INFERENCE = "evidence_and_inference"
    DIFFERENTIATION = "differentiation_and_decoy_exclusion"
    TREATMENT_ETHICS = "treatment_and_ethics"


class ExamOption(ExamModel):
    option_id: Identifier
    public_text: NonEmptyText


class ExamQuestion(ExamModel):
    question_id: Identifier
    section: ExamSection
    public_scenario: NonEmptyText
    options: tuple[ExamOption, ...] = Field(min_length=2)
    correct_option_ids: tuple[Identifier, ...] = Field(min_length=1)
    explanation: NonEmptyText
    score: Annotated[StrictInt, Field(ge=1, le=100)]
    critical_safety: StrictBool
    targeted_ability_ids: tuple[AbilityId, ...] = Field(min_length=1)
    remediation_id: Identifier

    @model_validator(mode="after")
    def validate_options(self) -> "ExamQuestion":
        option_ids = tuple(item.option_id for item in self.options)
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("exam option ids must be unique")
        if not set(self.correct_option_ids).issubset(option_ids):
            raise ValueError("correct option must identify a public option")
        return self


class ExamDefinition(ExamModel):
    exam_id: Literal["foundational_xuanyi_exam_v1"]
    version: Literal["v1"]
    title: NonEmptyText
    fictional_safety_notice: NonEmptyText
    questions: tuple[ExamQuestion, ...] = Field(min_length=6, max_length=6)
    total_score: Literal[100]
    passing_score: Literal[80]
    require_nonzero_each_section: Literal[True]
    critical_failure_blocks_pass: Literal[True]
    hint_limit: Literal[0]
    recognition_reward: Literal[2]
    source_revision: Literal["r4_contract_v1"]

    @model_validator(mode="after")
    def validate_exam(self) -> "ExamDefinition":
        if sum(item.score for item in self.questions) != self.total_score:
            raise ValueError("exam question scores must total 100")
        if len({item.question_id for item in self.questions}) != 6:
            raise ValueError("exam question ids must be unique")
        counts = {section: 0 for section in ExamSection}
        for item in self.questions:
            counts[item.section] += 1
        if set(counts.values()) != {2}:
            raise ValueError("exam must contain two questions in each section")
        if not any(item.critical_safety for item in self.questions):
            raise ValueError("exam must contain a critical safety question")
        return self


class ExamEligibilityPolicy(ExamModel):
    policy_id: Literal["exam_eligibility_v1"]
    version: Literal["v1"]
    required_core_lessons: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    mandatory_remediation_ids: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    required_positive_evidence_abilities: tuple[AbilityId, ...] = Field(min_length=3)
    unresolved_serious_abilities: tuple[AbilityId, ...] = Field(min_length=2)
    retake_requires_remediation: Literal[True]


class ExamSessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    SUBMITTED = "submitted"
    PASSED = "passed"
    FAILED = "failed"


class ExamResult(ExamModel):
    exam_id: Literal["foundational_xuanyi_exam_v1"]
    attempt_id: Identifier
    player_id: Identifier
    total_score: Annotated[StrictInt, Field(ge=0, le=100)]
    section_scores: dict[ExamSection, Annotated[StrictInt, Field(ge=0, le=100)]]
    critical_failure: StrictBool
    passed: StrictBool
    improvement_areas: tuple[AbilityId, ...]
    required_remediation_ids: tuple[Identifier, ...]
    submitted_at: datetime
    source_revision: Literal["r4_contract_v1"]

    @model_validator(mode="after")
    def validate_result(self) -> "ExamResult":
        if set(self.section_scores) != set(ExamSection):
            raise ValueError("exam result must include each section")
        if self.submitted_at.tzinfo is None or self.submitted_at.utcoffset() is None:
            raise ValueError("submitted_at must include timezone")
        if self.passed and (self.critical_failure or self.total_score < 80):
            raise ValueError("invalid passing result")
        return self


class ExamEventBase(ExamModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    player_id: Identifier
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "ExamEventBase":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("exam event timestamp must include timezone")
        return self


class ExamStarted(ExamEventBase):
    event_type: Literal["exam_started"] = "exam_started"
    exam_session_id: Identifier
    exam_id: Literal["foundational_xuanyi_exam_v1"]
    attempt_id: Identifier
    attempt_number: Annotated[StrictInt, Field(ge=1)]


class ExamAnswerRecorded(ExamEventBase):
    event_type: Literal["exam_answer_recorded"] = "exam_answer_recorded"
    question_id: Identifier
    selected_option_ids: tuple[Identifier, ...] = Field(min_length=1)


class ExamSubmitted(ExamEventBase):
    event_type: Literal["exam_submitted"] = "exam_submitted"
    answer_fingerprint: Identifier


class ExamScored(ExamEventBase):
    event_type: Literal["exam_scored"] = "exam_scored"
    result: ExamResult


class ExamPassed(ExamEventBase):
    event_type: Literal["exam_passed"] = "exam_passed"
    attempt_id: Identifier


class ExamFailed(ExamEventBase):
    event_type: Literal["exam_failed"] = "exam_failed"
    attempt_id: Identifier
    required_remediation_ids: tuple[Identifier, ...] = Field(min_length=1)
    teaching_plan_revision: Annotated[StrictInt, Field(ge=1)]


class ExamRetakeUnlocked(ExamEventBase):
    event_type: Literal["exam_retake_unlocked"] = "exam_retake_unlocked"
    prior_attempt_id: Identifier
    completed_remediation_ids: tuple[Identifier, ...] = Field(min_length=1)


ExamEvent: TypeAlias = Annotated[
    ExamStarted | ExamAnswerRecorded | ExamSubmitted | ExamScored | ExamPassed
    | ExamFailed | ExamRetakeUnlocked,
    Field(discriminator="event_type"),
]


class ExamSessionState(ExamModel):
    schema_version: Literal["exam_session_v1"] = "exam_session_v1"
    exam_session_id: Identifier
    player_id: Identifier
    exam_id: Literal["foundational_xuanyi_exam_v1"]
    attempt_id: Identifier
    attempt_number: Annotated[StrictInt, Field(ge=1)]
    status: ExamSessionStatus
    submitted_answers: dict[Identifier, tuple[Identifier, ...]]
    result: ExamResult | None = None
    events: tuple[ExamEvent, ...] = Field(min_length=1)
    revision: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "ExamSessionState":
        if self.revision != len(self.events):
            raise ValueError("exam revision must equal event count")
        if [item.sequence for item in self.events] != list(range(1, self.revision + 1)):
            raise ValueError("exam event sequences must be contiguous")
        if any(item.player_id != self.player_id for item in self.events):
            raise ValueError("exam event player mismatch")
        return self


class ExamReplayError(ValueError):
    pass


class ExamEventReplayer:
    def replay(self, events: tuple[ExamEvent, ...]) -> ExamSessionState:
        if not events or not isinstance(events[0], ExamStarted):
            raise ExamReplayError("exam must begin with ExamStarted")
        first = events[0]
        answers: dict[str, tuple[str, ...]] = {}
        result = None
        status = ExamSessionStatus.ACTIVE
        completed_at = None
        submitted = False
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected or event.player_id != first.player_id:
                raise ExamReplayError("invalid exam event sequence")
            if expected == 1:
                continue
            if isinstance(event, ExamAnswerRecorded):
                if submitted or event.question_id in answers:
                    raise ExamReplayError("exam answer cannot be changed")
                answers[event.question_id] = event.selected_option_ids
            elif isinstance(event, ExamSubmitted):
                if submitted:
                    raise ExamReplayError("exam submitted twice")
                submitted, status = True, ExamSessionStatus.SUBMITTED
            elif isinstance(event, ExamScored):
                if not submitted or result is not None:
                    raise ExamReplayError("exam score is out of order")
                result = event.result
            elif isinstance(event, ExamPassed):
                if result is None or not result.passed:
                    raise ExamReplayError("passing event conflicts with score")
                status, completed_at = ExamSessionStatus.PASSED, event.occurred_at
            elif isinstance(event, ExamFailed):
                if result is None or result.passed:
                    raise ExamReplayError("failure event conflicts with score")
                status, completed_at = ExamSessionStatus.FAILED, event.occurred_at
            elif isinstance(event, ExamRetakeUnlocked):
                if status is not ExamSessionStatus.FAILED:
                    raise ExamReplayError("only a failed attempt can unlock retake")
            else:
                raise ExamReplayError("exam started may appear only once")
        return ExamSessionState(
            exam_session_id=first.exam_session_id, player_id=first.player_id,
            exam_id=first.exam_id, attempt_id=first.attempt_id,
            attempt_number=first.attempt_number, status=status,
            submitted_answers=answers, result=result, events=events,
            revision=len(events), created_at=first.occurred_at, completed_at=completed_at,
        )
