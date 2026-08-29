"""Permission-filtered read models safe to place in Agent context."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import (
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
)
from xuanyi_npc.domain.player import PlayerState
from xuanyi_npc.domain.memory import MemoryType

if TYPE_CHECKING:
    from xuanyi_npc.memory.embeddings import InternalMemorySearchResult


class AgentViewModel(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class AvailableSkillView(AgentViewModel):
    skill_id: Identifier
    proficiency: StrictInt = Field(ge=0, le=100)


class PlayerView(AgentViewModel):
    """Player facts allowed in V0 context; hidden gates and raw relations are absent."""

    player_id: Identifier
    display_name: NonEmptyText
    available_skills: tuple[AvailableSkillView, ...] = Field(default_factory=tuple)


class ObservedClueView(AgentViewModel):
    clue_id: Identifier
    description: NonEmptyText


class InvestigationOptionView(AgentViewModel):
    investigation_id: Identifier
    action_type: CaseActionType
    target_id: Identifier
    public_description: NonEmptyText


class DiagnosisCandidateView(AgentViewModel):
    diagnosis_id: Identifier
    public_description: NonEmptyText


class TreatmentOptionView(AgentViewModel):
    """Public action semantics; outcome and gate rules stay private."""

    treatment_id: Identifier
    public_description: NonEmptyText


class CaseObservation(AgentViewModel):
    """Current observable case state, excluding world truth and hidden content."""

    case_id: Identifier
    title: NonEmptyText
    synopsis: NonEmptyText
    patient_id: Identifier
    patient_name: NonEmptyText
    patient_public_profile: NonEmptyText
    session_status: CaseSessionStatus
    session_revision: StrictInt = Field(ge=0)
    discovered_clues: tuple[ObservedClueView, ...] = Field(default_factory=tuple)
    available_investigations: tuple[InvestigationOptionView, ...] = Field(
        default_factory=tuple
    )
    diagnosis_candidates: tuple[DiagnosisCandidateView, ...] = Field(
        default_factory=tuple
    )
    can_submit_diagnosis: StrictBool
    submitted_diagnosis_id: Identifier | None = None
    available_treatments: tuple[TreatmentOptionView, ...] = Field(default_factory=tuple)


V1_READABLE_MEMORY_TYPES = (MemoryType.EPISODIC, MemoryType.LEARNING)


class MemoryScope(AgentViewModel):
    """Trusted cross-Episode retrieval scope; never supplied by a model."""

    player_id: Identifier
    allowed_memory_types: tuple[MemoryType, ...]
    excluded_source_session_id: Identifier

    @model_validator(mode="after")
    def require_frozen_v1_scope(self) -> "MemoryScope":
        if self.allowed_memory_types != V1_READABLE_MEMORY_TYPES:
            raise ValueError("V1 memory scope permits only episodic and learning memory")
        return self


class MemoryView(AgentViewModel):
    """Least-privilege memory data safe to serialize into V1 user context."""

    memory_id: Identifier
    memory_type: MemoryType
    content: NonEmptyText
    occurred_at: datetime

    @model_validator(mode="after")
    def require_public_v1_memory(self) -> "MemoryView":
        if self.memory_type not in V1_READABLE_MEMORY_TYPES:
            raise ValueError("memory type is not readable by V1")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("memory occurred_at must include a timezone")
        return self


class MemoryContextStatus(str, Enum):
    READY = "ready"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


class ViewContextError(ValueError):
    """Raised when incompatible state is passed to the permission filter."""


class AgentContextFilter:
    """Build least-privilege context before any model call occurs."""

    def player_view(self, player: PlayerState) -> PlayerView:
        skills = tuple(
            AvailableSkillView(
                skill_id=skill.skill_id,
                proficiency=skill.proficiency,
            )
            for skill in sorted(player.skills.values(), key=lambda item: item.skill_id)
            if skill.unlocked
        )
        return PlayerView(
            player_id=player.player_id,
            display_name=player.display_name,
            available_skills=skills,
        )

    def memory_scope(
        self,
        player: PlayerState,
        session: CaseSessionState,
    ) -> MemoryScope:
        if session.player_id != player.player_id:
            raise ViewContextError("session player_id does not match player state")
        return MemoryScope(
            player_id=player.player_id,
            allowed_memory_types=V1_READABLE_MEMORY_TYPES,
            excluded_source_session_id=session.session_id,
        )

    def memory_views(
        self,
        scope: MemoryScope,
        result: InternalMemorySearchResult,
    ) -> tuple[MemoryView, ...]:
        """Revalidate internal retrieval output before any model request."""

        if result.player_id != scope.player_id:
            raise ViewContextError("memory result player does not match trusted scope")
        views: list[MemoryView] = []
        for hit in result.hits:
            if hit.player_id != scope.player_id:
                raise ViewContextError("memory hit player does not match trusted scope")
            if hit.memory_type not in scope.allowed_memory_types:
                raise ViewContextError("memory hit type is outside trusted scope")
            if hit.source_session_id == scope.excluded_source_session_id:
                raise ViewContextError("current Episode memory crossed the context boundary")
            views.append(
                MemoryView(
                    memory_id=hit.memory_id,
                    memory_type=hit.memory_type,
                    content=hit.content,
                    occurred_at=hit.occurred_at,
                )
            )
        return tuple(views)

    def case_observation(
        self,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
    ) -> CaseObservation:
        if session.case_id != case.case_id:
            raise ViewContextError("session case_id does not match case definition")
        if session.player_id != player.player_id:
            raise ViewContextError("session player_id does not match player state")

        is_active = session.status is CaseSessionStatus.ACTIVE
        satisfied_requirement_ids = case.satisfied_requirement_ids(session)
        investigations = tuple(
            InvestigationOptionView(
                investigation_id=investigation.investigation_id,
                action_type=investigation.action_type,
                target_id=investigation.target_id,
                public_description=investigation.public_description,
            )
            for investigation in sorted(
                case.investigations,
                key=lambda item: item.investigation_id,
            )
            if is_active
            and case.requirement_for(investigation.investigation_id).requirement_id not in satisfied_requirement_ids
            and not any(
                record.reference_id == investigation.investigation_id
                and record.action_type == investigation.action_type
                for record in session.action_history
            )
            and self._skill_is_available(
                player,
                investigation.required_skill_id,
                investigation.minimum_skill_level,
            )
            and investigation.required_clue_ids.issubset(session.discovered_clue_ids)
        )
        clues = tuple(
            ObservedClueView(
                clue_id=clue_id,
                description=case.clues[clue_id].description,
            )
            for clue_id in sorted(session.discovered_clue_ids)
        )
        diagnosis_candidates = tuple(
            DiagnosisCandidateView(
                diagnosis_id=candidate.diagnosis_id,
                public_description=candidate.public_description,
            )
            for candidate in sorted(
                case.diagnosis_candidates.values(),
                key=lambda item: item.diagnosis_id,
            )
        )
        treatments = tuple(
            TreatmentOptionView(
                treatment_id=treatment.treatment_id,
                public_description=treatment.public_description,
            )
            for treatment in sorted(
                case.treatments.values(),
                key=lambda item: item.treatment_id,
            )
            if is_active
            and session.submitted_diagnosis_id is not None
            and treatment.required_clue_ids.issubset(session.discovered_clue_ids)
        )
        return CaseObservation(
            case_id=case.case_id,
            title=case.title,
            synopsis=case.synopsis,
            patient_id=case.patient.patient_id,
            patient_name=case.patient.display_name,
            patient_public_profile=case.patient.public_profile,
            session_status=session.status,
            session_revision=session.revision,
            discovered_clues=clues,
            available_investigations=investigations,
            diagnosis_candidates=diagnosis_candidates,
            can_submit_diagnosis=(
                is_active and session.submitted_diagnosis_id is None
            ),
            submitted_diagnosis_id=session.submitted_diagnosis_id,
            available_treatments=treatments,
        )

    @staticmethod
    def _skill_is_available(
        player: PlayerState,
        skill_id: str | None,
        minimum_level: int,
    ) -> bool:
        if skill_id is None:
            return True
        skill = player.skills.get(skill_id)
        # Case data historically called the public 验物 ability
        # ``inspect_object``. The player skill map uses the unified public id
        # ``inspect_evidence``; read projections must apply the same alias as
        # the authoritative engine so stale case definitions cannot disagree
        # with execution.
        if skill is None and skill_id == "inspect_object":
            skill = player.skills.get("inspect_evidence")
        return bool(
            skill is not None
            and skill.unlocked
            and skill.proficiency >= minimum_level
        )
