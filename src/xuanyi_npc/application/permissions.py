"""Deterministic R4 stage coordination and permission-filtered public views."""

from dataclasses import dataclass

from pydantic import ConfigDict

from xuanyi_npc.domain.apprenticeship import AbilityId, EvidencePolarity
from xuanyi_npc.application.progression import ProgressionPolicy
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.exams import ExamEligibilityPolicy
from xuanyi_npc.domain.permissions import (
    ExamEligibilityGranted,
    ExamEligibilityRevoked,
    ExamRecognitionGranted,
    InnerDiscipleStatusGranted,
    PermissionEvent,
    PermissionEventReplayer,
    PermissionGranted,
    PermissionLevel,
    PermissionPolicy,
    PermissionState,
    PermissionStateInitialized,
    R4TeachingStage,
    TeachingStageAdvanced,
)
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage.json_store import JsonStateStore, StateNotFoundError


CORE_LESSONS = (
    "evidence_before_diagnosis_v1",
    "provenance_before_intent_v1",
    "corroborate_before_handoff_v1",
)
MANDATORY_REMEDIATIONS = (
    "remediate_evidence_completeness_v1",
    "remediate_diagnostic_reasoning_v1",
    "remediate_treatment_alignment_v1",
)


class PermissionAccessError(ValueError):
    error_code = "knowledge_access_denied"


class PermissionPublicView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_id: Identifier
    teaching_stage: R4TeachingStage
    exam_eligible: bool
    permissions: tuple[PermissionLevel, ...]
    unlocked_knowledge_ids: tuple[Identifier, ...]
    granted_inheritance_ids: tuple[Identifier, ...]
    effective_recognition: int
    revision: int


class RestrictedKnowledgeView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content_id: Identifier
    title: NonEmptyText
    description: NonEmptyText


