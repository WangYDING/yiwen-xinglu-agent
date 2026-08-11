"""Frozen deterministic R4 examination contracts."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .apprenticeship import AbilityId
from .base import DomainModel, Identifier, NonEmptyText


class ExamModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ExamSection(str, Enum):
    EVIDENCE_INFERENCE = "evidence_and_inference"
    DIFFERENTIATION = "differentiation_and_decoy_exclusion"
    TREATMENT_ETHICS = "treatment_and_ethics"


class ExamOption(ExamModel):
    option_id: Identifier
    public_text: NonEmptyText


class ExamQuestion(ExamModel):
    question_id: Identifier
    section: ExamSection
    public_scenario: NonEmptyText
    options: tuple[ExamOption, ...] = Field(min_length=2)
    correct_option_ids: tuple[Identifier, ...] = Field(min_length=1)
    explanation: NonEmptyText
    score: Annotated[StrictInt, Field(ge=1, le=100)]
    critical_safety: StrictBool
    targeted_ability_ids: tuple[AbilityId, ...] = Field(min_length=1)
    remediation_id: Identifier

    @model_validator(mode="after")
    def validate_options(self) -> "ExamQuestion":
        option_ids = tuple(item.option_id for item in self.options)
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("exam option ids must be unique")
        if not set(self.correct_option_ids).issubset(option_ids):
            raise ValueError("correct option must identify a public option")
        return self


class ExamDefinition(ExamModel):
    exam_id: Literal["foundational_xuanyi_exam_v1"]
    version: Literal["v1"]
    title: NonEmptyText
    fictional_safety_notice: NonEmptyText
    questions: tuple[ExamQuestion, ...] = Field(min_length=6, max_length=6)
    total_score: Literal[100]
    passing_score: Literal[80]
    require_nonzero_each_section: Literal[True]
    critical_failure_blocks_pass: Literal[True]
    hint_limit: Literal[0]
    recognition_reward: Literal[2]
    source_revision: Literal["r4_contract_v1"]

    @model_validator(mode="after")
    def validate_exam(self) -> "ExamDefinition":
        if sum(item.score for item in self.questions) != self.total_score:
            raise ValueError("exam question scores must total 100")
        if len({item.question_id for item in self.questions}) != 6:
            raise ValueError("exam question ids must be unique")
        counts = {section: 0 for section in ExamSection}
        for item in self.questions:
            counts[item.section] += 1
        if set(counts.values()) != {2}:
            raise ValueError("exam must contain two questions in each section")
        if not any(item.critical_safety for item in self.questions):
            raise ValueError("exam must contain a critical safety question")
        return self


class ExamEligibilityPolicy(ExamModel):
    policy_id: Literal["exam_eligibility_v1"]
    version: Literal["v1"]
    required_core_lessons: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    mandatory_remediation_ids: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    required_positive_evidence_abilities: tuple[AbilityId, ...] = Field(min_length=3)
    unresolved_serious_abilities: tuple[AbilityId, ...] = Field(min_length=2)
    retake_requires_remediation: Literal[True]

