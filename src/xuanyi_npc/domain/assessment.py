"""Deterministic public assessment produced before mentor language."""

from typing import Annotated

from pydantic import ConfigDict, Field, StrictInt

from .apprenticeship import AbilityId, RelationshipDimension
from .base import DomainModel, Identifier, NonEmptyText
from .cases import TreatmentOutcome


class AssessmentModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PublicAbilityChange(AssessmentModel):
    ability_id: AbilityId
    proficiency_before: Annotated[StrictInt, Field(ge=0, le=100)]
    proficiency_after: Annotated[StrictInt, Field(ge=0, le=100)]
    delta: Annotated[StrictInt, Field(ge=1, le=2)]
    public_description: NonEmptyText


class PublicRelationshipChange(AssessmentModel):
    dimension: RelationshipDimension
    value_before: Annotated[StrictInt, Field(ge=0, le=100)]
    value_after: Annotated[StrictInt, Field(ge=0, le=100)]
    delta: Annotated[StrictInt, Field(ge=-2, le=2)]
    public_description: NonEmptyText


class AssessmentReport(AssessmentModel):
    assessment_id: Identifier
    player_id: Identifier
    case_id: Identifier
    case_session_id: Identifier
    lesson_id: Identifier
    outcome: TreatmentOutcome
    final_score: Annotated[StrictInt, Field(ge=0, le=100)]
    completed_objectives: tuple[Identifier, ...]
    missed_objectives: tuple[Identifier, ...]
    demonstrated_abilities: tuple[AbilityId, ...]
    improvement_abilities: tuple[AbilityId, ...]
    hints_used: tuple[Identifier, ...]
    ability_changes: tuple[PublicAbilityChange, ...]
    relationship_changes: tuple[PublicRelationshipChange, ...]
    public_evidence_references: tuple[Identifier, ...]
    fixed_next_step: NonEmptyText
    source_revision: Annotated[StrictInt, Field(ge=1)]
