"""Frozen R3 curriculum, remediation, and structured-memory contracts."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .apprenticeship import AbilityId
from .base import DomainModel, Identifier, NonEmptyText


class CurriculumModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RemediationAnswerOption(CurriculumModel):
    option_id: Identifier
    public_text: NonEmptyText


class RemediationDefinition(CurriculumModel):
    remediation_id: Identifier
    version: Literal["v1"] = "v1"
    title: NonEmptyText
    target_ability_ids: tuple[AbilityId, ...] = Field(min_length=1)
    public_explanation: NonEmptyText
    structured_question: NonEmptyText
    answer_options: tuple[RemediationAnswerOption, ...] = Field(min_length=2)
    correct_option_id: Identifier
    completion_feedback: NonEmptyText
    next_step: NonEmptyText

    @model_validator(mode="after")
    def validate_options(self) -> "RemediationDefinition":
        option_ids = tuple(item.option_id for item in self.answer_options)
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("remediation answer options must be unique")
        if self.correct_option_id not in option_ids:
            raise ValueError("correct_option_id must identify an answer option")
        return self


class RecommendationKind(str, Enum):
    CORE_LESSON = "core_lesson"
    REMEDIATION = "remediation"
    FOUNDATION_COMPLETE = "foundation_complete"


class CurriculumPriorityRule(CurriculumModel):
    priority: Annotated[StrictInt, Field(ge=1)]
    ability_ids: tuple[AbilityId, ...] = Field(min_length=1)
    remediation_id: Identifier
    reason_code: Identifier


class CurriculumSelectionPolicy(CurriculumModel):
    policy_id: Literal["curriculum_selection_v1"] = "curriculum_selection_v1"
    version: Literal["v1"] = "v1"
    improvement_priority: tuple[CurriculumPriorityRule, ...] = Field(min_length=4)
    core_lesson_order: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    stable_tie_breaker: Literal["ability_id_asc"] = "ability_id_asc"
    foundation_complete_message: NonEmptyText
    recommendations_do_not_lock_cases: Literal[True] = True

    @model_validator(mode="after")
    def validate_frozen_order(self) -> "CurriculumSelectionPolicy":
        priorities = tuple(item.priority for item in self.improvement_priority)
        if priorities != tuple(sorted(priorities)) or len(priorities) != len(set(priorities)):
            raise ValueError("curriculum priorities must be unique and ascending")
        expected = (
            AbilityId.ETHICAL_PRACTICE,
            AbilityId.APPLY_TREATMENT,
            AbilityId.REASON_DIAGNOSIS,
        )
        if tuple(item.ability_ids[0] for item in self.improvement_priority[:3]) != expected:
            raise ValueError("R3 safety, treatment, diagnosis priority is frozen")
        return self


class StructuredTeachingMemoryType(str, Enum):
    CASE_EXPERIENCE = "case_experience"
    ABILITY_STRENGTH = "ability_strength"
    LEARNING_PATTERN = "learning_pattern"
    MENTOR_FEEDBACK = "mentor_feedback"
    REMEDIATION_HISTORY = "remediation_history"
    EXAM_EVENT = "exam_event"
    PERMISSION_EVENT = "permission_event"
    INHERITANCE_EVENT = "inheritance_event"


class StructuredMemorySourceType(str, Enum):
    CASE_COMPLETION = "case_completion"
    ABILITY_EVIDENCE = "ability_evidence"
    ASSESSMENT = "assessment"
    REMEDIATION_RESULT = "remediation_result"
    CORE_LESSON_COMPLETION = "core_lesson_completion"
    EXAM_EVENT = "exam_event"
    PERMISSION_EVENT = "permission_event"
    INHERITANCE_EVENT = "inheritance_event"


class StructuredMemorySelectionPolicy(CurriculumModel):
    policy_id: Literal["structured_mentor_memory_selection_v1"] = (
        "structured_mentor_memory_selection_v1"
    )
    version: Literal["v1"] = "v1"
    allowed_memory_types: tuple[StructuredTeachingMemoryType, ...] = Field(min_length=8)
    allowed_source_types: tuple[StructuredMemorySourceType, ...] = Field(min_length=8)
    category_priority: tuple[Identifier, ...] = Field(min_length=8, max_length=8)
    ordering: tuple[Literal["priority_desc", "occurred_at_desc", "memory_id_asc"], ...]
    default_limit: Literal[3] = 3
    player_filter_first: Literal[True] = True
    exclude_current_episode: Literal[True] = True
    exclude_inactive: Literal[True] = True
    exclude_deleted: Literal[True] = True
    requires_embedding: Literal[False] = False
    uses_similarity: Literal[False] = False

    @model_validator(mode="after")
    def validate_frozen_selection(self) -> "StructuredMemorySelectionPolicy":
        if set(self.allowed_memory_types) != set(StructuredTeachingMemoryType):
            raise ValueError("all and only R3 structured memory types are required")
        if set(self.allowed_source_types) != set(StructuredMemorySourceType):
            raise ValueError("all and only trusted R3 memory sources are required")
        if self.ordering != (
            "priority_desc",
            "occurred_at_desc",
            "memory_id_asc",
        ):
            raise ValueError("structured memory ordering is frozen")
        return self


class R3AcceptanceExpectation(CurriculumModel):
    scenario_id: Identifier
    input_facts: tuple[NonEmptyText, ...]
    expected_recommendation_id: Identifier
    expected_reason_codes: tuple[Identifier, ...]


class R3AcceptanceContract(CurriculumModel):
    contract_id: Literal["r3_acceptance_v1"] = "r3_acceptance_v1"
    version: Literal["v1"] = "v1"
    scenarios: tuple[R3AcceptanceExpectation, ...] = Field(min_length=6)
