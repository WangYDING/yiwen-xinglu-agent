"""Trusted mentor profile and strict public teaching action contracts."""

from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictInt, model_validator

from .apprenticeship import AbilityId, RelationshipDimension
from .base import DomainModel, Identifier, NonEmptyText


class MentorModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class MentorAttitudes(MentorModel):
    evidence: NonEmptyText
    promises: NonEmptyText
    non_human_beings: NonEmptyText
    risk: NonEmptyText


class MentorProfile(MentorModel):
    mentor_id: Identifier
    display_name: NonEmptyText
    version: str
    role: NonEmptyText
    stable_personality: tuple[NonEmptyText, ...]
    core_values: tuple[NonEmptyText, ...]
    speaking_style: NonEmptyText
    teaching_principles: tuple[NonEmptyText, ...]
    attitudes: MentorAttitudes
    public_background: NonEmptyText
    private_boundaries: tuple[NonEmptyText, ...]
    safety_rules: tuple[NonEmptyText, ...]

    def public_view(self) -> "MentorPublicProfile":
        return MentorPublicProfile(
            mentor_id=self.mentor_id,
            display_name=self.display_name,
            version=self.version,
            role=self.role,
            stable_personality=self.stable_personality,
            core_values=self.core_values,
            speaking_style=self.speaking_style,
            teaching_principles=self.teaching_principles,
            attitudes=self.attitudes,
            public_background=self.public_background,
            safety_rules=self.safety_rules,
        )


class MentorPublicProfile(MentorModel):
    """Only the profile fields allowed to cross the model boundary."""

    mentor_id: Identifier
    display_name: NonEmptyText
    version: str
    role: NonEmptyText
    stable_personality: tuple[NonEmptyText, ...]
    core_values: tuple[NonEmptyText, ...]
    speaking_style: NonEmptyText
    teaching_principles: tuple[NonEmptyText, ...]
    attitudes: MentorAttitudes
    public_background: NonEmptyText
    safety_rules: tuple[NonEmptyText, ...]


class LearningObjective(MentorModel):
    objective_id: Identifier
    description: NonEmptyText


class ReflectionCheckpoint(MentorModel):
    minimum_investigation_categories: Annotated[StrictInt, Field(ge=3, le=5)]
    question: NonEmptyText


class HintCard(MentorModel):
    hint_id: Identifier
    text: NonEmptyText


class LessonDefinition(MentorModel):
    lesson_id: Identifier
    version: str
    title: NonEmptyText
    public_description: NonEmptyText
    learning_objectives: tuple[LearningObjective, ...] = Field(min_length=1)
    assigned_case_id: Identifier
    reflection_checkpoint: ReflectionCheckpoint
    maximum_hints: Annotated[StrictInt, Field(ge=0, le=2)]
    public_hint_cards: tuple[HintCard, ...]
    completion_condition: NonEmptyText
    fixed_next_step: NonEmptyText

    @model_validator(mode="after")
    def validate_cards(self) -> "LessonDefinition":
        ids = [item.hint_id for item in self.public_hint_cards]
        if len(ids) != len(set(ids)) or len(ids) != self.maximum_hints:
            raise ValueError("lesson hint cards must be unique and match maximum_hints")
        expected_cases = {
            "evidence_before_diagnosis_v1": "old_paper_umbrella",
            "provenance_before_intent_v1": "gray_hearth_inn",
            "corroborate_before_handoff_v1": "moon_well_echo",
        }
        if expected_cases.get(self.lesson_id) != self.assigned_case_id:
            raise ValueError("lesson_id must use its frozen R3 case binding")
        return self


class MentorInteractionPhase(str, Enum):
    LESSON_START = "lesson_start"
    INVESTIGATION = "investigation"
    CASE_COMPLETE = "case_complete"


class MentorActionType(str, Enum):
    SPEAK = "speak"
    ASK_REFLECTION = "ask_reflection"
    GIVE_HINT = "give_hint"
    REVIEW_PERFORMANCE = "review_performance"
    RECOMMEND_FIXED_NEXT_STEP = "recommend_fixed_next_step"


class MentorAction(MentorModel):
    action_type: MentorActionType
    message: NonEmptyText
    hint_id: Identifier | None = None
    referenced_public_evidence_ids: tuple[Identifier, ...] = ()
    referenced_ability_ids: tuple[AbilityId, ...] = ()
    referenced_relationship_dimensions: tuple[RelationshipDimension, ...] = ()

    @model_validator(mode="after")
    def validate_hint_shape(self) -> "MentorAction":
        if (self.action_type is MentorActionType.GIVE_HINT) != (self.hint_id is not None):
            raise ValueError("hint_id is required only for give_hint")
        return self
