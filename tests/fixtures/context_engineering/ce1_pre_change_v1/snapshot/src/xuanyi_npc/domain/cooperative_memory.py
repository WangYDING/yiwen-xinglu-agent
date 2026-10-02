"""Safe memory projection models for the cooperative Game NPC."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictInt, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.memory import MemoryType


class AgentMemorySourceType(str, Enum):
    INVESTIGATION_COMPLETED = "investigation_completed"
    DIAGNOSIS_SUBMITTED = "diagnosis_submitted"
    TREATMENT_EXECUTED = "treatment_executed"
    MEMORY_CORRECTION = "memory_correction"
    STRUCTURED_EXPERIENCE = "structured_teaching_fact"


class AgentMemoryItem(DomainModel):
    """Least-privilege memory item safe to place in GameNPCAgent context."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    memory_id: Identifier
    memory_type: MemoryType
    public_summary: NonEmptyText
    source_type: AgentMemorySourceType
    source_episode_id: Identifier
    source_case_id: Identifier | None = None
    relevance_score: Annotated[float, Field(strict=True, ge=-1.0, le=1.0)]
    confidence: Annotated[float, Field(strict=True, ge=0.0, le=1.0)]
    reason_code: Identifier
    occurred_at: datetime
    last_verified_at: datetime
    conflict_with_current_observation: bool = False

    @model_validator(mode="after")
    def validate_memory_item(self) -> "AgentMemoryItem":
        for value in (self.occurred_at, self.last_verified_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("memory timestamps must include a timezone")
        return self


class AgentMemoryContext(DomainModel):
    """Bounded projection of retrieved memories for one cooperative turn."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    retrieval_id: Identifier
    query_basis: NonEmptyText
    normalized_query: NonEmptyText
    memories: tuple[AgentMemoryItem, ...] = Field(default_factory=tuple)
    retrieval_summary: NonEmptyText
    candidate_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    selected_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    total_candidates: Annotated[StrictInt, Field(ge=0)]
    selected_count: Annotated[StrictInt, Field(ge=0)]
    max_selected: Annotated[StrictInt, Field(ge=1, le=10)]
    char_budget: Annotated[StrictInt, Field(ge=120, le=4000)]
    selected_chars: Annotated[StrictInt, Field(ge=0)]
    embedding_space_id: Identifier
    query_template_version: Identifier
    index_status: Identifier
    active_memory_count: Annotated[StrictInt, Field(ge=0)]
    valid_embedding_count: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def validate_context(self) -> "AgentMemoryContext":
        memory_ids = tuple(item.memory_id for item in self.memories)
        if memory_ids != self.selected_memory_ids:
            raise ValueError("selected_memory_ids must match projected memories")
        if self.selected_count != len(self.memories):
            raise ValueError("selected_count must match projected memories")
        if self.selected_count > self.max_selected:
            raise ValueError("selected_count exceeds max_selected")
        if self.selected_chars > self.char_budget:
            raise ValueError("selected memory text exceeds char budget")
        if len(set(self.candidate_memory_ids)) != len(self.candidate_memory_ids):
            raise ValueError("candidate memory IDs must be unique")
        return self


class MemoryRetrievalStatus(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    FAILED_SAFE = "failed_safe"


class MemoryUsageAttributionStatus(str, Enum):
    ACCEPTED = "accepted"
    DECLARED_ONLY = "declared_only"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class MemoryUsageTrace(DomainModel):
    """Auditable external attribution, not a claim about model internals."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    retrieval_id: Identifier | None = None
    retrieval_status: MemoryRetrievalStatus
    candidate_memory_ids: tuple[Identifier, ...] = ()
    selected_memory_ids: tuple[Identifier, ...] = ()
    declared_used_memory_ids: tuple[Identifier, ...] = ()
    accepted_used_memory_ids: tuple[Identifier, ...] = ()
    rejected_memory_ids: tuple[Identifier, ...] = ()
    influence_types: tuple[Identifier, ...] = ()
    attribution_status: MemoryUsageAttributionStatus
    goal_changed: bool = False
    plan_changed: bool = False
    decision_influenced: bool = False
    tool_priority_influenced: bool = False
    communication_influenced: bool = False
    public_effect_summary: NonEmptyText | None = None
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_trace(self) -> "MemoryUsageTrace":
        selected = set(self.selected_memory_ids)
        if any(memory_id not in selected for memory_id in self.declared_used_memory_ids):
            raise ValueError("declared memory must come from selected context")
        if any(memory_id not in selected for memory_id in self.accepted_used_memory_ids):
            raise ValueError("accepted memory must come from selected context")
        if any(memory_id not in self.declared_used_memory_ids for memory_id in self.accepted_used_memory_ids):
            raise ValueError("accepted memory must have been declared")
        if self.attribution_status is MemoryUsageAttributionStatus.ACCEPTED and not self.accepted_used_memory_ids:
            raise ValueError("accepted attribution requires accepted memory IDs")
        return self
