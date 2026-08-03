"""Player aggregate state."""

from enum import Enum

from pydantic import Field, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .relationship import RelationshipState
from .skills import SkillState


class TeachingStage(str, Enum):
    NOVICE = "novice"
    ADVANCED = "advanced"
    EXAM = "exam"


class PlayerState(DomainModel):
    player_id: Identifier
    display_name: NonEmptyText
    teaching_stage: TeachingStage = TeachingStage.NOVICE
    handled_case_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    skills: dict[Identifier, SkillState] = Field(default_factory=dict)
    relationship: RelationshipState = Field(default_factory=RelationshipState)

    @model_validator(mode="after")
    def validate_skill_graph(self) -> "PlayerState":
        for key, skill in self.skills.items():
            if key != skill.skill_id:
                raise ValueError(f"skill map key {key!r} does not match skill_id")

            missing = skill.prerequisite_ids.difference(self.skills)
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(f"skill {skill.skill_id!r} has missing prerequisites: {missing_text}")

            if skill.unlocked:
                locked = {
                    prerequisite_id
                    for prerequisite_id in skill.prerequisite_ids
                    if not self.skills[prerequisite_id].unlocked
                }
                if locked:
                    locked_text = ", ".join(sorted(locked))
                    raise ValueError(
                        f"skill {skill.skill_id!r} has locked prerequisites: {locked_text}"
                    )
        return self
