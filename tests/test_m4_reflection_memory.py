import json
from datetime import datetime, timezone

import pytest

from xuanyi_npc.application import (
    AgentContextFilter,
    BasicCosineMemoryRetriever,
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalService,
    MemoryIndexService,
)
from xuanyi_npc.application.game_npc_memory import GameNPCMemoryRetrievalConfig
from xuanyi_npc.application.reflection import ReflectionProposalValidationError
from xuanyi_npc.application.reflection_memory import (
    ReflectionMemoryCandidateBuilder,
    ReflectionMemoryConsolidationService,
    ReflectionMemoryWritePolicy,
)
from xuanyi_npc.domain import CaseSessionState
from xuanyi_npc.domain.cooperative_memory import (
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
)
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.reflection import (
    ApplicabilityScope,
    ApplicabilityScopeType,
    EvidenceRef,
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionEvidenceBundle,
    ReflectionProposal,
    ReflectionTrigger,
    ReflectionTriggerType,
    ReusableLessonProposal,
    ReusableLessonType,
)
from xuanyi_npc.domain.reflection_memory import ReflectionMemoryWriteOutcome
from xuanyi_npc.memory import (
    DeterministicFakeEmbedding,
    MemoryRetrievalConfig,
)
from xuanyi_npc.storage import SQLiteMemoryRepository


NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def trigger() -> ReflectionTrigger:
    return ReflectionTrigger.create(
        trigger_type=ReflectionTriggerType.EPISODE_COMPLETED,
        episode_id="episode_reflection_source",
        case_id="old_paper_umbrella",
        lifecycle_event_id="case_completion_9",
        reason="The public completion assessment is available.",
    )


def evidence(kind: EvidenceRefType, ref_id: str, summary: str) -> EvidenceRef:
    return EvidenceRef(
        ref_type=kind,
        ref_id=ref_id,
        episode_id=trigger().episode_id,
        case_id=trigger().case_id,
        public_summary=summary,
    )


OUTCOME = evidence(
    EvidenceRefType.TOOL_OUTCOME,
    "outcome_public_1",
    "Questioning before treatment exposed a public cough clue and avoided a premature intervention.",
)
ASSESSMENT = evidence(
    EvidenceRefType.ASSESSMENT,
    "assessment_public_1",
    "The completed episode assessment confirmed that evidence was gathered before intervention.",
)


def scope(*, tags=("question_before_treatment",)) -> ApplicabilityScope:
    return ApplicabilityScope(
        scope_type=ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
        public_pattern_tags=tags,
        limitation="Only apply when the same public evidence gap and reversible question are available.",
    )


def outcome_lesson(
    *,
    summary: str = OUTCOME.public_summary,
    confidence: ReflectionConfidence = ReflectionConfidence.HIGH,
    lesson_scope: ApplicabilityScope | None = None,
    memory_type: MemoryType = MemoryType.LEARNING,
    refs=(OUTCOME, ASSESSMENT),
) -> ReusableLessonProposal:
    return ReusableLessonProposal(
        lesson_type=ReusableLessonType.OUTCOME,
        public_safe_summary=summary,
        applicability_scope=lesson_scope or scope(),
        evidence_refs=refs,
        confidence=confidence,
        proposed_memory_type=memory_type,
    )


def proposal(*lessons: ReusableLessonProposal) -> ReflectionProposal:
    return ReflectionProposal(
        proposal_id="reflection_proposal_1",
        trigger_id=trigger().trigger_id,
        reusable_lesson_candidates=lessons,
        overall_confidence=ReflectionConfidence.HIGH,
    )


def bundle(*refs: EvidenceRef) -> ReflectionEvidenceBundle:
    return ReflectionEvidenceBundle(
        episode_id=trigger().episode_id,
        case_id=trigger().case_id,
        trigger=trigger(),
        evidence_refs=refs,
    )


def repository_at(path) -> SQLiteMemoryRepository:
    repository = SQLiteMemoryRepository(path, clock=lambda: NOW)
    repository.initialize()
    return repository


def consolidate(repository, lesson=None):
    value = proposal(lesson or outcome_lesson())
    result = ReflectionMemoryConsolidationService(
        repository=repository,
        clock=lambda: NOW,
    ).consolidate(
        player_id="player_apprentice",
        proposal=value,
        evidence_bundle=bundle(*value.reusable_lesson_candidates[0].evidence_refs),
    )
    return value, result


def test_valid_outcome_grounded_lesson_writes_existing_repository(tmp_path) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    _, result = consolidate(repository)
    assert result.decisions[0].outcome is ReflectionMemoryWriteOutcome.WRITE_NEW
    assert len(result.written_memory_ids) == 1
    record = repository.get_memory(
        player_id="player_apprentice", memory_id=result.written_memory_ids[0]
    )
    assert record.content == OUTCOME.public_summary
    receipt = repository.get_source_receipt(
        player_id="player_apprentice",
        source_event_id=record.source_event_id,
        projection_version=record.projection_version,
        projection_ordinal=record.projection_ordinal,
    )
    assert receipt.public_payload.reason_code == "reflection_generated"
    assert trigger().trigger_id in receipt.public_payload.ability_ids


