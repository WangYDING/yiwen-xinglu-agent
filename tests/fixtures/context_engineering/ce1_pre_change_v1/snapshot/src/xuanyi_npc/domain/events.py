"""Domain events emitted by successful deterministic case commands."""

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .base import DomainModel, Identifier
from .cases import CaseActionType, TreatmentOutcome


class CaseEventModel(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    sequence: Annotated[StrictInt, Field(ge=1)]
    session_id: Identifier
    occurred_at: datetime

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> "CaseEventModel":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return self


class InvestigationCompletedEvent(CaseEventModel):
    event_type: Literal["investigation_completed"] = "investigation_completed"
    investigation_id: Identifier
    action_type: CaseActionType
    target_id: Identifier
    newly_discovered_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)


class DiagnosisSubmittedEvent(CaseEventModel):
    event_type: Literal["diagnosis_submitted"] = "diagnosis_submitted"
    diagnosis_id: Identifier
    evidence_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)


class TreatmentExecutedEvent(CaseEventModel):
    event_type: Literal["treatment_executed"] = "treatment_executed"
    treatment_id: Identifier
    outcome: TreatmentOutcome
    diagnosis_correct: StrictBool
    score: Annotated[StrictInt, Field(ge=0, le=100)]


CaseEvent: TypeAlias = Annotated[
    InvestigationCompletedEvent | DiagnosisSubmittedEvent | TreatmentExecutedEvent,
    Field(discriminator="event_type"),
]
