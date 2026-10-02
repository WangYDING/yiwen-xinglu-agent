"""Auditable M4 reflection-memory candidate and consolidation results."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .memory import MemoryType
from .reflection import (
    ApplicabilityScope,
    EvidenceRef,
    ReflectionConfidence,
    ReusableLessonType,
)


class ReflectionMemoryCandidate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: Identifier
    fingerprint: Identifier
    player_id: Identifier
    source_reflection_proposal_id: Identifier
    source_trigger_id: Identifier
    episode_id: Identifier
    case_id: Identifier
    lesson_type: ReusableLessonType
    proposed_memory_type: MemoryType
    public_safe_summary: NonEmptyText
    applicability_scope: ApplicabilityScope
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=2, max_length=8)
    reflection_confidence: ReflectionConfidence
    source: Literal["reflection_generated"] = "reflection_generated"
    candidate_ordinal: Annotated[StrictInt, Field(ge=0, le=2)]

    @model_validator(mode="after")
    def validate_provenance_ownership(self) -> "ReflectionMemoryCandidate":
        if any(
            ref.episode_id != self.episode_id or ref.case_id != self.case_id
            for ref in self.evidence_refs
        ):
            raise ValueError("candidate provenance must share episode/case ownership")
        return self


class ReflectionMemoryWriteOutcome(str, Enum):
    WRITE_NEW = "write_new"
    SKIP_DUPLICATE = "skip_duplicate"
    REJECT_WEAK_EVIDENCE = "reject_weak_evidence"
    REJECT_UNSAFE = "reject_unsafe"
    REJECT_CONFLICT = "reject_conflict"
    REJECT_SCOPE_TOO_BROAD = "reject_scope_too_broad"
    REJECT_OWNERSHIP = "reject_ownership"
    REPOSITORY_FAILURE = "repository_failure"


class ReflectionMemoryIndexStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    COMPLETE = "complete"
    PENDING = "pending"


class ReflectionMemoryWriteDecision(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: Identifier
    outcome: ReflectionMemoryWriteOutcome
    reason_code: Identifier
    memory_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_memory_id(self) -> "ReflectionMemoryWriteDecision":
        if self.outcome is not ReflectionMemoryWriteOutcome.WRITE_NEW and self.memory_id is not None:
            raise ValueError("non-write outcome cannot claim a memory_id")
        return self


class ReflectionConsolidationResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reflection_proposal_id: Identifier
    trigger_id: Identifier
    candidate_ids: tuple[Identifier, ...] = ()
    written_memory_ids: tuple[Identifier, ...] = ()
    decisions: tuple[ReflectionMemoryWriteDecision, ...] = ()
    index_status: ReflectionMemoryIndexStatus = ReflectionMemoryIndexStatus.NOT_REQUIRED
    index_error_code: Identifier | None = None
