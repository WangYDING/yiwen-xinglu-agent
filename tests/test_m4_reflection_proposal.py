import json

import pytest
from pydantic import ValidationError

from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.application.reflection import (
    PublicAssessmentEvidence,
    PublicObservationDeltaEvidence,
    PublicOutcomeEvidence,
    ReflectionEvidenceBuilder,
    ReflectionProposalGenerator,
    ReflectionProposalValidationError,
    ReflectionProposalValidator,
)
from xuanyi_npc.domain.cooperative_memory import (
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
    MemoryUsageTrace,
)
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.reflection import (
    ApplicabilityScope,
    ApplicabilityScopeType,
    EvidenceRef,
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionEvidenceBundle,
    ReflectionFinding,
    ReflectionFindingType,
    ReflectionProposal,
    ReflectionTrigger,
    ReflectionTriggerType,
    ReusableLessonProposal,
    ReusableLessonType,
)


def trigger() -> ReflectionTrigger:
    return ReflectionTrigger.create(
        trigger_type=ReflectionTriggerType.EPISODE_COMPLETED,
        episode_id="episode_m4",
        case_id="case_m4",
        lifecycle_event_id="event_episode_completed",
        reason="The public episode assessment is available.",
        turn_id="turn_9",
    )


def ref(kind: EvidenceRefType, ref_id: str, summary: str) -> EvidenceRef:
    return EvidenceRef(
        ref_type=kind,
        ref_id=ref_id,
        episode_id="episode_m4",
        case_id="case_m4",
        public_summary=summary,
    )


def bundle(*refs: EvidenceRef) -> ReflectionEvidenceBundle:
    return ReflectionEvidenceBundle(
        episode_id="episode_m4",
        case_id="case_m4",
        trigger=trigger(),
        evidence_refs=refs,
    )


def finding(
    kind: ReflectionFindingType,
    summary: str,
    *refs: EvidenceRef,
) -> ReflectionFinding:
    return ReflectionFinding(
        finding_type=kind,
        public_summary=summary,
        evidence_refs=refs,
        confidence=ReflectionConfidence.MEDIUM,
    )


def proposal(*findings: ReflectionFinding) -> ReflectionProposal:
    return ReflectionProposal(
        proposal_id="reflection_m4",
        trigger_id=trigger().trigger_id,
        findings=findings,
        overall_confidence=ReflectionConfidence.MEDIUM,
    )


class ScriptedAdapter:
    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(content=self.outputs.pop(0))


def test_evidence_builder_uses_stable_public_refs_and_ownership() -> None:
    builder = ReflectionEvidenceBuilder()
    kwargs = dict(
        tool_outcomes=(
            PublicOutcomeEvidence(
                outcome_id="outcome_1",
                public_summary="The public investigation revealed a dry cough.",
            ),
        ),
        observation_deltas=(
            PublicObservationDeltaEvidence(
                delta_id="delta_1",
                public_summary="One new public clue became observable.",
            ),
        ),
        assessments=(
            PublicAssessmentEvidence(
                assessment_id="assessment_1",
                public_summary="The episode reached its public completion condition.",
            ),
        ),
    )
    first = builder.build(trigger(), **kwargs)
    second = builder.build(trigger(), **kwargs)
    assert first == second
    assert all(item.episode_id == "episode_m4" for item in first.evidence_refs)
    assert all(item.case_id == "case_m4" for item in first.evidence_refs)
    assert {item.ref_type for item in first.evidence_refs} == {
        EvidenceRefType.TOOL_OUTCOME,
        EvidenceRefType.OBSERVATION_DELTA,
        EvidenceRefType.ASSESSMENT,
    }


def test_valid_evidence_produces_valid_reflection() -> None:
    action = ref(EvidenceRefType.ACTION, "action_1", "The NPC asked about cough.")
    outcome = ref(
        EvidenceRefType.TOOL_OUTCOME,
        "outcome_1",
        "The public outcome confirmed a dry cough.",
    )
    value = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            outcome.public_summary,
            action,
            outcome,
        )
    )
    assert ReflectionProposalValidator().validate(value, bundle(action, outcome)) == value


def test_bundle_external_or_other_ownership_evidence_is_rejected() -> None:
    action = ref(EvidenceRefType.ACTION, "action_1", "The NPC investigated.")
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_1", "A public clue appeared.")
    outside = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_2", "A different result.")
    value = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            outside.public_summary,
            action,
            outside,
        )
    )
    with pytest.raises(ReflectionProposalValidationError, match="outside"):
        ReflectionProposalValidator().validate(value, bundle(action, outcome))

    other_case = outcome.model_copy(update={"case_id": "case_other"})
    with pytest.raises(ValidationError, match="episode and case"):
        bundle(action, other_case)


@pytest.mark.parametrize(
    "unsupported_claim",
    (
        "The player's belief proves the diagnosis is correct.",
        "The treatment was effective.",
    ),
)
def test_unsupported_diagnosis_or_treatment_claim_is_rejected(
    unsupported_claim: str,
) -> None:
    action = ref(EvidenceRefType.ACTION, "action_1", "The NPC discussed public evidence.")
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_1", "The public action completed.")
    value = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            unsupported_claim,
            action,
            outcome,
        )
    )
    with pytest.raises(ReflectionProposalValidationError, match="not supported"):
        ReflectionProposalValidator().validate(value, bundle(action, outcome))


def test_player_belief_cannot_be_promoted_to_outcome_fact() -> None:
    belief = ref(
        EvidenceRefType.PLAYER_CONTRIBUTION,
        "contribution_1",
        "I believe the diagnosis is lung heat.",
    )
    value = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            belief.public_summary,
            belief,
        )
    )
    with pytest.raises(ReflectionProposalValidationError, match="required evidence"):
        ReflectionProposalValidator().validate(value, bundle(belief))


