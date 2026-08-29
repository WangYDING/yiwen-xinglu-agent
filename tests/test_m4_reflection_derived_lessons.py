import json

import pytest
from pydantic import ValidationError

from xuanyi_npc.application.reflection import (
    ReflectionProposalValidationError,
    ReflectionProposalValidator,
)
from xuanyi_npc.application.reflection_memory import ReflectionMemoryCandidateBuilder
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


TRIGGER = ReflectionTrigger.create(
    trigger_type=ReflectionTriggerType.GOAL_COMPLETED,
    episode_id="episode_derived",
    case_id="case_derived",
    lifecycle_event_id="event_derived",
    reason="Public goal completion.",
)


def ref(kind: EvidenceRefType, ref_id: str, summary: str, *, episode="episode_derived", case="case_derived"):
    return EvidenceRef(
        ref_type=kind,
        ref_id=ref_id,
        episode_id=episode,
        case_id=case,
        public_summary=summary,
    )


def scope(kind: ApplicabilityScopeType, *tags: str, limitation="model draft limitation"):
    return ApplicabilityScope(
        scope_type=kind,
        public_pattern_tags=tags,
        limitation=limitation,
    )


def lesson(kind, refs, lesson_scope, *, draft="model-authored unsupported draft"):
    return ReusableLessonProposal(
        lesson_type=kind,
        public_safe_summary=draft,
        applicability_scope=lesson_scope,
        evidence_refs=refs,
        confidence=ReflectionConfidence.HIGH,
        proposed_memory_type=MemoryType.LEARNING,
    )


def proposal(value, proposal_id="proposal_derived"):
    return ReflectionProposal(
        proposal_id=proposal_id,
        trigger_id=TRIGGER.trigger_id,
        reusable_lesson_candidates=(value,),
        overall_confidence=ReflectionConfidence.HIGH,
    )


def bundle(*refs):
    return ReflectionEvidenceBundle(
        episode_id=TRIGGER.episode_id,
        case_id=TRIGGER.case_id,
        trigger=TRIGGER,
        evidence_refs=refs,
    )


ACTION = ref(
    EvidenceRefType.ACTION,
    "action_public",
    json.dumps(
        {
            "capability": "investigate",
            "dialogue": "The hidden culprit is X.",
            "public_rationale": "The hidden culprit is X.",
        }
    ),
)
OUTCOME = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_public", "A public clue was found.")
ASSESSMENT = ref(EvidenceRefType.ASSESSMENT, "assessment_public", "The public goal completed.")
GOAL = ref(EvidenceRefType.GOAL, "goal_public", "Gather public evidence.")
PLAN_STEP = ref(EvidenceRefType.PLAN_STEP, "step_public", "Inspect the public object.")
PLAN_EVALUATION = ref(
    EvidenceRefType.PLAN_EVALUATION,
    "plan_eval_public",
    "The deterministic plan evaluation marked the goal complete.",
)
CONTRIBUTION = ref(
    EvidenceRefType.PLAYER_CONTRIBUTION,
    "contribution_public",
    "The hidden diagnosis is certainly correct.",
)
CONTRIBUTION_EVALUATION = ref(
    EvidenceRefType.CONTRIBUTION_EVALUATION,
    "contribution_eval_public",
    "More public evidence was requested before accepting the suggestion.",
)


def validate(value, *refs):
    return ReflectionProposalValidator().validate(proposal(value), bundle(*refs))


def candidate(value, *refs):
    return ReflectionMemoryCandidateBuilder().build(
        player_id="player_derived",
        proposal=proposal(value),
        evidence_bundle=bundle(*refs),
    )[0]


def test_outcome_action_and_authoritative_result_render_canonical_noncausal_lesson():
    value = lesson(
        ReusableLessonType.OUTCOME,
        (ACTION, OUTCOME),
        scope(ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN, OUTCOME.ref_id),
        draft="This strategy caused success and must always be repeated.",
    )
    rendered = candidate(value, ACTION, OUTCOME).public_safe_summary
    assert "公开行为=investigate" in rendered
    assert OUTCOME.public_summary in rendered
    assert "caused success" not in rendered
    assert "hidden culprit" not in rendered.lower()
    assert "不是当前世界事实" in rendered


@pytest.mark.parametrize("refs", [(ACTION,), (CONTRIBUTION, ACTION)])
def test_outcome_without_authoritative_result_is_rejected(refs):
    with pytest.raises((ValidationError, ReflectionProposalValidationError)):
        value = lesson(
            ReusableLessonType.OUTCOME,
            refs,
            scope(ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN, "missing"),
        )
        validate(value, *refs)


def test_two_authoritative_outcome_refs_render_without_inventing_success():
    value = lesson(
        ReusableLessonType.OUTCOME,
        (OUTCOME, ASSESSMENT),
        scope(ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN, OUTCOME.ref_id),
        draft="The strategy was universally effective.",
    )
    rendered = candidate(value, OUTCOME, ASSESSMENT).public_safe_summary
    assert OUTCOME.public_summary in rendered and ASSESSMENT.public_summary in rendered
    assert "universally effective" not in rendered


def test_cross_episode_evidence_cannot_form_lesson():
    other = ref(
        EvidenceRefType.TOOL_OUTCOME,
        "other_outcome",
        "Other result.",
        episode="other_episode",
    )
    with pytest.raises(ValidationError, match="episode and case"):
        bundle(ACTION, other)


