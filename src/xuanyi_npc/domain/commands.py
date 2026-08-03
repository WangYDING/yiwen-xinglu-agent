"""Validated commands accepted by the deterministic case engine."""

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, model_validator

from .base import DomainModel, Identifier
from .cases import CaseActionType, INVESTIGATION_ACTIONS


class CaseCommandModel(DomainModel):
    """Commands are immutable inputs; the application layer supplies the time."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    occurred_at: datetime

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> "CaseCommandModel":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return self


class InvestigationCommand(CaseCommandModel):
    command_type: Literal["investigate"] = "investigate"
    investigation_id: Identifier
    action_type: CaseActionType
    target_id: Identifier

    @model_validator(mode="after")
    def require_investigation_action(self) -> "InvestigationCommand":
        if self.action_type not in INVESTIGATION_ACTIONS:
            raise ValueError("investigation commands require an investigation action")
        return self


class SubmitDiagnosisCommand(CaseCommandModel):
    command_type: Literal["submit_diagnosis"] = "submit_diagnosis"
    diagnosis_id: Identifier
    evidence_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)


class ExecuteTreatmentCommand(CaseCommandModel):
    command_type: Literal["execute_treatment"] = "execute_treatment"
    treatment_id: Identifier


CaseCommand: TypeAlias = Annotated[
    InvestigationCommand | SubmitDiagnosisCommand | ExecuteTreatmentCommand,
    Field(discriminator="command_type"),
]