def test_planning_lesson_requires_plan_evidence() -> None:
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_1", "The public action completed.")
    assessment = ref(EvidenceRefType.ASSESSMENT, "assessment_1", "The episode completed.")
    with pytest.raises(ValidationError, match="planning lessons"):
        ReusableLessonProposal(
            lesson_type=ReusableLessonType.PLANNING,
            public_safe_summary=assessment.public_summary,
            applicability_scope=ApplicabilityScope(
                scope_type=ApplicabilityScopeType.SIMILAR_GOAL_TYPE,
                public_pattern_tags=("gather_evidence",),
                limitation="Only when the same public goal type is active.",
            ),
            evidence_refs=(outcome, assessment),
            confidence=ReflectionConfidence.MEDIUM,
            proposed_memory_type=MemoryType.LEARNING,
        )


def memory_ref(*, accepted: bool) -> EvidenceRef:
    payload = json.dumps(
        {
            "accepted_used_memory_ids": ["memory_1"] if accepted else [],
            "attribution_status": "accepted" if accepted else "declared_only",
            "selected_memory_ids": ["memory_1"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return ref(EvidenceRefType.MEMORY_USAGE_TRACE, "memory_trace_1", payload)


def test_selected_but_unused_memory_cannot_be_helpful() -> None:
    trace = memory_ref(accepted=False)
    value = proposal(
        finding(
            ReflectionFindingType.MEMORY_HELPFULNESS,
            trace.public_summary,
            trace,
        )
    )
    with pytest.raises(ReflectionProposalValidationError, match="selected-but-unused"):
        ReflectionProposalValidator().validate(value, bundle(trace))


def test_accepted_memory_usage_can_support_helpfulness() -> None:
    trace = memory_ref(accepted=True)
    value = proposal(
        finding(
            ReflectionFindingType.MEMORY_HELPFULNESS,
            trace.public_summary,
            trace,
        )
    )
    assert ReflectionProposalValidator().validate(value, bundle(trace)) == value


@pytest.mark.parametrize("forbidden", ("tool_call", "repository_write", "authority_override"))
def test_reflection_schema_forbids_execution_or_authority_fields(forbidden: str) -> None:
    with pytest.raises(ValidationError):
        ReflectionProposal.model_validate(
            {
                "proposal_id": "reflection_m4",
                "trigger_id": trigger().trigger_id,
                "findings": [],
                "reusable_lesson_candidates": [],
                "overall_confidence": "low",
                forbidden: {"requested": True},
            }
        )


def test_invalid_first_output_repairs_to_legal_proposal() -> None:
    action = ref(EvidenceRefType.ACTION, "action_1", "The NPC investigated.")
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_1", "A public clue appeared.")
    valid = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            outcome.public_summary,
            action,
            outcome,
        )
    )
    invalid = valid.model_copy(
        update={
            "findings": (
                finding(
                    ReflectionFindingType.SUCCESSFUL_STRATEGY,
                    "An unsupported diagnosis was correct.",
                    action,
                    outcome,
                ),
            )
        }
    )
    adapter = ScriptedAdapter(invalid.model_dump_json(), valid.model_dump_json())
    result = ReflectionProposalGenerator(adapter).generate(trigger(), bundle(action, outcome))
    assert result.proposal == valid
    assert result.attempts == 2
    assert result.used_fallback is False
    assert len(adapter.requests) == 2


def test_failed_repair_returns_non_assertive_safe_fallback() -> None:
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_1", "A public clue appeared.")
    invalid = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            "Unsupported diagnosis correctness.",
            outcome,
        )
    )
    adapter = ScriptedAdapter(invalid.model_dump_json(), invalid.model_dump_json())
    result = ReflectionProposalGenerator(adapter).generate(trigger(), bundle(outcome))
    assert result.used_fallback is True
    assert result.attempts == 2
    assert result.proposal.findings == ()
    assert result.proposal.reusable_lesson_candidates == ()


def test_builder_memory_trace_exposes_accepted_usage_not_raw_memory() -> None:
    trace = MemoryUsageTrace(
        retrieval_id="retrieval_1",
        retrieval_status=MemoryRetrievalStatus.SUCCESS,
        selected_memory_ids=("memory_1",),
        declared_used_memory_ids=("memory_1",),
        accepted_used_memory_ids=("memory_1",),
        attribution_status=MemoryUsageAttributionStatus.ACCEPTED,
        public_effect_summary="The NPC adjusted the public investigation order.",
    )
    evidence = ReflectionEvidenceBuilder().build(trigger(), memory_usage_traces=(trace,))
    summary = json.loads(evidence.evidence_refs[0].public_summary)
    assert summary["accepted_used_memory_ids"] == ["memory_1"]
    assert "embedding" not in evidence.evidence_refs[0].public_summary
    assert "raw" not in evidence.evidence_refs[0].public_summary


def test_trigger_identity_remains_deterministic_during_generation() -> None:
    first = trigger()
    second = trigger()
    adapter = ScriptedAdapter(
        ReflectionProposal(
            proposal_id="empty",
            trigger_id=first.trigger_id,
            findings=(),
            reusable_lesson_candidates=(),
            overall_confidence=ReflectionConfidence.LOW,
        ).model_dump_json()
    )
    result = ReflectionProposalGenerator(adapter).generate(
        first,
        ReflectionEvidenceBuilder().build(
            first,
            assessments=(
                PublicAssessmentEvidence(
                    assessment_id="assessment_1",
                    public_summary="A public assessment is available.",
                ),
            ),
        ),
    )
    assert first.trigger_id == second.trigger_id == result.proposal.trigger_id
