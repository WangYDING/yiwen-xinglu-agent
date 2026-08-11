"""Deterministic R3 curriculum selection and teaching-plan coordination."""

import hashlib
from dataclasses import dataclass

from xuanyi_npc.domain.apprenticeship import (
    AbilityId,
    ApprenticeshipState,
    EvidencePolarity,
)
from xuanyi_npc.domain.assessment import AssessmentReport
from xuanyi_npc.domain.curriculum import (
    CurriculumSelectionPolicy,
    RecommendationKind,
    RemediationDefinition,
)
from xuanyi_npc.domain.mentor import LessonDefinition
from xuanyi_npc.domain.teaching_plan import (
    CoreLessonCompleted,
    RemediationAssigned,
    RemediationAttempted,
    RemediationCompleted,
    RecommendationDeviationRecorded,
    TeachingPlanEvent,
    TeachingPlanEventReplayer,
    TeachingPlanInitialized,
    TeachingPlanState,
    TeachingRecommendation,
    TeachingRecommendationUpdated,
)
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage.json_store import JsonStateStore, StateNotFoundError


CORE_RESOURCE_NAMES = (
    "evidence_before_diagnosis_v1.json",
    "provenance_before_intent_v1.json",
    "corroborate_before_handoff_v1.json",
)
REMEDIATION_RESOURCE_NAMES = (
    "remediate_evidence_completeness_v1.json",
    "remediate_diagnostic_reasoning_v1.json",
    "remediate_treatment_alignment_v1.json",
)


@dataclass(frozen=True)
class CurriculumCatalog:
    lessons: dict[str, LessonDefinition]
    lessons_by_case: dict[str, LessonDefinition]
    remediations: dict[str, RemediationDefinition]
    policy: CurriculumSelectionPolicy

    @classmethod
    def load(cls) -> "CurriculumCatalog":
        lessons = tuple(
            LessonDefinition.model_validate_json(read_runtime_text(f"curriculum/{name}"))
            for name in CORE_RESOURCE_NAMES
        )
        remediations = tuple(
            RemediationDefinition.model_validate_json(read_runtime_text(f"curriculum/{name}"))
            for name in REMEDIATION_RESOURCE_NAMES
        )
        policy = CurriculumSelectionPolicy.model_validate_json(
            read_runtime_text("curriculum/curriculum_selection_v1.json")
        )
        return cls(
            lessons={item.lesson_id: item for item in lessons},
            lessons_by_case={item.assigned_case_id: item for item in lessons},
            remediations={item.remediation_id: item for item in remediations},
            policy=policy,
        )


class CurriculumSelector:
    def __init__(self, catalog: CurriculumCatalog | None = None) -> None:
        self.catalog = catalog or CurriculumCatalog.load()

    def select(
        self,
        *,
        apprenticeship: ApprenticeshipState,
        plan: TeachingPlanState,
        assessment_improvements: tuple[AbilityId, ...] = (),
    ) -> tuple[TeachingRecommendation, tuple[AbilityId, ...]]:
        latest = {}
        for evidence in sorted(
            apprenticeship.evidence_history,
            key=lambda item: (item.occurred_at, item.evidence_id),
        ):
            latest[evidence.ability_id] = evidence
        completion_times: dict[AbilityId, object] = {}
        for event in plan.events:
            if isinstance(event, RemediationCompleted):
                for ability_id in event.target_ability_ids:
                    completion_times[ability_id] = event.occurred_at
        unresolved_values = {
            ability_id
            for ability_id, evidence in latest.items()
            if evidence.polarity is EvidencePolarity.NEEDS_IMPROVEMENT
            and (
                ability_id not in completion_times
                or completion_times[ability_id] < evidence.occurred_at
            )
        }
        unresolved_values.update(assessment_improvements)
        unresolved_values.update(
            ability_id for ability_id in plan.unresolved_improvement_areas
            if ability_id not in completion_times
        )
        unresolved = tuple(
            sorted(
                unresolved_values,
                key=lambda item: item.value,
            )
        )
        unresolved_set = set(unresolved)
        for rule in self.catalog.policy.improvement_priority:
            matching = tuple(sorted(unresolved_set.intersection(rule.ability_ids), key=lambda item: item.value))
            if matching:
                return (
                    TeachingRecommendation(
                        kind=RecommendationKind.REMEDIATION,
                        recommendation_id=rule.remediation_id,
                        reason_codes=(rule.reason_code,),
                    ),
                    unresolved,
                )
        for lesson_id in self.catalog.policy.core_lesson_order:
            if lesson_id not in plan.completed_core_lessons:
                return (
                    TeachingRecommendation(
                        kind=RecommendationKind.CORE_LESSON,
                        recommendation_id=lesson_id,
                        reason_codes=("next_incomplete_core_lesson",),
                    ),
                    unresolved,
                )
        return (
            TeachingRecommendation(
                kind=RecommendationKind.FOUNDATION_COMPLETE,
                recommendation_id="foundation_complete",
                reason_codes=("foundation_three_lessons_complete",),
            ),
            unresolved,
        )


