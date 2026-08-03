"""Player skill state and prerequisite declarations."""

from typing import Annotated

from pydantic import Field, StrictBool, StrictInt, model_validator

from .base import DomainModel, Identifier


Proficiency = Annotated[StrictInt, Field(ge=0, le=100)]


class SkillState(DomainModel):
    skill_id: Identifier
    proficiency: Proficiency = 0
    unlocked: StrictBool = False
    prerequisite_ids: frozenset[Identifier] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_lock_state(self) -> "SkillState":
        if self.skill_id in self.prerequisite_ids:
            raise ValueError("a skill cannot require itself")
        if not self.unlocked and self.proficiency != 0:
            raise ValueError("a locked skill cannot have proficiency")
        return self