def test_persisted_reflection_memory_is_retrievable_by_m3(
    tmp_path, case_definition, qualified_player_state
) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    _, result = consolidate(repository)
    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter, clock=lambda: NOW).index_player(
        player_id="player_apprentice"
    )
    observation = AgentContextFilter().case_observation(
        case_definition,
        qualified_player_state,
        CaseSessionState(
            session_id="future_episode",
            case_id=case_definition.case_id,
            player_id=qualified_player_state.player_id,
        ),
    )
    service = GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=adapter),
        retrieval_config=MemoryRetrievalConfig(
            top_k=10,
            min_similarity=-1.0,
            embedding_space_id=adapter.embedding_space_id,
            query_template_version="memory_query_v1",
        ),
        projection_policy=GameNPCMemoryProjectionPolicy(
            repository=repository, clock=lambda: NOW
        ),
        projection_config=GameNPCMemoryRetrievalConfig(min_relevance=-1.0),
    )
    context = service.retrieve(
        turn_id="future_turn",
        player_id="player_apprentice",
        current_session_id="future_episode",
        observation=observation,
    )
    assert result.written_memory_ids[0] in context.selected_memory_ids
    assert context.memories[0].public_summary == OUTCOME.public_summary


def test_same_trigger_rerun_is_idempotent_and_duplicate_is_skipped(tmp_path) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    first_proposal, first = consolidate(repository)
    second_proposal, second = consolidate(repository)
    assert first_proposal == second_proposal
    assert first.candidate_ids == second.candidate_ids
    assert second.written_memory_ids == ()
    assert second.decisions[0].outcome is ReflectionMemoryWriteOutcome.SKIP_DUPLICATE
    assert len(repository.list_memories(player_id="player_apprentice")) == 1


def test_weak_evidence_and_broad_scope_are_rejected(tmp_path) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    _, weak = consolidate(
        repository,
        outcome_lesson(confidence=ReflectionConfidence.LOW),
    )
    assert weak.decisions[0].outcome is ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE

    broad = outcome_lesson(
        lesson_scope=scope(tags=("one", "two", "three", "four"))
    )
    _, broad_result = consolidate(repository, broad)
    assert broad_result.decisions[0].outcome is ReflectionMemoryWriteOutcome.REJECT_SCOPE_TOO_BROAD


def test_player_belief_cannot_be_consolidated_as_fact(tmp_path) -> None:
    belief = evidence(
        EvidenceRefType.PLAYER_CONTRIBUTION,
        "contribution_1",
        "I believe this diagnosis is certainly correct.",
    )
    evaluation = evidence(
        EvidenceRefType.CONTRIBUTION_EVALUATION,
        "contribution_eval_1",
        "The NPC requested more public evidence before accepting the claim.",
    )
    lesson = ReusableLessonProposal(
        lesson_type=ReusableLessonType.COOPERATION,
        public_safe_summary=belief.public_summary,
        applicability_scope=ApplicabilityScope(
            scope_type=ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR,
            public_pattern_tags=("premature_certainty",),
            limitation="Only for the same public cooperation pattern.",
        ),
        evidence_refs=(belief, evaluation, ASSESSMENT),
        confidence=ReflectionConfidence.HIGH,
        proposed_memory_type=MemoryType.LEARNING,
    )
    repository = repository_at(tmp_path / "memory.sqlite3")
    value = proposal(lesson)
    result = ReflectionMemoryConsolidationService(repository=repository).consolidate(
        player_id="player_apprentice",
        proposal=value,
        evidence_bundle=bundle(belief, evaluation, ASSESSMENT),
    )
    assert result.decisions[0].outcome is ReflectionMemoryWriteOutcome.REJECT_UNSAFE
    assert repository.list_memories(player_id="player_apprentice") == ()


