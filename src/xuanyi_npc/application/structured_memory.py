"""R3 structured memory projection and non-vector mentor selection."""

from xuanyi_npc.domain.apprenticeship import AbilityId
from xuanyi_npc.domain.assessment import AssessmentReport
from xuanyi_npc.domain.curriculum import (
    StructuredMemorySourceType,
    StructuredTeachingMemoryType,
)
from xuanyi_npc.domain.structured_memory import RetrievedStructuredMemory
from xuanyi_npc.memory.contracts import StructuredTeachingPublicPayload
from xuanyi_npc.memory.projection import DeterministicMemoryProjector
from xuanyi_npc.storage.sqlite_memory import SQLiteMemoryRepository
from xuanyi_npc.application.public_presentation import PUBLIC_PRESENTATION


STRUCTURED_PROJECTION_VERSION = "structured_teaching_memory_v1"


class StructuredTeachingMemoryProjector:
    def __init__(self, repository: SQLiteMemoryRepository) -> None:
        self.repository = repository

    def project_assessment(self, report: AssessmentReport, *, occurred_at) -> tuple[str, ...]:
        facts = [
            (
                StructuredTeachingMemoryType.CASE_EXPERIENCE,
                StructuredMemorySourceType.CASE_COMPLETION,
                f"你曾完成一则病例，公开结局为{PUBLIC_PRESENTATION.name('outcome', report.outcome.value)}。",
                "prior_case_completion",
                (),
            ),
            (
                StructuredTeachingMemoryType.MENTOR_FEEDBACK,
                StructuredMemorySourceType.ASSESSMENT,
                f"结构化师评记录：已完成 {len(report.completed_objectives)} 项目标，仍有 {len(report.missed_objectives)} 项待改进。",
                "prior_structured_assessment",
                tuple(item.value for item in report.improvement_abilities),
            ),
        ]
        facts.extend(
            (
                StructuredTeachingMemoryType.ABILITY_STRENGTH,
                StructuredMemorySourceType.ABILITY_EVIDENCE,
                f"你此前在{PUBLIC_PRESENTATION.name('ability', ability.value)}方面有已提交的良好表现。",
                "demonstrated_ability_history",
                (ability.value,),
            )
            for ability in report.demonstrated_abilities
        )
        facts.extend(
            (
                StructuredTeachingMemoryType.LEARNING_PATTERN,
                StructuredMemorySourceType.ABILITY_EVIDENCE,
                f"你此前在{PUBLIC_PRESENTATION.name('ability', ability.value)}方面仍有已提交的改进证据。",
                "unresolved_ability_history",
                (ability.value,),
            )
            for ability in report.improvement_abilities
        )
        memory_ids = []
        for ordinal, (memory_type, source_type, summary, reason, abilities) in enumerate(facts):
            projector = DeterministicMemoryProjector(
                projection_version=STRUCTURED_PROJECTION_VERSION,
                projection_ordinal=ordinal,
            )
            source, memory = projector.project_structured_teaching_fact(
                player_id=report.player_id,
                source_session_id=report.case_session_id,
                source_sequence=report.source_revision,
                source_revision=report.source_revision,
                occurred_at=occurred_at,
                structured_memory_type=memory_type,
                source_type=source_type,
                source_reference_id=report.assessment_id,
                public_summary=summary,
                reason_code=reason,
                source_case_id=report.case_id,
                lesson_id=report.lesson_id,
                ability_ids=abilities,
            )
            memory_ids.append(self.repository.write_projection(source, memory).memory_id)
        return tuple(memory_ids)

    def project_remediation(
        self,
        *,
        player_id: str,
        remediation_id: str,
        attempt_id: str,
        occurred_at,
        ability_ids: tuple[AbilityId, ...],
    ) -> str:
        projector = DeterministicMemoryProjector(
            projection_version=STRUCTURED_PROJECTION_VERSION,
            projection_ordinal=0,
        )
        source, memory = projector.project_structured_teaching_fact(
            player_id=player_id,
            source_session_id=attempt_id,
            source_sequence=1,
            source_revision=1,
            occurred_at=occurred_at,
            structured_memory_type=StructuredTeachingMemoryType.REMEDIATION_HISTORY,
            source_type=StructuredMemorySourceType.REMEDIATION_RESULT,
            source_reference_id=attempt_id,
            public_summary=f"你已完成{PUBLIC_PRESENTATION.name('remediation', remediation_id)}；后续病例表现才会形成新的能力证据。",
            reason_code="completed_remediation_history",
            ability_ids=tuple(item.value for item in ability_ids),
        )
        return self.repository.write_projection(source, memory).memory_id

    def project_r4_event(
        self, *, player_id: str, source_session_id: str, source_sequence: int,
        source_revision: int, occurred_at, event_kind: str,
        source_reference_id: str, public_summary: str, reason_code: str,
    ) -> str:
        """Project only a caller-supplied public summary from an already committed R4 event."""
        mapping = {
            "exam": (StructuredTeachingMemoryType.EXAM_EVENT, StructuredMemorySourceType.EXAM_EVENT),
            "permission": (StructuredTeachingMemoryType.PERMISSION_EVENT, StructuredMemorySourceType.PERMISSION_EVENT),
            "inheritance": (StructuredTeachingMemoryType.INHERITANCE_EVENT, StructuredMemorySourceType.INHERITANCE_EVENT),
        }
        if event_kind not in mapping:
            raise ValueError("unsupported R4 structured memory event")
        memory_type, source_type = mapping[event_kind]
        projector = DeterministicMemoryProjector(
            projection_version=STRUCTURED_PROJECTION_VERSION,
            projection_ordinal=0,
        )
        source, memory = projector.project_structured_teaching_fact(
            player_id=player_id, source_session_id=source_session_id,
            source_sequence=source_sequence, source_revision=source_revision,
            occurred_at=occurred_at, structured_memory_type=memory_type,
            source_type=source_type, source_reference_id=source_reference_id,
            public_summary=public_summary, reason_code=reason_code,
        )
        return self.repository.write_projection(source, memory).memory_id


