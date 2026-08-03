"""Mentor relationship state."""

from typing import Annotated

from pydantic import Field, StrictInt

from .base import DomainModel


RelationshipScore = Annotated[StrictInt, Field(ge=0, le=100)]


class RelationshipState(DomainModel):
    """Three independent dimensions; flattery alone cannot unlock inheritance."""

    affinity: RelationshipScore = 0
    trust: RelationshipScore = 0
    recognition: RelationshipScore = 0
