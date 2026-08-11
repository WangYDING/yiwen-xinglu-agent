"""Frozen R4 teaching-stage policy and replayable permission authority."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText


class PermissionModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class R4TeachingStage(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    APPRENTICE = "APPRENTICE"
    EXAM_CANDIDATE = "EXAM_CANDIDATE"
    INNER_DISCIPLE = "INNER_DISCIPLE"


class PermissionLevel(str, Enum):
    PUBLIC = "PUBLIC"
    APPRENTICE = "APPRENTICE"
    INNER_DISCIPLE = "INNER_DISCIPLE"
    CORE_TEACHING = "CORE_TEACHING"
    INHERITANCE = "INHERITANCE"
    MENTOR_SECRET = "MENTOR_SECRET"


class PermissionRule(PermissionModel):
    permission: PermissionLevel
    public_description: NonEmptyText
    grant_condition_code: Identifier


class PermissionPolicy(PermissionModel):
    policy_id: Literal["permission_policy_v1"]
    version: Literal["v1"]
    default_permissions: tuple[PermissionLevel, ...] = (PermissionLevel.PUBLIC,)
    rules: tuple[PermissionRule, ...] = Field(min_length=6, max_length=6)
    allowed_stage_transitions: dict[R4TeachingStage, tuple[R4TeachingStage, ...]]
    mentor_secret_grantable: Literal[False]
    denial_error_code: Literal["knowledge_access_denied"]

    @model_validator(mode="after")
    def validate_policy(self) -> "PermissionPolicy":
        if {item.permission for item in self.rules} != set(PermissionLevel):
            raise ValueError("permission policy must define every level once")
        if set(self.allowed_stage_transitions) != set(R4TeachingStage):
            raise ValueError("permission policy must define every stage transition")
        return self


class PermissionEventBase(PermissionModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    player_id: Identifier
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "PermissionEventBase":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("permission event timestamp must include timezone")
        return self


class PermissionStateInitialized(PermissionEventBase):
    event_type: Literal["permission_state_initialized"] = "permission_state_initialized"
    schema_version: Literal["permission_state_v1"] = "permission_state_v1"
    initial_stage: Literal[R4TeachingStage.PROBATIONARY]
    initial_permissions: tuple[PermissionLevel, ...] = (PermissionLevel.PUBLIC,)


class TeachingStageAdvanced(PermissionEventBase):
    event_type: Literal["teaching_stage_advanced"] = "teaching_stage_advanced"
    stage_before: R4TeachingStage
    stage_after: R4TeachingStage
    reason_code: Identifier


class ExamEligibilityGranted(PermissionEventBase):
    event_type: Literal["exam_eligibility_granted"] = "exam_eligibility_granted"


class ExamEligibilityRevoked(PermissionEventBase):
    event_type: Literal["exam_eligibility_revoked"] = "exam_eligibility_revoked"
    reason_code: Identifier


class InnerDiscipleStatusGranted(PermissionEventBase):
    event_type: Literal["inner_disciple_status_granted"] = "inner_disciple_status_granted"
    exam_attempt_id: Identifier


class PermissionGranted(PermissionEventBase):
    event_type: Literal["permission_granted"] = "permission_granted"
    permission: PermissionLevel
    source_reference_id: Identifier


class KnowledgeUnlocked(PermissionEventBase):
    event_type: Literal["knowledge_unlocked"] = "knowledge_unlocked"
    knowledge_id: Identifier
    permission: PermissionLevel
    source_reference_id: Identifier


class ExamRecognitionGranted(PermissionEventBase):
    event_type: Literal["exam_recognition_granted"] = "exam_recognition_granted"
    exam_attempt_id: Identifier
    delta: Literal[2]


class InheritanceGranted(PermissionEventBase):
    event_type: Literal["inheritance_granted"] = "inheritance_granted"
    inheritance_id: Identifier
    content_id: Identifier
    decision_revision: Identifier


PermissionEvent: TypeAlias = Annotated[
    PermissionStateInitialized | TeachingStageAdvanced | ExamEligibilityGranted
    | ExamEligibilityRevoked | InnerDiscipleStatusGranted | PermissionGranted
    | KnowledgeUnlocked | ExamRecognitionGranted | InheritanceGranted,
    Field(discriminator="event_type"),
]


class PermissionState(PermissionModel):
    schema_version: Literal["permission_state_v1"] = "permission_state_v1"
    player_id: Identifier
    teaching_stage: R4TeachingStage
    exam_eligible: StrictBool
    permissions: frozenset[PermissionLevel]
    unlocked_knowledge_ids: frozenset[Identifier]
    granted_inheritance_ids: frozenset[Identifier]
    exam_recognition_bonus: Annotated[StrictInt, Field(ge=0)]
    passed_exam_attempt_id: Identifier | None = None
    events: tuple[PermissionEvent, ...] = Field(min_length=1)
    revision: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime
    updated_at: datetime


class PermissionReplayError(ValueError):
    pass


class PermissionEventReplayer:
    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy

    def replay(self, events: tuple[PermissionEvent, ...]) -> PermissionState:
        if not events or not isinstance(events[0], PermissionStateInitialized):
            raise PermissionReplayError("permission state must begin with initialization")
        first = events[0]
        stage = first.initial_stage
        eligible = False
        permissions = set(first.initial_permissions)
        knowledge: set[str] = set()
        inheritances: set[str] = set()
        bonus = 0
        passed_attempt = None
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected or event.player_id != first.player_id:
                raise PermissionReplayError("invalid permission event sequence")
            if expected == 1:
                continue
            if isinstance(event, TeachingStageAdvanced):
                if event.stage_before is not stage or event.stage_after not in self.policy.allowed_stage_transitions[stage]:
                    raise PermissionReplayError("invalid teaching stage transition")
                stage = event.stage_after
            elif isinstance(event, ExamEligibilityGranted):
                if eligible:
                    raise PermissionReplayError("exam eligibility granted twice")
                eligible = True
            elif isinstance(event, ExamEligibilityRevoked):
                if not eligible:
                    raise PermissionReplayError("exam eligibility revoked while absent")
                eligible = False
            elif isinstance(event, InnerDiscipleStatusGranted):
                if passed_attempt is not None:
                    raise PermissionReplayError("inner disciple status granted twice")
                passed_attempt = event.exam_attempt_id
            elif isinstance(event, PermissionGranted):
                if event.permission in permissions or event.permission is PermissionLevel.MENTOR_SECRET:
                    raise PermissionReplayError("invalid permission grant")
                permissions.add(event.permission)
            elif isinstance(event, KnowledgeUnlocked):
                if event.permission not in permissions or event.knowledge_id in knowledge:
                    raise PermissionReplayError("invalid knowledge unlock")
                knowledge.add(event.knowledge_id)
            elif isinstance(event, ExamRecognitionGranted):
                if bonus or passed_attempt != event.exam_attempt_id:
                    raise PermissionReplayError("exam recognition may be granted once after pass")
                bonus += event.delta
            elif isinstance(event, InheritanceGranted):
                if event.inheritance_id in inheritances:
                    raise PermissionReplayError("inheritance granted twice")
                inheritances.add(event.inheritance_id)
            else:
                raise PermissionReplayError("initialization may appear only once")
        return PermissionState(
            player_id=first.player_id, teaching_stage=stage, exam_eligible=eligible,
            permissions=frozenset(permissions), unlocked_knowledge_ids=frozenset(knowledge),
            granted_inheritance_ids=frozenset(inheritances), exam_recognition_bonus=bonus,
            passed_exam_attempt_id=passed_attempt, events=events, revision=len(events),
            created_at=first.occurred_at, updated_at=events[-1].occurred_at,
        )