class StructuredMentorMemorySelector:
    """Select trusted records without embeddings, similarity, BGE, or model judgment."""

    def __init__(self, repository: SQLiteMemoryRepository) -> None:
        self.repository = repository

    def select(
        self,
        *,
        player_id: str,
        current_lesson_id: str,
        current_case_id: str,
        target_ability_ids: tuple[AbilityId, ...],
        unresolved_improvement_areas: tuple[AbilityId, ...],
        current_teaching_stage: str,
        excluded_episode_id: str,
        limit: int = 3,
    ) -> tuple[RetrievedStructuredMemory, ...]:
        del current_teaching_stage
        targets = {item.value for item in target_ability_ids}
        unresolved = {item.value for item in unresolved_improvement_areas}
        candidates = []
        for record in self.repository.list_memories(player_id=player_id, include_inactive=False):
            if record.source_session_id == excluded_episode_id:
                continue
            try:
                receipt = self.repository.get_source_receipt(
                    player_id=player_id,
                    source_event_id=record.source_event_id,
                    projection_version=record.projection_version,
                    projection_ordinal=record.projection_ordinal,
                )
            except Exception:
                continue
            payload = receipt.public_payload
            if not isinstance(payload, StructuredTeachingPublicPayload):
                continue
            abilities = set(payload.ability_ids)
            priority = 0
            reason_code = payload.reason_code
            if (
                payload.structured_memory_type is StructuredTeachingMemoryType.LEARNING_PATTERN
                and abilities.intersection(unresolved)
            ):
                priority, reason_code = 500, "unresolved_learning_issue"
            elif (
                payload.structured_memory_type is StructuredTeachingMemoryType.MENTOR_FEEDBACK
                and payload.lesson_id == current_lesson_id
            ):
                priority, reason_code = 400, "course_mentor_feedback"
            elif (
                payload.structured_memory_type is StructuredTeachingMemoryType.CASE_EXPERIENCE
                and payload.source_case_id != current_case_id
            ):
                priority, reason_code = 300, "similar_case_experience"
            elif (
                payload.structured_memory_type is StructuredTeachingMemoryType.ABILITY_STRENGTH
                and (not targets or abilities.intersection(targets))
            ):
                priority, reason_code = 200, "related_ability_strength"
            elif payload.structured_memory_type is StructuredTeachingMemoryType.REMEDIATION_HISTORY:
                priority, reason_code = 100, "recent_remediation"
            elif payload.structured_memory_type is StructuredTeachingMemoryType.EXAM_EVENT:
                priority, reason_code = 150, "recent_exam_event"
            elif payload.structured_memory_type is StructuredTeachingMemoryType.PERMISSION_EVENT:
                priority, reason_code = 140, "recent_permission_event"
            elif payload.structured_memory_type is StructuredTeachingMemoryType.INHERITANCE_EVENT:
                priority, reason_code = 130, "recent_inheritance_event"
            if priority:
                candidates.append(
                    (
                        priority,
                        RetrievedStructuredMemory(
                            memory_id=record.memory_id,
                            memory_type=payload.structured_memory_type,
                            public_summary=PUBLIC_PRESENTATION.sanitize_legacy_text(payload.public_summary),
                            source_case_id=payload.source_case_id,
                            occurred_at=record.occurred_at,
                            reason_code=reason_code,
                        ),
                    )
                )
        candidates.sort(key=lambda item: item[1].memory_id)
        candidates.sort(key=lambda item: item[1].occurred_at, reverse=True)
        candidates.sort(key=lambda item: item[0], reverse=True)
        return tuple(item[1] for item in candidates[: max(0, min(limit, 3))])
