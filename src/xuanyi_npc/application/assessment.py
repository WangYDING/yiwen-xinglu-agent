"""Deterministic R2 assessment derived only from committed public sources."""

import hashlib
import json

from xuanyi_npc.domain.apprenticeship import (
    AbilityId,
    AbilityEvidenceRecorded,
    AbilityProgressed,
    ApprenticeshipState,
    EvidencePolarity,
    RelationshipChanged,
)
from xuanyi_npc.domain.assessment import (
    AssessmentReport,
    PublicAbilityChange,
    PublicRelationshipChange,
)
from xuanyi_npc.domain.cases import (
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
    INVESTIGATION_ACTIONS,
    TreatmentOutcome,
)
from xuanyi_npc.domain.mentor import LessonDefinition


class AssessmentSourceError(ValueError):
    pass


class AssessmentBuilder:
    def build(
        self,
        *,
        session: CaseSessionState,
        case: CaseDefinition,
        apprenticeship: ApprenticeshipState,
        lesson: LessonDefinition,
        used_hint_ids: tuple[str, ...],
    ) -> AssessmentReport:
        if session.status is not CaseSessionStatus.COMPLETED:
            raise AssessmentSourceError("case is not completed")
        if session.player_id != apprenticeship.player_id or session.case_id != case.case_id:
            raise AssessmentSourceError("assessment source ownership mismatch")
        if session.session_id not in apprenticeship.completed_source_sessions:
            raise AssessmentSourceError("apprenticeship projection is pending")
        if lesson.assigned_case_id != session.case_id:
            raise AssessmentSourceError("lesson does not match case")

        evidence_events = tuple(
            event for event in apprenticeship.events
            if isinstance(event, AbilityEvidenceRecorded)
            and event.evidence.source_session_id == session.session_id
        )
        evidence_ids = {event.evidence.evidence_id for event in evidence_events}
        positive = {
            event.evidence.ability_id for event in evidence_events
            if event.evidence.polarity is EvidencePolarity.DEMONSTRATED
        }
        improvement = {
            event.evidence.ability_id for event in evidence_events
            if event.evidence.polarity is EvidencePolarity.NEEDS_IMPROVEMENT
        }
        investigated_ids = {
            record.reference_id for record in session.action_history
            if record.action_type in INVESTIGATION_ACTIONS
        }
        missing_requirements = tuple(
            item for item in case.normalized_investigation_requirements()
            if not item.satisfying_investigation_ids.intersection(investigated_ids)
        )
        investigation_ability = {
            CaseActionType.OBSERVE_PATIENT: AbilityId.OBSERVE_FORM,
            CaseActionType.QUESTION_PATIENT: AbilityId.ASK_CAUSE,
            CaseActionType.INSPECT_OBJECT: AbilityId.INSPECT_EVIDENCE,
            CaseActionType.INVESTIGATE_LOCATION: AbilityId.INSPECT_EVIDENCE,
            CaseActionType.OBSERVE_QI: AbilityId.REASON_DIAGNOSIS,
        }
        improvement.update(
            investigation_ability[next(item for item in case.investigations if item.investigation_id in requirement.satisfying_investigation_ids).action_type]
            for requirement in missing_requirements
        )
        ability_changes = tuple(
            PublicAbilityChange(
                ability_id=event.ability_id,
                proficiency_before=event.proficiency_before,
                proficiency_after=event.proficiency_after,
                delta=event.delta,
                public_description=event.public_description,
            )
            for event in apprenticeship.events
            if isinstance(event, AbilityProgressed)
            and evidence_ids.intersection(event.evidence_ids)
        )
        relationship_changes = tuple(
            PublicRelationshipChange(
                dimension=event.dimension,
                value_before=event.value_before,
                value_after=event.value_after,
                delta=event.delta,
                public_description=event.public_description,
            )
            for event in apprenticeship.events
            if isinstance(event, RelationshipChanged)
            and event.source_session_id == session.session_id
        )

        diagnosis = next(
            (record for record in session.action_history
             if record.action_type is CaseActionType.SUBMIT_DIAGNOSIS),
            None,
        )
        completed: list[str] = []
        complete_investigation = not missing_requirements
        cited_evidence = diagnosis is not None and bool(diagnosis.evidence_clue_ids)
        if not cited_evidence:
            improvement.add(AbilityId.INSPECT_EVIDENCE)
        if complete_investigation:
            completed.extend((
                "cover_public_investigations",
                "separate_fact_inference_lure",
                "verify_contract_provenance",
                "separate_anomaly_from_malice",
                "corroborate_witness_and_object",
                "avoid_single_testimony",
                "identify_timing_and_handoff",
            ))
        if cited_evidence:
            completed.extend((
                "cite_discovered_evidence",
                "separate_prior_case_from_current_truth",
            ))
        diagnosis_positive = any(
            event.evidence.public_reason_code == "diagnosis_positive"
            for event in evidence_events
        )
        if (
            session.outcome is TreatmentOutcome.RESOLVED
            and diagnosis_positive
        ):
            completed.extend((
                "align_treatment_with_judgment",
                "avoid_harming_related_roles",
                "align_action_with_public_cause",
            ))
        if session.submitted_diagnosis_id != "evil_spirit_attack":
            completed.append("avoid_prejudging_anomaly")
        objective_ids = tuple(item.objective_id for item in lesson.learning_objectives)
        if session.outcome is TreatmentOutcome.RESOLVED and diagnosis_positive:
            completed.extend(objective_ids)
        completed_ordered = tuple(item for item in objective_ids if item in completed)
        missed = tuple(item for item in objective_ids if item not in completed)
        public_refs = tuple(sorted(diagnosis.evidence_clue_ids)) if diagnosis else ()
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "session": session.model_dump(mode="json"),
                    "hints": used_hint_ids,
                    "growth_events": [
                        event.model_dump(mode="json")
                        for event in apprenticeship.events
                        if (
                            isinstance(event, AbilityEvidenceRecorded)
                            and event.evidence.source_session_id == session.session_id
                        )
                        or (
                            isinstance(event, AbilityProgressed)
                            and evidence_ids.intersection(event.evidence_ids)
                        )
                        or (
                            isinstance(event, RelationshipChanged)
                            and event.source_session_id == session.session_id
                        )
                    ],
                    "lesson": lesson.lesson_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:20]
        return AssessmentReport(
            assessment_id=f"assessment_{fingerprint}",
            player_id=session.player_id,
            case_id=session.case_id,
            case_session_id=session.session_id,
            lesson_id=lesson.lesson_id,
            outcome=session.outcome,
            final_score=session.score,
            completed_objectives=completed_ordered,
            missed_objectives=missed,
            demonstrated_abilities=tuple(
                sorted(positive.difference(improvement), key=lambda item: item.value)
            ),
            improvement_abilities=tuple(sorted(improvement, key=lambda item: item.value)),
            hints_used=used_hint_ids,
            ability_changes=ability_changes,
            relationship_changes=relationship_changes,
            public_evidence_references=public_refs,
            fixed_next_step=lesson.fixed_next_step,
            source_revision=session.revision,
        )
