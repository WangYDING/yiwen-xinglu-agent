from datetime import datetime, timezone

from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.application.reflection import (
    PublicAssessmentEvidence,
    PublicOutcomeEvidence,
    ReflectionEvidenceBuilder,
    ReflectionProposalGenerator,
)
from xuanyi_npc.application.reflection_lifecycle import ReflectionLifecycleService
from xuanyi_npc.application.reflection_memory import ReflectionMemoryConsolidationService
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.reflection import (
    ApplicabilityScope,
    ApplicabilityScopeType,
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionProposal,
    ReflectionTrigger,
    ReflectionTriggerType,
    ReusableLessonProposal,
    ReusableLessonType,
)
from xuanyi_npc.domain.reflection_lifecycle import ReflectionLifecycleStatus
from xuanyi_npc.domain.reflection_memory import ReflectionMemoryWriteOutcome
from xuanyi_npc.evaluation import summarize_reflection_lifecycle
from xuanyi_npc.storage import SQLiteMemoryRepository


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class ScriptedAdapter:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(content=self.outputs.pop(0))


def lifecycle_trigger(kind=ReflectionTriggerType.EPISODE_COMPLETED):
    return ReflectionTrigger.create(
        trigger_type=kind,
        episode_id="episode_lifecycle",
        case_id="case_lifecycle",
        lifecycle_event_id=f"event_{kind.value}",
        reason="A deterministic lifecycle boundary was reached.",
    )


def public_inputs(trigger):
    outcome = PublicOutcomeEvidence(
        outcome_id="outcome_lifecycle",
        public_summary="Questioning first exposed a public cough clue before irreversible treatment.",
    )
    assessment = PublicAssessmentEvidence(
        assessment_id="assessment_lifecycle",
        public_summary="The public episode assessment confirmed completion after evidence gathering.",
    )
    bundle = ReflectionEvidenceBuilder().build(
        trigger, tool_outcomes=(outcome,), assessments=(assessment,)
    )
    outcome_ref = next(
        item for item in bundle.evidence_refs if item.ref_type is EvidenceRefType.TOOL_OUTCOME
    )
    assessment_ref = next(
        item for item in bundle.evidence_refs if item.ref_type is EvidenceRefType.ASSESSMENT
    )
    proposal = ReflectionProposal(
        proposal_id="proposal_lifecycle",
        trigger_id=trigger.trigger_id,
        reusable_lesson_candidates=(
            ReusableLessonProposal(
                lesson_type=ReusableLessonType.OUTCOME,
                public_safe_summary=outcome_ref.public_summary,
                applicability_scope=ApplicabilityScope(
                    scope_type=ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
                    public_pattern_tags=("question_before_treatment",),
                    limitation="Only when the same public evidence gap is present.",
                ),
                evidence_refs=(outcome_ref, assessment_ref),
                confidence=ReflectionConfidence.HIGH,
                proposed_memory_type=MemoryType.LEARNING,
            ),
        ),
        overall_confidence=ReflectionConfidence.HIGH,
    )
    return outcome, assessment, proposal


def repository_at(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3", clock=lambda: NOW)
    repository.initialize()
    return repository


def lifecycle_service(repository, adapter):
    return ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(adapter),
        consolidation_service=ReflectionMemoryConsolidationService(
            repository=repository, clock=lambda: NOW
        ),
    )


def test_lifecycle_valid_proposal_writes_and_replay_does_not_attempt_again(tmp_path):
    trigger = lifecycle_trigger()
    outcome, assessment, proposal = public_inputs(trigger)
    adapter = ScriptedAdapter(proposal.model_dump_json())
    service = lifecycle_service(repository_at(tmp_path), adapter)
    first = service.process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    replay = service.process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert first.status is ReflectionLifecycleStatus.COMPLETED
    assert first.write_decisions[0].outcome is ReflectionMemoryWriteOutcome.WRITE_NEW
    assert len(first.written_memory_ids) == 1
    assert replay.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
    assert replay.reflection_attempt_count == 0
    assert replay.written_memory_ids == ()
    assert len(adapter.requests) == 1


def test_lifecycle_invalid_repairs_once_then_writes(tmp_path):
    trigger = lifecycle_trigger(ReflectionTriggerType.GOAL_COMPLETED)
    outcome, assessment, valid = public_inputs(trigger)
    invalid = valid.model_copy(update={"trigger_id": "rtr_wrong"})
    adapter = ScriptedAdapter(invalid.model_dump_json(), valid.model_dump_json())
    result = lifecycle_service(repository_at(tmp_path), adapter).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert result.status is ReflectionLifecycleStatus.COMPLETED
    assert result.repaired is True
    assert len(adapter.requests) == 2


def test_lifecycle_failed_repair_is_safe_fallback_without_write(tmp_path):
    trigger = lifecycle_trigger()
    outcome, assessment, valid = public_inputs(trigger)
    invalid = valid.model_copy(update={"trigger_id": "rtr_wrong"})
    repository = repository_at(tmp_path)
    result = lifecycle_service(
        repository,
        ScriptedAdapter(invalid.model_dump_json(), invalid.model_dump_json()),
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert result.status is ReflectionLifecycleStatus.FALLBACK
    assert result.written_memory_ids == ()
    assert repository.list_memories(player_id="player_lifecycle") == ()


def test_weak_lesson_is_rejected_and_metrics_treat_rejection_as_auditable(tmp_path):
    trigger = lifecycle_trigger()
    outcome, assessment, proposal = public_inputs(trigger)
    weak_lesson = proposal.reusable_lesson_candidates[0].model_copy(
        update={"confidence": ReflectionConfidence.LOW}
    )
    weak = proposal.model_copy(update={"reusable_lesson_candidates": (weak_lesson,)})
    result = lifecycle_service(
        repository_at(tmp_path), ScriptedAdapter(weak.model_dump_json())
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    summary = summarize_reflection_lifecycle((result,), future_retrieval_success_count=0)
    assert result.written_memory_ids == ()
    assert result.write_decisions[0].outcome is ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE
    assert summary.eligible_trigger_count == 1
    assert summary.reflection_attempt_count == 1
    assert summary.weak_evidence_rejection_rate == 1.0
    assert summary.accepted_write_rate == 0.0
