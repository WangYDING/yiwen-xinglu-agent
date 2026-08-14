"""Frozen deterministic R4 inheritance contracts."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .apprenticeship import AbilityId, RelationshipDimension
from .base import DomainModel, Identifier, NonEmptyText
from .permissions import PermissionLevel, R4TeachingStage


class InheritanceModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AbilityRequirement(InheritanceModel):
    ability_id: AbilityId
    minimum_proficiency: Annotated[StrictInt, Field(ge=0, le=100)]


class RelationshipRequirement(InheritanceModel):
    dimension: RelationshipDimension
    minimum_value: Annotated[StrictInt, Field(ge=0, le=100)]


class GrantedContent(InheritanceModel):
    content_id: Identifier
    public_title: NonEmptyText
    public_description: NonEmptyText
    restricted_text: NonEmptyText


class ReachabilitySnapshot(InheritanceModel):
    route_id: Identifier
    ability_values: dict[AbilityId, Annotated[StrictInt, Field(ge=0, le=100)]]
    relationship_values: dict[RelationshipDimension, Annotated[StrictInt, Field(ge=0, le=100)]]
    expected_inheritance_eligible_after_exam: bool


class InheritanceDefinition(InheritanceModel):
    inheritance_id: Literal["trace_vow_restore_v1"]
    version: Literal["v1"]
    title: NonEmptyText
    public_teaser: NonEmptyText
    restricted_description: NonEmptyText
    required_stage: Literal[R4TeachingStage.INNER_DISCIPLE]
    required_permissions: tuple[PermissionLevel, ...] = Field(min_length=1)
    required_lessons: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    required_knowledge_ids: tuple[Identifier, ...] = Field(min_length=2, max_length=2)
    required_exam: Literal["foundational_xuanyi_exam_v1"]
    required_abilities: tuple[AbilityRequirement, ...] = Field(min_length=4, max_length=4)
    required_relationship: tuple[RelationshipRequirement, ...] = Field(min_length=2, max_length=2)
    blocking_improvement_areas: tuple[AbilityId, ...] = Field(min_length=2)
    granted_content: GrantedContent
    public_reason_messages: dict[Identifier, NonEmptyText]
    reachability_audit: tuple[ReachabilitySnapshot, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_requirements(self) -> "InheritanceDefinition":
        if len({item.ability_id for item in self.required_abilities}) != 4:
            raise ValueError("inheritance ability requirements must be unique")
        if len({item.dimension for item in self.required_relationship}) != 2:
            raise ValueError("inheritance relationship requirements must be unique")
        return self


class R4AcceptanceScenario(InheritanceModel):
    scenario_id: Identifier
    input_facts: tuple[NonEmptyText, ...] = Field(min_length=1)
    expected_stage: R4TeachingStage
    expected_reason_codes: tuple[Identifier, ...]
    expected_permissions: tuple[PermissionLevel, ...]
    expected_inheritance_granted: bool


class R4AcceptanceContract(InheritanceModel):
    contract_id: Literal["r4_acceptance_v1"]
    version: Literal["v1"]
    scenarios: tuple[R4AcceptanceScenario, ...] = Field(min_length=8)


class InheritanceDecision(InheritanceModel):
    eligible: StrictBool
    public_reason_codes: tuple[Identifier, ...]
    missing_requirement_categories: tuple[Identifier, ...]
    inheritance_id: Literal["trace_vow_restore_v1"]
    decision_revision: Identifier

    @model_validator(mode="after")
    def validate_decision(self) -> "InheritanceDecision":
        if self.eligible and (self.public_reason_codes or self.missing_requirement_categories):
            raise ValueError("eligible inheritance cannot have missing requirements")
        if not self.eligible and not self.public_reason_codes:
            raise ValueError("refusal requires public reasons")
        return self