@dataclass(frozen=True)
class PermissionCoordinator:
    store: JsonStateStore
    clock: object

    def __post_init__(self) -> None:
        policy = PermissionPolicy.model_validate_json(
            read_runtime_text("permissions/permission_policy_v1.json")
        )
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "replayer", PermissionEventReplayer(policy))
        object.__setattr__(self, "eligibility_policy", ExamEligibilityPolicy(
            policy_id="exam_eligibility_v1", version="v1",
            required_core_lessons=CORE_LESSONS,
            mandatory_remediation_ids=MANDATORY_REMEDIATIONS,
            required_positive_evidence_abilities=(
                AbilityId.INSPECT_EVIDENCE, AbilityId.REASON_DIAGNOSIS,
                AbilityId.APPLY_TREATMENT, AbilityId.ETHICAL_PRACTICE,
            ),
            unresolved_serious_abilities=(AbilityId.APPLY_TREATMENT, AbilityId.ETHICAL_PRACTICE),
            retake_requires_remediation=True,
        ))

    def ensure(self, player_id: str) -> PermissionState:
        self.store.load_player(player_id)
        try:
            return self.store.load_permission_state(player_id)
        except StateNotFoundError:
            event = PermissionStateInitialized(
                sequence=1, player_id=player_id, occurred_at=self.clock.now(),
                initial_stage=R4TeachingStage.PROBATIONARY,
            )
            state = self.replayer.replay((event,))
            self.store.save_permission_state(state)
            return state

    def reconcile(self, player_id: str) -> PermissionState:
        state = self.ensure(player_id)
        apprenticeship = self.store.load_apprenticeship(player_id)
        try:
            plan = self.store.load_teaching_plan(player_id)
        except StateNotFoundError:
            return state
        if PermissionLevel.APPRENTICE not in state.permissions:
            state = self._append(state, PermissionGranted(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                permission=PermissionLevel.APPRENTICE, source_reference_id="formal_teaching_started",
            ))
        core_complete = set(CORE_LESSONS).issubset(plan.completed_core_lessons)
        if core_complete and state.teaching_stage is R4TeachingStage.PROBATIONARY:
            state = self._append(state, TeachingStageAdvanced(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                stage_before=state.teaching_stage, stage_after=R4TeachingStage.APPRENTICE,
                reason_code="three_core_lessons_complete",
            ))
        eligible = core_complete and not plan.unresolved_improvement_areas
        latest = {}
        for evidence in apprenticeship.evidence_history:
            latest[evidence.ability_id] = evidence
        eligible = eligible and all(
            ability in latest and latest[ability].polarity is EvidencePolarity.DEMONSTRATED
            for ability in self.eligibility_policy.required_positive_evidence_abilities
        )
        eligible = eligible and not any(
            latest.get(ability) is not None
            and latest[ability].polarity is EvidencePolarity.NEEDS_IMPROVEMENT
            for ability in self.eligibility_policy.unresolved_serious_abilities
        )
        progression=ProgressionPolicy.load_default();config=progression.config
        minimum=next(x.minimum_proficiency for x in config.ability_levels if x.level is config.exam_minimum_level)
        competent=next(x.minimum_proficiency for x in config.ability_levels if x.level.value=="competent")
        eligible=eligible and all(apprenticeship.abilities[x].unlocked and apprenticeship.abilities[x].proficiency>=minimum for x in config.exam_required_abilities)
        eligible=eligible and sum(apprenticeship.abilities[x].proficiency>=competent for x in config.exam_required_abilities)>=config.exam_minimum_competent_count
        if eligible and state.teaching_stage is R4TeachingStage.APPRENTICE:
            state = self._append(state, TeachingStageAdvanced(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                stage_before=state.teaching_stage, stage_after=R4TeachingStage.EXAM_CANDIDATE,
                reason_code="exam_requirements_met",
            ))
        if eligible and not state.exam_eligible and state.passed_exam_attempt_id is None:
            state = self._append(state, ExamEligibilityGranted(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            ))
        elif not eligible and state.exam_eligible:
            state = self._append(state, ExamEligibilityRevoked(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                reason_code="requirements_no_longer_met",
            ))
        self.store.save_permission_state(state)
        return state

    def grant_exam_pass(self, player_id: str, attempt_id: str) -> PermissionState:
        state = self.reconcile(player_id)
        if state.passed_exam_attempt_id is not None:
            return state
        if state.teaching_stage is not R4TeachingStage.EXAM_CANDIDATE:
            raise PermissionAccessError("exam pass cannot be applied in current stage")
        state = self._append(state, InnerDiscipleStatusGranted(
            sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            exam_attempt_id=attempt_id,
        ))
        state = self._append(state, TeachingStageAdvanced(
            sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            stage_before=R4TeachingStage.EXAM_CANDIDATE,
            stage_after=R4TeachingStage.INNER_DISCIPLE, reason_code="formal_exam_passed",
        ))
        state = self._append(state, PermissionGranted(
            sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            permission=PermissionLevel.INNER_DISCIPLE, source_reference_id=attempt_id,
        ))
        state = self._append(state, ExamRecognitionGranted(
            sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            exam_attempt_id=attempt_id, delta=2,
        ))
        if state.exam_eligible:
            state = self._append(state, ExamEligibilityRevoked(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                reason_code="exam_already_passed",
            ))
        self.store.save_permission_state(state)
        return state

    def public_view(self, player_id: str) -> PermissionPublicView:
        state = self.reconcile(player_id)
        apprenticeship = self.store.load_apprenticeship(player_id)
        return PermissionPublicView(
            player_id=player_id, teaching_stage=state.teaching_stage,
            exam_eligible=state.exam_eligible,
            permissions=tuple(sorted(state.permissions, key=lambda item: list(PermissionLevel).index(item))),
            unlocked_knowledge_ids=tuple(sorted(state.unlocked_knowledge_ids)),
            granted_inheritance_ids=tuple(sorted(state.granted_inheritance_ids)),
            effective_recognition=apprenticeship.relationship.recognition + state.exam_recognition_bonus,
            revision=state.revision,
        )

    def require(self, player_id: str, permission: PermissionLevel) -> PermissionState:
        state = self.reconcile(player_id)
        if permission is PermissionLevel.MENTOR_SECRET or permission not in state.permissions:
            raise PermissionAccessError("requested knowledge is not available")
        return state

    def _append(self, state: PermissionState, event: PermissionEvent) -> PermissionState:
        return self.replayer.replay((*state.events, event))
