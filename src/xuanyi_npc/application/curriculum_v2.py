"""Deterministic R5 curriculum selection over R1-R4 authority."""

from dataclasses import dataclass

from pydantic import ConfigDict

from xuanyi_npc.domain.base import DomainModel, Identifier
from xuanyi_npc.domain.clinic import CurriculumSelectionV2
from xuanyi_npc.domain.permissions import R4TeachingStage
from xuanyi_npc.resources.runtime import read_runtime_text


class CurriculumV2Recommendation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Identifier
    recommendation_id: Identifier
    reason_code: Identifier
    does_not_lock_cases: bool = True


@dataclass(frozen=True)
class CurriculumV2Selector:
    def __post_init__(self) -> None:
        policy = CurriculumSelectionV2.model_validate_json(
            read_runtime_text("curriculum/curriculum_selection_v2.json")
        )
        object.__setattr__(self, "policy", policy)

    def select(self, *, plan, permission, completed_case_ids: frozenset[str]) -> CurriculumV2Recommendation:
        if plan.unresolved_improvement_areas and plan.current_recommendation is not None:
            return self._result("remediation", plan.current_recommendation.recommendation_id, "r3_remediation_unresolved")
        for lesson_id in self.policy.foundation_lesson_order:
            if lesson_id not in plan.completed_core_lessons:
                return self._result("core_lesson", lesson_id, "foundation_lesson_incomplete")
        if permission.passed_exam_attempt_id is None:
            return self._result("exam", "foundational_xuanyi_exam_v1", "exam_not_passed")
        advanced = self.policy.advanced_lesson_order
        if advanced[0] not in plan.completed_core_lessons:
            return self._result("advanced_lesson", advanced[0], "inner_disciple_lantern_incomplete")
        if advanced[1] not in plan.completed_core_lessons:
            return self._result("advanced_lesson", advanced[1], "inner_disciple_ferry_incomplete")
        if "trace_vow_restore_v1" not in permission.granted_inheritance_ids:
            return self._result("inheritance", "trace_vow_restore_v1", "inheritance_missing_shrine_visible")
        if advanced[2] not in plan.completed_core_lessons:
            return self._result("advanced_lesson", advanced[2], "inheritance_granted_shrine_incomplete")
        return self._result("complete", self.policy.completion_recommendation_id, "six_lessons_complete")

    @staticmethod
    def _result(kind, recommendation_id, reason):
        return CurriculumV2Recommendation(
            kind=kind, recommendation_id=recommendation_id,
            reason_code=reason, does_not_lock_cases=True,
        )
