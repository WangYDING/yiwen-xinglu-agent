import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.agents.model_usage import ModelUsage
from xuanyi_npc.application.reflection import (
    REFLECTION_SYSTEM_PROMPT,
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


class UsageAdapter(ScriptedAdapter):
    def __init__(self, outputs, usages):
        super().__init__(*outputs)
        self.usages = list(usages)
        self.config = SimpleNamespace(max_output_tokens=512)

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(content=self.outputs.pop(0), usage=self.usages.pop(0))


def test_initial_prompt_exposes_exact_finding_extractive_contract() -> None:
    prompt = REFLECTION_SYSTEM_PROMPT
    assert "Finding 是 extractive factual record，不是自由总结" in prompt
    assert "COPY, DO NOT PARAPHRASE" in prompt
    assert "原样完整复制该 EvidenceRef.public_summary" in prompt
    assert "ACTION 不得作为 summary anchor" in prompt
    assert "PLAN 不得作为 summary anchor" in prompt
    assert "summary 必须原样完整复制 CONTRIBUTION_EVALUATION.public_summary" in prompt
    assert "summary 必须原样完整复制该 MEMORY_USAGE_TRACE.public_summary" in prompt
    assert "如果没有可原样复制的 grounding anchor，不生成该 finding" in prompt


def test_initial_request_contains_extractive_contract_without_repair_dependency() -> None:
    value = ReflectionProposal(
        proposal_id="empty_prompt_contract",
        trigger_id=trigger().trigger_id,
        overall_confidence=ReflectionConfidence.LOW,
    )
    adapter = ScriptedAdapter(value.model_dump_json())
    result = ReflectionProposalGenerator(adapter).generate(
        trigger(), bundle(ref(EvidenceRefType.ASSESSMENT, "assessment_prompt", "Public assessment."))
    )
    assert result.repair_attempted is False
    assert len(adapter.requests) == 1
    assert "COPY, DO NOT PARAPHRASE" in adapter.requests[0].messages[0].content


def usage(request_id: str, input_tokens: int, output_tokens: int) -> ModelUsage:
    return ModelUsage(
        provider_model="DeepSeek-V4-Flash-0731",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_hit_input_tokens=0,
        cache_miss_input_tokens=input_tokens,
        reasoning_tokens=0,
        latency_ms=10.0,
        estimated_cost="0.0001",
        cost_currency="CNY",
        provider_request_id=request_id,
    )


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


def test_generation_instruction_exposes_existing_finding_evidence_contract() -> None:
    value = ReflectionProposal(
        proposal_id="empty_contract_check",
        trigger_id=trigger().trigger_id,
        overall_confidence=ReflectionConfidence.LOW,
    )
    adapter = ScriptedAdapter(value.model_dump_json())
    ReflectionProposalGenerator(adapter).generate(
        trigger(), bundle(ref(EvidenceRefType.ASSESSMENT, "assessment_contract", "Public assessment."))
    )
    system = adapter.requests[0].messages[0].content
    for finding_type in (
        "successful_strategy",
        "failed_strategy",
        "unnecessary_action",
    ):
        line = next(item for item in system.splitlines() if finding_type in item)
        assert "ACTION" in line
        assert "TOOL_OUTCOME" in line
        assert "ASSESSMENT" in line
    delayed = next(item for item in system.splitlines() if "missed_or_delayed_evidence" in item)
    assert "PLAN" in delayed and "PLAN_EVALUATION" in delayed
    assert "OBSERVATION_DELTA" in delayed and "TOOL_OUTCOME" in delayed and "ASSESSMENT" in delayed
    cooperation = next(item for item in system.splitlines() if "cooperation_observation" in item)
    assert "PLAYER_CONTRIBUTION" in cooperation
    assert "CONTRIBUTION_EVALUATION" in cooperation
    helpfulness = next(item for item in system.splitlines() if "memory_helpfulness" in item)
    assert "MEMORY_USAGE_TRACE" in helpfulness
    assert "accepted_used_memory_ids" in helpfulness
    assert "ACTION 只证明" in system
    assert "不得伪造 ref_id" in system
    assert "不得修改 public_summary" in system


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


@pytest.mark.parametrize(
    ("value_factory", "refs_factory", "expected_code"),
    (
        (
            lambda action, outcome: proposal(finding(
                ReflectionFindingType.SUCCESSFUL_STRATEGY,
                outcome.public_summary,
                outcome,
            )),
            lambda action, outcome: (outcome,),
            "required_action_evidence_missing",
        ),
        (
            lambda action, outcome: proposal(finding(
                ReflectionFindingType.SUCCESSFUL_STRATEGY,
                action.public_summary,
                action,
            )),
            lambda action, outcome: (action,),
            "required_authoritative_evidence_missing",
        ),
        (
            lambda action, outcome: proposal(finding(
                ReflectionFindingType.MISSED_OR_DELAYED_EVIDENCE,
                outcome.public_summary,
                outcome,
            )),
            lambda action, outcome: (outcome,),
            "required_planning_evidence_missing",
        ),
        (
            lambda action, outcome: proposal(finding(
                ReflectionFindingType.COOPERATION_OBSERVATION,
                outcome.public_summary,
                outcome,
            )),
            lambda action, outcome: (outcome,),
            "required_cooperation_evidence_missing",
        ),
        (
            lambda action, outcome: proposal(finding(
                ReflectionFindingType.MEMORY_HELPFULNESS,
                outcome.public_summary,
                outcome,
            )),
            lambda action, outcome: (outcome,),
            "memory_usage_trace_missing",
        ),
    ),
)
def test_grounding_requirement_branches_have_exact_rule_codes(
    value_factory, refs_factory, expected_code
) -> None:
    action = ref(EvidenceRefType.ACTION, "action_rule", "The NPC investigated.")
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_rule", "A public clue appeared.")
    value = value_factory(action, outcome)
    with pytest.raises(ReflectionProposalValidationError) as captured:
        ReflectionProposalValidator().validate(value, bundle(*refs_factory(action, outcome)))
    assert captured.value.grounding_rule_code.value == expected_code


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

    payload_mismatch = outcome.model_copy(update={"public_summary": "Changed public payload."})
    mismatch_value = proposal(
        finding(
            ReflectionFindingType.SUCCESSFUL_STRATEGY,
            payload_mismatch.public_summary,
            action,
            payload_mismatch,
        )
    )
    with pytest.raises(ReflectionProposalValidationError) as captured:
        ReflectionProposalValidator().validate(mismatch_value, bundle(action, outcome))
    assert captured.value.grounding_rule_code.value == "evidence_ref_payload_mismatch"

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


def test_agent_dialogue_cannot_be_laundered_by_unrelated_outcome() -> None:
    action = ref(
        EvidenceRefType.ACTION,
        "action_claim",
        "The hidden culprit is certainly the lamp keeper.",
    )
    outcome = ref(
        EvidenceRefType.TOOL_OUTCOME,
        "outcome_public",
        "The public inspection found an old ribbon on the lamp handle.",
    )
    lesson = ReusableLessonProposal(
        lesson_type=ReusableLessonType.OUTCOME,
        public_safe_summary=action.public_summary,
        applicability_scope=ApplicabilityScope(
            scope_type=ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
            public_pattern_tags=(outcome.ref_id,),
            limitation="Only when the same public trace is observed.",
        ),
        evidence_refs=(action, outcome),
        confidence=ReflectionConfidence.HIGH,
        proposed_memory_type=MemoryType.LEARNING,
    )
    value = ReflectionProposal(
        proposal_id="reflection_agent_claim",
        trigger_id=trigger().trigger_id,
        reusable_lesson_candidates=(lesson,),
        overall_confidence=ReflectionConfidence.HIGH,
    )
    assert ReflectionProposalValidator().validate(value, bundle(action, outcome)) is value


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
    with pytest.raises(ReflectionProposalValidationError, match="selected-but-unused") as captured:
        ReflectionProposalValidator().validate(value, bundle(trace))
    assert captured.value.grounding_rule_code.value == "memory_usage_not_eligible"


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
    assert result.repair_attempted is True
    assert result.repair_succeeded is True


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
    assert result.repair_attempted is True
    assert result.repair_succeeded is False
    assert result.attempt_telemetry[0].failure_stage == "reflection_grounding_validation"
    assert result.attempt_telemetry[1].failure_stage == "reflection_grounding_validation"


def test_invalid_json_failure_is_classified_before_successful_repair() -> None:
    valid = ReflectionProposal(
        proposal_id="empty_valid",
        trigger_id=trigger().trigger_id,
        overall_confidence=ReflectionConfidence.LOW,
    )
    result = ReflectionProposalGenerator(
        ScriptedAdapter("{not-json", valid.model_dump_json())
    ).generate(trigger(), bundle(ref(EvidenceRefType.ASSESSMENT, "assessment_1", "Public assessment.")))
    first = result.attempt_telemetry[0]
    assert first.failure_stage == "reflection_json_parse"
    assert first.failure_code == "invalid_json"


def test_required_field_and_enum_failures_are_classified() -> None:
    valid = ReflectionProposal(
        proposal_id="empty_valid",
        trigger_id=trigger().trigger_id,
        overall_confidence=ReflectionConfidence.LOW,
    )
    evidence = bundle(ref(EvidenceRefType.ASSESSMENT, "assessment_1", "Public assessment."))
    missing = ReflectionProposalGenerator(
        ScriptedAdapter('{"proposal_id":"missing"}', valid.model_dump_json())
    ).generate(trigger(), evidence).attempt_telemetry[0]
    invalid_enum = json.loads(valid.model_dump_json())
    invalid_enum["overall_confidence"] = "certain"
    enum = ReflectionProposalGenerator(
        ScriptedAdapter(json.dumps(invalid_enum), valid.model_dump_json())
    ).generate(trigger(), evidence).attempt_telemetry[0]
    assert missing.failure_stage == "reflection_schema_validation"
    assert missing.failure_code == "required_field_missing"
    assert missing.field_path == "trigger_id"
    assert enum.failure_stage == "reflection_schema_validation"
    assert enum.failure_code == "enum_mismatch"
    assert enum.field_path == "overall_confidence"


def test_invalid_ref_and_unsupported_claim_have_distinct_grounding_codes() -> None:
    action = ref(EvidenceRefType.ACTION, "action_1", "The NPC investigated.")
    outcome = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_1", "A public clue appeared.")
    outside = ref(EvidenceRefType.TOOL_OUTCOME, "outside", "Another public clue.")
    outside_proposal = proposal(
        finding(ReflectionFindingType.SUCCESSFUL_STRATEGY, outside.public_summary, action, outside)
    )
    unsupported = proposal(
        finding(ReflectionFindingType.SUCCESSFUL_STRATEGY, "Unsupported claim.", action, outcome)
    )
    empty = ReflectionProposal(
        proposal_id="empty_valid",
        trigger_id=trigger().trigger_id,
        overall_confidence=ReflectionConfidence.LOW,
    )
    invalid_ref = ReflectionProposalGenerator(
        ScriptedAdapter(outside_proposal.model_dump_json(), empty.model_dump_json())
    ).generate(trigger(), bundle(action, outcome)).attempt_telemetry[0]
    unsupported_claim = ReflectionProposalGenerator(
        ScriptedAdapter(unsupported.model_dump_json(), empty.model_dump_json())
    ).generate(trigger(), bundle(action, outcome)).attempt_telemetry[0]
    assert invalid_ref.failure_code == "evidence_ref_not_in_bundle"
    assert unsupported_claim.failure_code == "claim_not_grounded"


def test_per_attempt_provider_usage_is_not_aggregated() -> None:
    valid = ReflectionProposal(
        proposal_id="empty_valid",
        trigger_id=trigger().trigger_id,
        overall_confidence=ReflectionConfidence.LOW,
    )
    adapter = UsageAdapter(
        ("{not-json", valid.model_dump_json()),
        (usage("request_1", 101, 11), usage("request_2", 202, 22)),
    )
    result = ReflectionProposalGenerator(adapter).generate(
        trigger(), bundle(ref(EvidenceRefType.ASSESSMENT, "assessment_1", "Public assessment."))
    )
    first, second = result.attempt_telemetry
    assert (first.provider_request_id, first.input_tokens, first.output_tokens) == (
        "request_1", 101, 11
    )
    assert (second.provider_request_id, second.input_tokens, second.output_tokens) == (
        "request_2", 202, 22
    )
    assert first.configured_max_output_tokens == second.configured_max_output_tokens == 512


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
