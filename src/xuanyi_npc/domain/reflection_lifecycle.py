"""Public/auditable results for bounded reflection lifecycle execution."""

from enum import Enum

from pydantic import ConfigDict

from .base import DomainModel, Identifier, NonEmptyText
from .reflection import ReflectionTriggerType
from .reflection_memory import ReflectionMemoryWriteDecision


class ReflectionLifecycleStatus(str, Enum):
    COMPLETED = "completed"
    FALLBACK = "fallback"
    FAILED_SAFE = "failed_safe"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class ReflectionProposalStatus(str, Enum):
    VALID = "valid"
    FALLBACK_EMPTY = "fallback_empty"
    FAILED_SAFE = "failed_safe"


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
    error_code: Identifier | None = None

