"""Least-privilege structured teaching memory exposed to the mentor."""

from datetime import datetime

from pydantic import ConfigDict, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .curriculum import StructuredTeachingMemoryType


class RetrievedStructuredMemory(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    memory_id: Identifier
    memory_type: StructuredTeachingMemoryType
    public_summary: NonEmptyText
    source_case_id: Identifier | None = None
    occurred_at: datetime
    reason_code: Identifier

    @model_validator(mode="after")
    def aware_time(self) -> "RetrievedStructuredMemory":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("memory timestamp must include a timezone")
        return self
