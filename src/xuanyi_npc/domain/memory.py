"""Auditable memory event data."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import Field, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    RELATIONSHIP = "relationship"
    LEARNING = "learning"
    COMMITMENT = "commitment"
    REFLECTION = "reflection"


class RelationshipDimension(str, Enum):
    AFFINITY = "affinity"
    TRUST = "trust"
    RECOGNITION = "recognition"


class RelationshipImpact(DomainModel):
    dimension: RelationshipDimension
    delta: Annotated[StrictInt, Field(ge=-20, le=20)]
    reason: NonEmptyText


class MemoryEvent(DomainModel):
    event_id: Identifier
    player_id: Identifier
    event_type: MemoryType
    content: NonEmptyText
    importance: Annotated[StrictInt, Field(ge=1, le=5)]
    related_case_id: Identifier | None = None
    related_entity_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    relationship_impacts: tuple[RelationshipImpact, ...] = Field(default_factory=tuple)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> "MemoryEvent":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return self
