"""Pure deterministic execution of one structured case session."""

from xuanyi_npc.domain.cases import (
    ActionRecord,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
    TreatmentOutcome,
)
from xuanyi_npc.domain.commands import (
    CaseCommand,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    SubmitDiagnosisCommand,
)
from xuanyi_npc.domain.events import (
    DiagnosisSubmittedEvent,
    InvestigationCompletedEvent,
    TreatmentExecutedEvent,
)
from xuanyi_npc.domain.player import PlayerState

from .errors import (
    ActionMismatchError,
    ContextMismatchError,
    DiagnosisRequiredError,
    EvidenceNotDiscoveredError,
    InsufficientSkillError,
    MissingCluePrerequisiteError,
    SessionClosedError,
    SkillLockedError,
    TreatmentPrerequisiteError,
    UnknownCommandError,
    UnknownInvestigationError,
    UnknownTreatmentError,
)
from .results import EngineResult, ScoreBreakdown


class CaseEngine:
    """Execute validated commands without mutating any input model."""

    def execute(
        self,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        command: CaseCommand,
    ) -> EngineResult:
        self._validate_context(case, player, session)

        if session.status is not CaseSessionStatus.ACTIVE:
            raise SessionClosedError("the case session is already completed")

        if isinstance(command, InvestigationCommand):
            return self._investigate(case, player, session, command)
        if isinstance(command, SubmitDiagnosisCommand):
            return self._submit_diagnosis(case, session, command)
        if isinstance(command, ExecuteTreatmentCommand):
            return self._execute_treatment(case, session, command)
        raise UnknownCommandError("the command type is not supported")

    @staticmethod
    def _validate_context(
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
    ) -> None:
        if session.case_id != case.case_id:
            raise ContextMismatchError("session case_id does not match the case definition")
        if session.player_id != player.player_id:
            raise ContextMismatchError("session player_id does not match the player state")

    def _investigate(
        self,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        command: InvestigationCommand,
    ) -> EngineResult:
        investigation = next(
            (
                item
                for item in case.investigations
                if item.investigation_id == command.investigation_id
            ),
            None,
        )
        if investigation is None:
            raise UnknownInvestigationError(
                f"unknown investigation: {command.investigation_id}"
            )
        if (
            investigation.action_type != command.action_type
            or investigation.target_id != command.target_id
        ):
            raise ActionMismatchError(
                "command action_type or target_id does not match the investigation"
            )

        self._validate_skill(
            player,
            investigation.required_skill_id,
            investigation.minimum_skill_level,
        )

        missing_clues = investigation.required_clue_ids.difference(
            session.discovered_clue_ids
        )
        if missing_clues:
            missing_text = ", ".join(sorted(missing_clues))
            raise MissingCluePrerequisiteError(
                f"investigation requires undiscovered clues: {missing_text}"
            )

        newly_discovered = investigation.reveals_clue_ids.difference(
            session.discovered_clue_ids
        )
        next_sequence = len(session.action_history) + 1
        record = ActionRecord(
            sequence=next_sequence,
            action_type=command.action_type,
            reference_id=investigation.investigation_id,
            target_id=command.target_id,
            revealed_clue_ids=newly_discovered,
            occurred_at=command.occurred_at,
        )
        updated_session = self._updated_session(
            session,
            discovered_clue_ids=(
                session.discovered_clue_ids | investigation.reveals_clue_ids
            ),
            action_history=(*session.action_history, record),
            revision=session.revision + 1,
        )
        event = InvestigationCompletedEvent(
            sequence=next_sequence,
            session_id=session.session_id,
            occurred_at=command.occurred_at,
            investigation_id=investigation.investigation_id,
            action_type=command.action_type,
            target_id=command.target_id,
            newly_discovered_clue_ids=newly_discovered,
        )

        if newly_discovered:
            descriptions = "；".join(
                case.clues[clue_id].description
                for clue_id in sorted(newly_discovered)
            )
            message = f"调查完成。新发现：{descriptions}"
        else:
            message = "调查完成，但没有发现新的线索。"
        return EngineResult(session=updated_session, events=(event,), message=message)

    @staticmethod
    def _validate_skill(
        player: PlayerState,
        required_skill_id: str | None,
        minimum_skill_level: int,
    ) -> None:
        if required_skill_id is None:
            return
        skill = player.skills.get(required_skill_id)
        if skill is None or not skill.unlocked:
            raise SkillLockedError(f"required skill is locked: {required_skill_id}")
        if skill.proficiency < minimum_skill_level:
            raise InsufficientSkillError(
                f"skill {required_skill_id} requires proficiency {minimum_skill_level}"
            )

    def _submit_diagnosis(
        self,
        case: CaseDefinition,
        session: CaseSessionState,
        command: SubmitDiagnosisCommand,
    ) -> EngineResult:
        unavailable_evidence = command.evidence_clue_ids.difference(
            session.discovered_clue_ids
        )
        if unavailable_evidence:
            evidence_text = ", ".join(sorted(unavailable_evidence))
            raise EvidenceNotDiscoveredError(
                f"diagnosis cites evidence not discovered in this session: {evidence_text}"
            )

        next_sequence = len(session.action_history) + 1
        record = ActionRecord(
            sequence=next_sequence,
            action_type="submit_diagnosis",
            reference_id=command.diagnosis_id,
            target_id=command.diagnosis_id,
            evidence_clue_ids=command.evidence_clue_ids,
            occurred_at=command.occurred_at,
        )
        updated_session = self._updated_session(
            session,
            submitted_diagnosis_id=command.diagnosis_id,
            action_history=(*session.action_history, record),
            revision=session.revision + 1,
        )
        event = DiagnosisSubmittedEvent(
            sequence=next_sequence,
            session_id=session.session_id,
            occurred_at=command.occurred_at,
            diagnosis_id=command.diagnosis_id,
            evidence_clue_ids=command.evidence_clue_ids,
        )
        return EngineResult(
            session=updated_session,
            events=(event,),
            message="诊断已经记录，需要通过处置结果复验。",
        )

    def _execute_treatment(
        self,
        case: CaseDefinition,
        session: CaseSessionState,
        command: ExecuteTreatmentCommand,
    ) -> EngineResult:
        if session.submitted_diagnosis_id is None:
            raise DiagnosisRequiredError("a diagnosis must be submitted before treatment")

        treatment = case.treatments.get(command.treatment_id)
        if treatment is None:
            raise UnknownTreatmentError(f"unknown treatment: {command.treatment_id}")

        missing_clues = treatment.required_clue_ids.difference(
            session.discovered_clue_ids
        )
        if missing_clues:
            missing_text = ", ".join(sorted(missing_clues))
            raise TreatmentPrerequisiteError(
                f"treatment requires undiscovered clues: {missing_text}"
            )

        breakdown = self._score(case, session, treatment.outcome)
        next_sequence = len(session.action_history) + 1
        record = ActionRecord(
            sequence=next_sequence,
            action_type="execute_treatment",
            reference_id=treatment.treatment_id,
            target_id=treatment.treatment_id,
            occurred_at=command.occurred_at,
        )
        updated_session = self._updated_session(
            session,
            status=CaseSessionStatus.COMPLETED,
            selected_treatment_id=treatment.treatment_id,
            outcome=treatment.outcome,
            score=breakdown.total,
            action_history=(*session.action_history, record),
            revision=session.revision + 1,
        )
        event = TreatmentExecutedEvent(
            sequence=next_sequence,
            session_id=session.session_id,
            occurred_at=command.occurred_at,
            treatment_id=treatment.treatment_id,
            outcome=treatment.outcome,
            diagnosis_correct=breakdown.diagnosis_correct,
            score=breakdown.total,
        )
        outcome_messages = {
            TreatmentOutcome.RESOLVED: "处置触及根因，病例已经解决。",
            TreatmentOutcome.SUPPRESSED: "症状暂时减弱，但根因仍未解除。",
            TreatmentOutcome.WORSENED: "处置违背病例因果，异常进一步恶化。",
        }
        return EngineResult(
            session=updated_session,
            events=(event,),
            message=outcome_messages[treatment.outcome],
            score_breakdown=breakdown,
        )

    @staticmethod
    def _score(
        case: CaseDefinition,
        session: CaseSessionState,
        outcome: TreatmentOutcome,
    ) -> ScoreBreakdown:
        key_clue_ids = {
            clue_id for clue_id, clue in case.clues.items() if clue.is_key
        }
        discovered_key_clues = len(
            key_clue_ids.intersection(session.discovered_clue_ids)
        )
        clue_points = (
            case.scoring.key_clue_points
            * discovered_key_clues
            // len(key_clue_ids)
        )
        diagnosis_correct = session.submitted_diagnosis_id in case.valid_diagnosis_ids
        diagnosis_points = (
            case.scoring.correct_diagnosis_points if diagnosis_correct else 0
        )
        treatment_points = (
            case.scoring.correct_treatment_points
            if outcome is TreatmentOutcome.RESOLVED
            else 0
        )
        unsafe_penalty = (
            case.scoring.unsafe_treatment_penalty
            if outcome is TreatmentOutcome.WORSENED
            else 0
        )
        total = max(
            0,
            min(
                case.scoring.max_score,
                clue_points + diagnosis_points + treatment_points - unsafe_penalty,
            ),
        )
        return ScoreBreakdown(
            discovered_key_clues=discovered_key_clues,
            total_key_clues=len(key_clue_ids),
            clue_points=clue_points,
            diagnosis_correct=diagnosis_correct,
            diagnosis_points=diagnosis_points,
            treatment_points=treatment_points,
            unsafe_treatment_penalty=unsafe_penalty,
            total=total,
        )

    @staticmethod
    def _updated_session(
        session: CaseSessionState,
        **changes: object,
    ) -> CaseSessionState:
        data = session.model_dump(mode="python")
        data.update(changes)
        return CaseSessionState.model_validate(data)
