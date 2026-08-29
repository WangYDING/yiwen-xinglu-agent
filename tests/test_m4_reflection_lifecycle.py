from datetime import datetime, timezone
import json
import sqlite3

import pytest

from xuanyi_npc.agents.deepseek import (
    DeepSeekEmptyContentError,
    DeepSeekProviderError,
    DeepSeekTruncatedOutputError,
)
from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.agents.model_usage import ModelUsage
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


class FailingAdapter:
    def __init__(self, error):
        self.error = error
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        raise self.error


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
                    public_pattern_tags=(outcome_ref.ref_id,),
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
    assert first.generation_attempt_count == 1
    assert first.repair_attempted is False
    assert first.generation_failure_code is None
    assert replay.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
    assert replay.reflection_attempt_count == 0
    assert replay.written_memory_ids == ()
    assert len(adapter.requests) == 1


def test_restart_replay_uses_persisted_receipt_without_llm_call(tmp_path):
    trigger = lifecycle_trigger()
    outcome, assessment, proposal = public_inputs(trigger)
    repository = repository_at(tmp_path)
    first_adapter = ScriptedAdapter(proposal.model_dump_json())
    first = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(first_adapter),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    replay_adapter = ScriptedAdapter()
    replay = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(replay_adapter),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert first.status is ReflectionLifecycleStatus.COMPLETED
    assert replay.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
    assert replay.reflection_attempt_count == 0
    assert replay_adapter.requests == []
    assert len(repository.list_memories(player_id="player_lifecycle")) == 1


def test_restart_receipt_preserves_generation_failure_telemetry(tmp_path):
    trigger = lifecycle_trigger(ReflectionTriggerType.GOAL_COMPLETED)
    outcome, assessment, _ = public_inputs(trigger)
    repository = repository_at(tmp_path)
    usage = ModelUsage(
        provider_model="DeepSeek-V4-Flash-0731",
        input_tokens=1900,
        output_tokens=512,
        cache_hit_input_tokens=0,
        cache_miss_input_tokens=1900,
        reasoning_tokens=0,
        latency_ms=250.0,
        estimated_cost="0.001",
        cost_currency="CNY",
        provider_request_id="request_reflection_truncated",
    )
    error = DeepSeekTruncatedOutputError("truncated", usage=usage)
    error.failure_stage = "provider_finish"
    error.finish_reason = "length"
    error.configured_max_output_tokens = 512
    first_adapter = FailingAdapter(error)
    first = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(first_adapter),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )

    with sqlite3.connect(repository.database_path) as connection:
        stored = json.loads(
            connection.execute(
                "SELECT result_json FROM reflection_lifecycle_receipts WHERE trigger_id = ?",
                (trigger.trigger_id,),
            ).fetchone()[0]
        )

    assert first.generation_failure_stage == "provider_finish"
    assert stored["generation_failure_code"] == "deepseek_output_truncated"
    assert stored["generation_exception_class"] == "DeepSeekTruncatedOutputError"
    assert stored["finish_reason"] == "length"
    assert stored["provider_request_id"] == "request_reflection_truncated"
    assert stored["input_tokens"] == 1900
    assert stored["output_tokens"] == 512
    assert stored["configured_max_output_tokens"] == 512
    assert stored["generation_attempt_count"] == 1
    assert stored["repair_attempted"] is False

    replay = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(ScriptedAdapter()),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert replay.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
    assert replay.generation_failure_code == "deepseek_output_truncated"
    assert replay.provider_request_id == "request_reflection_truncated"


@pytest.mark.parametrize(
    ("error_type", "error_code", "stage", "finish_reason"),
    (
        (DeepSeekEmptyContentError, "deepseek_empty_content", "provider_content", "stop"),
        (DeepSeekProviderError, "deepseek_provider_error", "provider_finish", "content_filter"),
    ),
)
def test_other_post_settlement_failure_codes_are_persisted(
    tmp_path, error_type, error_code, stage, finish_reason
):
    trigger = lifecycle_trigger(ReflectionTriggerType.GOAL_BLOCKED)
    outcome, assessment, _ = public_inputs(trigger)
    repository = repository_at(tmp_path)
    usage = ModelUsage(
        provider_model="DeepSeek-V4-Flash-0731",
        input_tokens=800,
        output_tokens=0,
        cache_hit_input_tokens=0,
        cache_miss_input_tokens=800,
        reasoning_tokens=0,
        latency_ms=100.0,
        estimated_cost="0.0001",
        cost_currency="CNY",
        provider_request_id="request_other_failure",
    )
    error = error_type("post-settlement failure", usage=usage)
    error.failure_stage = stage
    error.finish_reason = finish_reason
    error.configured_max_output_tokens = 512
    ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(FailingAdapter(error)),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    with sqlite3.connect(repository.database_path) as connection:
        stored = json.loads(
            connection.execute(
                "SELECT result_json FROM reflection_lifecycle_receipts WHERE trigger_id = ?",
                (trigger.trigger_id,),
            ).fetchone()[0]
        )
    assert stored["generation_failure_code"] == error_code
    assert stored["generation_failure_stage"] == stage
    assert stored["finish_reason"] == finish_reason


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
    assert result.repair_attempted is True
    assert result.repair_succeeded is False
    assert result.repaired is False
    assert result.written_memory_ids == ()
    assert repository.list_memories(player_id="player_lifecycle") == ()


def test_restart_receipt_preserves_both_validation_attempts(tmp_path):
    trigger = lifecycle_trigger(ReflectionTriggerType.GOAL_COMPLETED)
    outcome, assessment, valid = public_inputs(trigger)
    invalid = valid.model_copy(update={"trigger_id": "rtr_wrong"})
    lesson = valid.reusable_lesson_candidates[0]
    invalid_scope = lesson.applicability_scope.model_copy(
        update={"public_pattern_tags": ("invented_tag",)}
    )
    repair_lesson = lesson.model_copy(update={"applicability_scope": invalid_scope})
    repair_invalid = valid.model_copy(update={"reusable_lesson_candidates": (repair_lesson,)})
    repository = repository_at(tmp_path)
    first = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(
            ScriptedAdapter(invalid.model_dump_json(), repair_invalid.model_dump_json())
        ),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    replay = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(ScriptedAdapter()),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository),
        receipt_repository=repository,
    ).process(
        trigger=trigger,
        player_id="player_lifecycle",
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert first.repair_attempted is True
    assert first.repair_succeeded is False
    assert len(first.generation_attempts) == 2
    assert first.generation_attempts[0].failure_code == "trigger_id_mismatch"
    assert first.generation_attempts[1].failure_code == "lesson_scope_invalid"
    assert replay.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
    assert replay.generation_attempts == first.generation_attempts


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