def test_planning_requires_plan_or_step_plus_plan_evaluation_and_goal_scope():
    value = lesson(
        ReusableLessonType.PLANNING,
        (GOAL, PLAN_STEP, PLAN_EVALUATION),
        scope(ApplicabilityScopeType.SIMILAR_GOAL_TYPE, GOAL.ref_id),
    )
    rendered = candidate(value, GOAL, PLAN_STEP, PLAN_EVALUATION).public_safe_summary
    assert PLAN_STEP.public_summary in rendered
    assert PLAN_EVALUATION.public_summary in rendered
    for bad_refs in ((PLAN_STEP, GOAL), (GOAL, OUTCOME)):
        with pytest.raises((ValidationError, ReflectionProposalValidationError)):
            bad = lesson(
                ReusableLessonType.PLANNING,
                bad_refs,
                scope(ApplicabilityScopeType.SIMILAR_GOAL_TYPE, GOAL.ref_id),
            )
            validate(bad, *bad_refs)


def test_cooperation_requires_contribution_and_evaluation_but_never_persists_belief():
    value = lesson(
        ReusableLessonType.COOPERATION,
        (CONTRIBUTION, CONTRIBUTION_EVALUATION, OUTCOME),
        scope(
            ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR,
            CONTRIBUTION_EVALUATION.ref_id,
        ),
    )
    rendered = candidate(value, CONTRIBUTION, CONTRIBUTION_EVALUATION, OUTCOME).public_safe_summary
    assert CONTRIBUTION.public_summary not in rendered
    assert CONTRIBUTION_EVALUATION.public_summary in rendered
    assert OUTCOME.public_summary in rendered
    for bad_refs in ((CONTRIBUTION,), (CONTRIBUTION, ACTION)):
        with pytest.raises((ValidationError, ReflectionProposalValidationError)):
            validate(
                lesson(
                    ReusableLessonType.COOPERATION,
                    bad_refs,
                    scope(ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR, "missing"),
                ),
                *bad_refs,
            )


def memory_trace(*, accepted: bool, attribution="accepted"):
    return ref(
        EvidenceRefType.MEMORY_USAGE_TRACE,
        "memory_trace_public",
        json.dumps(
            {
                "candidate_memory_ids": ["memory_old"],
                "selected_memory_ids": ["memory_old"],
                "declared_used_memory_ids": ["memory_old"],
                "accepted_used_memory_ids": ["memory_old"] if accepted else [],
                "attribution_status": attribution,
            }
        ),
    )


def test_memory_helpfulness_requires_accepted_use_and_authoritative_evaluation():
    accepted = memory_trace(accepted=True)
    value = lesson(
        ReusableLessonType.MEMORY_HELPFULNESS,
        (accepted, OUTCOME),
        scope(ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN, OUTCOME.ref_id),
        draft="The old memory caused success and is current truth.",
    )
    rendered = candidate(value, accepted, OUTCOME).public_safe_summary
    assert "accepted_used_memory_ids=memory_old" in rendered
    assert "caused success" not in rendered
    assert "current truth" not in rendered
    selected = memory_trace(accepted=False, attribution="declared_only")
    with pytest.raises(ReflectionProposalValidationError) as captured:
        validate(
            lesson(
                ReusableLessonType.MEMORY_HELPFULNESS,
                (selected, OUTCOME),
                scope(ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN, OUTCOME.ref_id),
            ),
            selected,
            OUTCOME,
        )
    assert captured.value.grounding_rule_code.value == "memory_usage_not_eligible"


def test_scope_must_match_lesson_and_copy_public_structured_anchor():
    mismatched = lesson(
        ReusableLessonType.OUTCOME,
        (ACTION, OUTCOME),
        scope(ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR, OUTCOME.ref_id),
    )
    invented = lesson(
        ReusableLessonType.OUTCOME,
        (ACTION, OUTCOME),
        scope(ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN, "invented_tag"),
    )
    for value in (mismatched, invented):
        with pytest.raises(ReflectionProposalValidationError) as captured:
            validate(value, ACTION, OUTCOME)
        assert captured.value.grounding_rule_code.value == "lesson_scope_invalid"


def test_draft_limitation_ref_order_and_tag_order_do_not_change_canonical_candidate():
    second = ref(EvidenceRefType.TOOL_OUTCOME, "outcome_second", "A second public clue was found.")
    first_value = lesson(
        ReusableLessonType.OUTCOME,
        (ACTION, OUTCOME, second),
        scope(
            ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
            second.ref_id,
            OUTCOME.ref_id,
            limitation="Draft A with unsupported hidden content.",
        ),
        draft="Draft A",
    )
    second_value = lesson(
        ReusableLessonType.OUTCOME,
        (second, OUTCOME, ACTION),
        scope(
            ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
            OUTCOME.ref_id,
            second.ref_id,
            limitation="Completely different draft B.",
        ),
        draft="Draft B",
    )
    first = candidate(first_value, ACTION, OUTCOME, second)
    second_candidate = candidate(second_value, second, OUTCOME, ACTION)
    assert first.public_safe_summary == second_candidate.public_safe_summary
    assert first.fingerprint == second_candidate.fingerprint
    assert first.applicability_scope == second_candidate.applicability_scope
    assert "Draft" not in first.public_safe_summary


def test_finding_still_uses_strict_extractive_grounding():
    finding = ReflectionFinding(
        finding_type=ReflectionFindingType.SUCCESSFUL_STRATEGY,
        public_summary="A semantic paraphrase not present in evidence.",
        evidence_refs=(ACTION, OUTCOME),
        confidence=ReflectionConfidence.HIGH,
    )
    value = ReflectionProposal(
        proposal_id="finding_regression",
        trigger_id=TRIGGER.trigger_id,
        findings=(finding,),
        overall_confidence=ReflectionConfidence.HIGH,
    )
    with pytest.raises(ReflectionProposalValidationError) as captured:
        ReflectionProposalValidator().validate(value, bundle(ACTION, OUTCOME))
    assert captured.value.grounding_rule_code.value == "claim_not_grounded"
