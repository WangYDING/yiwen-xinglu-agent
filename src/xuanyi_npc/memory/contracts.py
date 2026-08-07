"""Strict M4-P1 contracts for public sources and authoritative memory."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseActionType
from xuanyi_npc.domain.memory import MemoryType, RelationshipImpact

from .canonical import (
    canonical_json,
    normalize_utc,
    sha256_hex,
    stable_lifecycle_operation_id,
    stable_memory_id,
    stable_correction_source_id,
    stable_source_event_id,
)


Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
UtcDateTime = Annotated[datetime, AfterValidator(normalize_utc)]


class StrictMemoryModel(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class MemoryWriteReason(str, Enum):
    VERIFIED_CASE_INVESTIGATION = "verified_case_investigation"
    VERIFIED_DIAGNOSIS_SUBMISSION = "verified_diagnosis_submission"
    VERIFIED_TREATMENT_OBSERVATION = "verified_treatment_observation"
    VERIFIED_MEMORY_CORRECTION = "verified_memory_correction"


class MemorySourceEventType(str, Enum):
    INVESTIGATION_COMPLETED = "investigation_completed"
    DIAGNOSIS_SUBMITTED = "diagnosis_submitted"
    TREATMENT_EXECUTED = "treatment_executed"
    MEMORY_CORRECTION = "memory_correction"


class PublicClueFact(StrictMemoryModel):
    clue_id: Identifier
    description: NonEmptyText


class InvestigationPublicPayload(StrictMemoryModel):
    payload_type: Literal["investigation_completed"] = "investigation_completed"
    case_id: Identifier
    case_title: NonEmptyText
    investigation_id: Identifier
    action_type: CaseActionType
    public_action_description: NonEmptyText
    newly_discovered_clues: tuple[PublicClueFact, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_stable_clue_order(self) -> "InvestigationPublicPayload":
        ids = [item.clue_id for item in self.newly_discovered_clues]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("public clues must be unique and sorted by clue_id")
        return self


class DiagnosisPublicPayload(StrictMemoryModel):
    payload_type: Literal["diagnosis_submitted"] = "diagnosis_submitted"
    case_id: Identifier
    case_title: NonEmptyText
    diagnosis_id: Identifier
    public_hypothesis_description: NonEmptyText
    cited_evidence: tuple[PublicClueFact, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_stable_evidence_order(self) -> "DiagnosisPublicPayload":
        ids = [item.clue_id for item in self.cited_evidence]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("cited evidence must be unique and sorted by clue_id")
        return self


class TreatmentPublicPayload(StrictMemoryModel):
    payload_type: Literal["treatment_executed"] = "treatment_executed"
    case_id: Identifier
    case_title: NonEmptyText
    treatment_id: Identifier
    public_action_description: NonEmptyText
    public_result: NonEmptyText


class CorrectionPublicPayload(StrictMemoryModel):
    payload_type: Literal["memory_correction"] = "memory_correction"
    operation_id: Identifier
    related_case_id: Identifier | None = None
    target_memory_id: Identifier
    replacement_public_content: NonEmptyText
    reason: NonEmptyText


PublicMemoryPayload: TypeAlias = Annotated[
    InvestigationPublicPayload
    | DiagnosisPublicPayload
    | TreatmentPublicPayload
    | CorrectionPublicPayload,
    Field(discriminator="payload_type"),
]


class VerifiedMemorySource(StrictMemoryModel):
    """A receipt containing only allowlisted, canonical public data."""

    source_event_id: Identifier
    player_id: Identifier
    source_session_id: Identifier
    source_event_type: MemorySourceEventType
    source_sequence: Annotated[StrictInt, Field(ge=1)]
    source_revision: Annotated[StrictInt, Field(ge=1)]
    projection_version: Identifier
    projection_ordinal: Annotated[StrictInt, Field(ge=0)]
    occurred_at: UtcDateTime
    public_payload: PublicMemoryPayload
    public_payload_hash: Sha256Hex

    @model_validator(mode="after")
    def verify_public_identity_and_hash(self) -> "VerifiedMemorySource":
        payload_type = self.public_payload.payload_type
        if payload_type != self.source_event_type.value:
            raise ValueError("source event type does not match public payload")
        if self.source_event_type is MemorySourceEventType.MEMORY_CORRECTION:
            if not isinstance(self.public_payload, CorrectionPublicPayload):
                raise ValueError("correction source requires a correction payload")
            if self.source_event_id != stable_correction_source_id(
                self.public_payload.operation_id
            ):
                raise ValueError("correction sources require a correction source id")
        else:
            expected_id = stable_source_event_id(
                self.source_event_type.value,
                self.source_session_id,
                self.source_sequence,
            )
            if self.source_event_id != expected_id:
                raise ValueError("source_event_id does not match public event identity")
        if self.public_payload_hash != sha256_hex(self.public_payload):
            raise ValueError("public_payload_hash does not match canonical public payload")
        return self


def authoritative_content_payload(
    *,
    memory_type: MemoryType,
    content: str,
    importance: int,
    related_case_id: str | None,
    related_entity_ids: frozenset[str],
) -> dict[str, object]:
    return {
        "content": content,
        "importance": importance,
        "memory_type": memory_type.value,
        "related_case_id": related_case_id,
        "related_entity_ids": sorted(related_entity_ids),
    }


class AuthoritativeMemoryRecord(StrictMemoryModel):
    memory_id: Identifier
    player_id: Identifier
    memory_type: MemoryType
    content: NonEmptyText
    importance: Annotated[StrictInt, Field(ge=1, le=5)]
    related_case_id: Identifier | None = None
    related_entity_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    relationship_impacts: tuple[RelationshipImpact, ...] = Field(default_factory=tuple)
    occurred_at: UtcDateTime
    source_event_id: Identifier
    source_session_id: Identifier
    source_event_type: MemorySourceEventType
    source_sequence: Annotated[StrictInt, Field(ge=1)]
    source_revision: Annotated[StrictInt, Field(ge=1)]
    projection_version: Identifier
    projection_ordinal: Annotated[StrictInt, Field(ge=0)]
    write_reason: MemoryWriteReason
    public_payload_hash: Sha256Hex
    content_hash: Sha256Hex
    status: MemoryStatus = MemoryStatus.ACTIVE
    supersedes_memory_id: Identifier | None = None

    @model_validator(mode="after")
    def verify_authoritative_shape(self) -> "AuthoritativeMemoryRecord":
        if self.memory_type not in {MemoryType.EPISODIC, MemoryType.LEARNING}:
            raise ValueError("V1 automatic memory only permits episodic or learning records")
        if self.relationship_impacts:
            raise ValueError("V1 memory relationship_impacts must be empty")
        expected_id = stable_memory_id(
            self.player_id,
            self.source_event_id,
            self.projection_version,
            self.projection_ordinal,
        )
        if self.memory_id != expected_id:
            raise ValueError("memory_id does not match its stable source key")
        expected_hash = sha256_hex(
            authoritative_content_payload(
                memory_type=self.memory_type,
                content=self.content,
                importance=self.importance,
                related_case_id=self.related_case_id,
                related_entity_ids=self.related_entity_ids,
            )
        )
        if self.content_hash != expected_hash:
            raise ValueError("content_hash does not match canonical public memory content")
        expected_reasons = {
            MemorySourceEventType.INVESTIGATION_COMPLETED: (
                MemoryWriteReason.VERIFIED_CASE_INVESTIGATION
            ),
            MemorySourceEventType.DIAGNOSIS_SUBMITTED: (
                MemoryWriteReason.VERIFIED_DIAGNOSIS_SUBMISSION
            ),
            MemorySourceEventType.TREATMENT_EXECUTED: (
                MemoryWriteReason.VERIFIED_TREATMENT_OBSERVATION
            ),
            MemorySourceEventType.MEMORY_CORRECTION: (
                MemoryWriteReason.VERIFIED_MEMORY_CORRECTION
            ),
        }
        if self.write_reason is not expected_reasons[self.source_event_type]:
            raise ValueError("write_reason does not match source event type")
        return self

    def immutable_projection_json(self) -> str:
        data = self.model_dump(mode="python", exclude={"status"})
        return canonical_json(data)


class ProjectionWriteDisposition(str, Enum):
    CREATED = "created"
    IDEMPOTENT = "idempotent"


class ProjectionWriteResult(StrictMemoryModel):
    disposition: ProjectionWriteDisposition
    memory_id: Identifier
    source_event_id: Identifier
    memory_status: MemoryStatus


class LifecycleAction(str, Enum):
    CORRECT = "correct"
    INVALIDATE = "invalidate"
    HARD_DELETE = "hard_delete"


class TrustedMemoryBoundary(str, Enum):
    V1_APPLICATION = "v1_application"
    ADMINISTRATOR = "administrator"


class MemoryLifecycleReason(str, Enum):
    VERIFIED_CORRECTION = "verified_correction"
    SOURCE_REVOKED = "source_revoked"
    ADMINISTRATIVE_INVALIDATION = "administrative_invalidation"
    PRIVACY_REQUEST = "privacy_request"


class MemoryLifecycleOperation(StrictMemoryModel):
    operation_id: Identifier
    request_id: Identifier
    action: LifecycleAction
    player_id: Identifier
    target_memory_id: Identifier
    reason: MemoryLifecycleReason
    trusted_boundary: TrustedMemoryBoundary
    occurred_at: UtcDateTime

    @model_validator(mode="after")
    def verify_operation_id_and_reason(self) -> "MemoryLifecycleOperation":
        expected = stable_lifecycle_operation_id(
            self.action.value,
            self.player_id,
            self.target_memory_id,
            self.request_id,
        )
        if self.operation_id != expected:
            raise ValueError("operation_id does not match stable lifecycle identity")
        allowed = {
            LifecycleAction.CORRECT: {MemoryLifecycleReason.VERIFIED_CORRECTION},
            LifecycleAction.INVALIDATE: {
                MemoryLifecycleReason.SOURCE_REVOKED,
                MemoryLifecycleReason.ADMINISTRATIVE_INVALIDATION,
            },
            LifecycleAction.HARD_DELETE: {MemoryLifecycleReason.PRIVACY_REQUEST},
        }
        if self.reason not in allowed[self.action]:
            raise ValueError("lifecycle reason is not valid for this action")
        return self


class MemoryCorrectionOperation(MemoryLifecycleOperation):
    action: Literal[LifecycleAction.CORRECT] = LifecycleAction.CORRECT
    replacement_public_content: NonEmptyText


class MemoryInvalidationOperation(MemoryLifecycleOperation):
    action: Literal[LifecycleAction.INVALIDATE] = LifecycleAction.INVALIDATE


class MemoryHardDeleteOperation(MemoryLifecycleOperation):
    action: Literal[LifecycleAction.HARD_DELETE] = LifecycleAction.HARD_DELETE


class LifecycleDisposition(str, Enum):
    APPLIED = "applied"
    IDEMPOTENT = "idempotent"


class MemoryLifecycleResult(StrictMemoryModel):
    disposition: LifecycleDisposition
    operation_id: Identifier
    target_memory_id: Identifier
    target_status: MemoryStatus | None = None
    replacement_memory_id: Identifier | None = None
    hard_deleted: StrictBool = False


class MemoryCommitStatus(str, Enum):
    COMPLETE = "complete"
    MEMORY_PROJECTION_PENDING = "memory_projection_pending"


class MemoryCommitResult(StrictMemoryModel):
    status: MemoryCommitStatus
    session_id: Identifier
    projections: tuple[ProjectionWriteResult, ...] = Field(default_factory=tuple)
    pending_source_event_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def verify_commit_shape(self) -> "MemoryCommitResult":
        if self.status is MemoryCommitStatus.COMPLETE:
            if self.pending_source_event_ids or self.error_code is not None:
                raise ValueError("complete commits cannot contain pending details")
        else:
            if not self.pending_source_event_ids or self.error_code is None:
                raise ValueError("pending commits require source ids and a safe error code")
        return self