def memory_trace(*, accepted: bool) -> EvidenceRef:
    return evidence(
        EvidenceRefType.MEMORY_USAGE_TRACE,
        "memory_trace_1",
        json.dumps(
            {
                "selected_memory_ids": ["memory_old"],
                "accepted_used_memory_ids": ["memory_old"] if accepted else [],
                "attribution_status": (
                    MemoryUsageAttributionStatus.ACCEPTED.value
                    if accepted
                    else MemoryUsageAttributionStatus.DECLARED_ONLY.value
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def test_selected_but_unused_memory_helpfulness_never_becomes_candidate() -> None:
    selected_only = memory_trace(accepted=False)
    lesson = ReusableLessonProposal(
        lesson_type=ReusableLessonType.MEMORY_HELPFULNESS,
        public_safe_summary=ASSESSMENT.public_summary,
        applicability_scope=scope(),
        evidence_refs=(selected_only, ASSESSMENT),
        confidence=ReflectionConfidence.HIGH,
        proposed_memory_type=MemoryType.LEARNING,
    )
    with pytest.raises(ReflectionProposalValidationError, match="selected-but-unused"):
        ReflectionMemoryCandidateBuilder().build(
            player_id="player_apprentice",
            proposal=proposal(lesson),
            evidence_bundle=bundle(selected_only, ASSESSMENT),
        )


def test_accepted_memory_usage_with_outcome_builds_bounded_candidate() -> None:
    accepted = memory_trace(accepted=True)
    lesson = ReusableLessonProposal(
        lesson_type=ReusableLessonType.MEMORY_HELPFULNESS,
        public_safe_summary=ASSESSMENT.public_summary,
        applicability_scope=scope(),
        evidence_refs=(accepted, ASSESSMENT),
        confidence=ReflectionConfidence.HIGH,
        proposed_memory_type=MemoryType.LEARNING,
    )
    candidates = ReflectionMemoryCandidateBuilder().build(
        player_id="player_apprentice",
        proposal=proposal(lesson),
        evidence_bundle=bundle(accepted, ASSESSMENT),
    )
    assert len(candidates) == 1
    assert candidates[0].source == "reflection_generated"
    assert len(candidates[0].evidence_refs) == 2


def test_candidate_count_is_bounded_and_player_ownership_is_enforced() -> None:
    unique_outcomes = tuple(
        evidence(
            EvidenceRefType.TOOL_OUTCOME,
            f"bounded_outcome_{index}",
            f"Public outcome {index} supplied sufficiently specific reusable evidence for a bounded lesson.",
        )
        for index in range(4)
    )
    lessons = tuple(
        outcome_lesson(summary=item.public_summary, refs=(item, ASSESSMENT))
        for item in unique_outcomes
    )
    candidates = ReflectionMemoryCandidateBuilder().build(
        player_id="player_apprentice",
        proposal=proposal(*lessons),
        evidence_bundle=bundle(*unique_outcomes, ASSESSMENT),
    )
    assert len(candidates) == 3
    decision = ReflectionMemoryWritePolicy().evaluate(
        candidates[0],
        player_id="player_other",
        active_memories=(),
    )
    assert decision.outcome is ReflectionMemoryWriteOutcome.REJECT_OWNERSHIP


def test_conflicting_active_memory_is_rejected_without_supersede(tmp_path) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    _, first = consolidate(repository)
    active_id = first.written_memory_ids[0]
    alternative_outcome = evidence(
        EvidenceRefType.TOOL_OUTCOME,
        "outcome_public_2",
        "Inspecting the public object first exposed a useful trace before questioning.",
    )
    alternative = outcome_lesson(
        summary=alternative_outcome.public_summary,
        refs=(alternative_outcome, ASSESSMENT),
    )
    value = ReflectionProposal(
        proposal_id="reflection_proposal_2",
        trigger_id=trigger().trigger_id,
        reusable_lesson_candidates=(alternative,),
        overall_confidence=ReflectionConfidence.HIGH,
    )
    result = ReflectionMemoryConsolidationService(repository=repository).consolidate(
        player_id="player_apprentice",
        proposal=value,
        evidence_bundle=bundle(alternative_outcome, ASSESSMENT),
        conflicting_memory_ids=frozenset({active_id}),
    )
    assert result.decisions[0].outcome is ReflectionMemoryWriteOutcome.REJECT_CONFLICT
    original = repository.get_memory(
        player_id="player_apprentice", memory_id=active_id
    )
    assert original.supersedes_memory_id is None


def test_unsupported_claim_is_rejected_before_repository_write(tmp_path) -> None:
    unsupported = outcome_lesson(summary="The hidden diagnosis was correct.")
    repository = repository_at(tmp_path / "memory.sqlite3")
    with pytest.raises(ReflectionProposalValidationError, match="not supported"):
        consolidate(repository, unsupported)
    assert repository.list_memories(player_id="player_apprentice") == ()


class FailingRepository:
    def list_memories(self, *, player_id, include_inactive=True):
        return ()

    def write_projection(self, source, memory):
        raise RuntimeError("injected repository failure")


def test_repository_failure_does_not_claim_success() -> None:
    _, result = consolidate(FailingRepository())
    assert result.written_memory_ids == ()
    assert result.decisions[0].outcome is ReflectionMemoryWriteOutcome.REPOSITORY_FAILURE


def test_findings_are_not_automatically_consolidated(tmp_path) -> None:
    repository = repository_at(tmp_path / "memory.sqlite3")
    value = ReflectionProposal(
        proposal_id="reflection_findings_only",
        trigger_id=trigger().trigger_id,
        findings=(),
        reusable_lesson_candidates=(),
        overall_confidence=ReflectionConfidence.MEDIUM,
    )
    result = ReflectionMemoryConsolidationService(repository=repository).consolidate(
        player_id="player_apprentice",
        proposal=value,
        evidence_bundle=bundle(ASSESSMENT),
    )
    assert result.candidate_ids == ()
    assert result.written_memory_ids == ()