class TeachingPlanService:
    def __init__(self, store: JsonStateStore, *, clock, catalog: CurriculumCatalog | None = None):
        self.store = store
        self.clock = clock
        self.catalog = catalog or CurriculumCatalog.load()
        self.selector = CurriculumSelector(self.catalog)

    def ensure(self, player_id: str) -> TeachingPlanState:
        try:
            return self.store.load_teaching_plan(player_id)
        except StateNotFoundError:
            event = TeachingPlanInitialized(sequence=1, player_id=player_id, occurred_at=self.clock.now())
            state = TeachingPlanEventReplayer().replay((event,))
            apprenticeship = self.store.load_apprenticeship(player_id)
            state = self._update_recommendation(state, apprenticeship, None)
            self.store.save_teaching_plan(state)
            return state

    def record_assessment(self, report: AssessmentReport) -> TeachingPlanState:
        state = self.ensure(report.player_id)
        if report.assessment_id == state.last_assessment_id:
            return state
        if report.lesson_id not in state.completed_core_lessons:
            state = self._append(
                state,
                CoreLessonCompleted(
                    sequence=state.revision + 1,
                    player_id=state.player_id,
                    occurred_at=self.clock.now(),
                    lesson_id=report.lesson_id,
                    assessment_id=report.assessment_id,
                    source_case_id=report.case_id,
                    source_session_id=report.case_session_id,
                    source_revision=report.source_revision,
                ),
            )
        apprenticeship = self.store.load_apprenticeship(report.player_id)
        recommendation, _ = self.selector.select(
            apprenticeship=apprenticeship,
            plan=state,
            assessment_improvements=report.improvement_abilities,
        )
        if recommendation.kind is RecommendationKind.REMEDIATION:
            definition = self.catalog.remediations[recommendation.recommendation_id]
            already_assigned = any(
                isinstance(item, RemediationAssigned)
                and item.source_assessment_id == report.assessment_id
                and item.remediation_id == definition.remediation_id
                for item in state.events
            )
            if not already_assigned:
                state = self._append(
                    state,
                    RemediationAssigned(
                        sequence=state.revision + 1,
                        player_id=state.player_id,
                        occurred_at=self.clock.now(),
                        remediation_id=definition.remediation_id,
                        reason_codes=recommendation.reason_codes,
                        target_ability_ids=definition.target_ability_ids,
                        source_assessment_id=report.assessment_id,
                    ),
                )
        state = self._update_recommendation(
            state,
            apprenticeship,
            report.assessment_id,
            report.improvement_abilities,
        )
        self.store.save_teaching_plan(state)
        return state

    def record_deviation(
        self, *, player_id: str, case_session_id: str, chosen_lesson_id: str
    ) -> TeachingPlanState:
        state = self.ensure(player_id)
        recommendation = state.current_recommendation
        if (
            recommendation is None
            or recommendation.recommendation_id == chosen_lesson_id
            or case_session_id in state.recommendation_deviations
        ):
            return state
        state = self._append(
            state,
            RecommendationDeviationRecorded(
                sequence=state.revision + 1,
                player_id=player_id,
                occurred_at=self.clock.now(),
                case_session_id=case_session_id,
                chosen_lesson_id=chosen_lesson_id,
                recommended_id=recommendation.recommendation_id,
            ),
        )
        self.store.save_teaching_plan(state)
        return state

    def attempt_remediation(
        self, *, player_id: str, remediation_id: str, option_id: str, request_id: str
    ) -> tuple[TeachingPlanState, bool]:
        state = self.ensure(player_id)
        definition = self.catalog.remediations[remediation_id]
        attempt_id = "remediation_attempt_" + hashlib.sha256(
            f"{player_id}|{remediation_id}|{request_id}".encode()
        ).hexdigest()[:20]
        existing = next(
            (item for item in state.events if isinstance(item, RemediationAttempted) and item.attempt_id == attempt_id),
            None,
        )
        if existing is not None:
            return state, existing.correct
        correct = option_id == definition.correct_option_id
        state = self._append(
            state,
            RemediationAttempted(
                sequence=state.revision + 1,
                player_id=player_id,
                occurred_at=self.clock.now(),
                attempt_id=attempt_id,
                remediation_id=remediation_id,
                selected_option_id=option_id,
                correct=correct,
            ),
        )
        if correct and remediation_id not in state.completed_remediations:
            state = self._append(
                state,
                RemediationCompleted(
                    sequence=state.revision + 1,
                    player_id=player_id,
                    occurred_at=self.clock.now(),
                    remediation_id=remediation_id,
                    attempt_id=attempt_id,
                    target_ability_ids=definition.target_ability_ids,
                ),
            )
        apprenticeship = self.store.load_apprenticeship(player_id)
        state = self._update_recommendation(state, apprenticeship, state.last_assessment_id)
        self.store.save_teaching_plan(state)
        return state, correct

    def _update_recommendation(
        self, state, apprenticeship, assessment_id, assessment_improvements=()
    ):
        recommendation, unresolved = self.selector.select(
            apprenticeship=apprenticeship,
            plan=state,
            assessment_improvements=assessment_improvements,
        )
        sources = tuple(
            sorted(
                {
                    *(item.evidence_id for item in apprenticeship.evidence_history if item.ability_id in unresolved),
                    *(() if assessment_id is None else (assessment_id,)),
                }
            )
        )
        if (
            state.current_recommendation == recommendation
            and state.unresolved_improvement_areas == unresolved
            and state.last_assessment_id == assessment_id
        ):
            return state
        return self._append(
            state,
            TeachingRecommendationUpdated(
                sequence=state.revision + 1,
                player_id=state.player_id,
                occurred_at=self.clock.now(),
                recommendation=recommendation,
                unresolved_improvement_areas=unresolved,
                last_assessment_id=assessment_id,
                source_references=sources,
            ),
        )

    @staticmethod
    def _append(state: TeachingPlanState, event: TeachingPlanEvent) -> TeachingPlanState:
        return TeachingPlanEventReplayer().replay((*state.events, event))
