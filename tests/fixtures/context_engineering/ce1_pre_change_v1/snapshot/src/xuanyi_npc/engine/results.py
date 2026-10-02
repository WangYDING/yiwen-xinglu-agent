"""Structured results produced by the deterministic case engine."""

from typing import Annotated

from pydantic import Field, StrictBool, StrictInt

from xuanyi_npc.domain.base import DomainModel, NonEmptyText
from xuanyi_npc.domain.cases import CaseSessionState
from xuanyi_npc.domain.events import CaseEvent


ScorePart = Annotated[StrictInt, Field(ge=0, le=100)]


class ScoreBreakdown(DomainModel):
    discovered_key_clues: Annotated[StrictInt, Field(ge=0)]
    total_key_clues: Annotated[StrictInt, Field(gt=0)]
    clue_points: ScorePart
    diagnosis_correct: StrictBool
    diagnosis_points: ScorePart
    treatment_points: ScorePart
    unsafe_treatment_penalty: ScorePart
    total: ScorePart


class EngineResult(DomainModel):
    session: CaseSessionState
    events: tuple[CaseEvent, ...] = Field(min_length=1)
    message: NonEmptyText
    score_breakdown: ScoreBreakdown | None = None
