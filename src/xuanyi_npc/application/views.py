"""Permission-filtered read models safe to place in Agent context."""

from pydantic import ConfigDict, Field, StrictBool, StrictInt

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import (
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
)
from xuanyi_npc.domain.player import PlayerState, TeachingStage


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
    teaching_stage: TeachingStage
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
            teaching_stage=player.teaching_stage,
            available_skills=skills,
        )

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
            and self._skill_is_available(player, investigation.required_skill_id, investigation.minimum_skill_level)
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
            can_submit_diagnosis=is_active,
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
        return bool(
            skill is not None
            and skill.unlocked
            and skill.proficiency >= minimum_level
        )
