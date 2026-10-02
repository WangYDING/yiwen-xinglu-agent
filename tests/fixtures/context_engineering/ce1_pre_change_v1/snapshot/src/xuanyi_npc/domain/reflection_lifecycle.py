"""Public/auditable results for bounded reflection lifecycle execution."""

from datetime import datetime
from enum import Enum

from pydantic import ConfigDict, Field

from .base import DomainModel, Identifier, NonEmptyText
from .reflection import ReflectionTriggerType
from .reflection_memory import ReflectionMemoryIndexStatus, ReflectionMemoryWriteDecision


class ReflectionLifecycleStatus(str, Enum):
    COMPLETED = "completed"
    NO_WRITE = "no_write"
    INDEX_PENDING = "index_pending"
    REPOSITORY_FAILURE = "repository_failure"
    FALLBACK = "fallback"
    FAILED_SAFE = "failed_safe"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class ReflectionProposalStatus(str, Enum):
    VALID = "valid"
    FALLBACK_EMPTY = "fallback_empty"
    FAILED_SAFE = "failed_safe"


class ReflectionGenerationAttemptTelemetry(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_index: int = Field(ge=1, le=2)
    attempt_kind: str
    provider_request_id: str | None = None
    configured_max_output_tokens: int | None = Field(default=None, ge=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    response_returned: bool
    failure_stage: str | None = None
    failure_code: str | None = None
    exception_class: str | None = None
    field_path: str | None = None
    error_count: int | None = Field(default=None, ge=1)


class ReflectionLifecycleResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_id: Identifier
    trigger_type: ReflectionTriggerType
    status: ReflectionLifecycleStatus
    proposal_status: ReflectionProposalStatus
    reflection_attempt_count: int = 0
    repaired: bool = False
    candidate_ids: tuple[Identifier, ...] = ()
    written_memory_ids: tuple[Identifier, ...] = ()
    write_decisions: tuple[ReflectionMemoryWriteDecision, ...] = ()
    provenance_ref_ids: tuple[Identifier, ...] = ()
    public_consolidation_summary: NonEmptyText | None = None
    index_status: ReflectionMemoryIndexStatus = ReflectionMemoryIndexStatus.NOT_REQUIRED
    error_code: Identifier | None = None
    generation_failure_stage: str | None = None
    generation_failure_code: str | None = None
    generation_exception_class: str | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    configured_max_output_tokens: int | None = None
    generation_attempt_count: int = 0
    repair_attempted: bool = False
    repair_succeeded: bool = False
    generation_attempts: tuple[ReflectionGenerationAttemptTelemetry, ...] = ()
    index_reconciled: bool = False
    previous_index_status: ReflectionMemoryIndexStatus | None = None
    previous_error_code: Identifier | None = None
    index_reconciliation_embedding_space_id: Identifier | None = None
    index_reconciled_memory_ids: tuple[Identifier, ...] = ()
    index_reconciled_at: datetime | None = None
