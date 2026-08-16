import pytest
from pydantic import ValidationError

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


def _trigger() -> ReflectionTrigger:
    return ReflectionTrigger.create(
        trigger_type=ReflectionTriggerType.GOAL_COMPLETED,
        episode_id="episode_alpha",
        case_id="case_alpha",
        lifecycle_event_id="goal_done_alpha",
        goal_id="goal_alpha",
        reason="Goal reached a deterministic lifecycle boundary.",
    )


def _evidence(ref_type: EvidenceRefType, ref_id: str) -> EvidenceRef:
    return EvidenceRef(
        ref_type=ref_type,
        ref_id=ref_id,
        episode_id="episode_alpha",
        case_id="case_alpha",
        public_summary=f"public evidence for {ref_id}",
    )


def _scope() -> ApplicabilityScope:
    return ApplicabilityScope(
        scope_type=ApplicabilityScopeType.SIMILAR_GOAL_TYPE,
        public_case_stage="stage_investigation",
        public_pattern_tags=("cough",),
        limitation="Only applies when the same public goal type and symptom pattern are present.",
    )


def test_reflection_trigger_identity_is_stable_and_lifecycle_bounded() -> None:
    first = _trigger()
    second = _trigger()

    assert first.trigger_id == second.trigger_id
    assert first.identity_key == second.identity_key
    assert first.trigger_id.startswith("rtr_")

    with pytest.raises(ValidationError, match="trigger_id must match"):
        ReflectionTrigger(
            trigger_id="rtr_wrong",
            trigger_type=ReflectionTriggerType.GOAL_COMPLETED,
            episode_id="episode_alpha",
            case_id="case_alpha",
            lifecycle_event_id="goal_done_alpha",
            goal_id="goal_alpha",
            reason="Wrong id should fail.",
        )


def test_evidence_bundle_requires_refs_from_same_episode_case_and_unique_refs() -> None:
    trigger = _trigger()
    ref = _evidence(EvidenceRefType.TOOL_OUTCOME, "tool_alpha")

    bundle = ReflectionEvidenceBundle(
        episode_id="episode_alpha",
        case_id="case_alpha",
        trigger=trigger,
        evidence_refs=(ref,),
    )

    assert bundle.evidence_refs == (ref,)

    with pytest.raises(ValidationError, match="must be unique"):
        ReflectionEvidenceBundle(
            episode_id="episode_alpha",
            case_id="case_alpha",
            trigger=trigger,
            evidence_refs=(ref, ref),
        )

    with pytest.raises(ValidationError, match="must belong"):
        ReflectionEvidenceBundle(
            episode_id="episode_beta",
            case_id="case_alpha",
            trigger=trigger,
            evidence_refs=(ref,),
        )


def test_finding_requires_at_least_one_evidence_ref() -> None:
    finding = ReflectionFinding(
        finding_type=ReflectionFindingType.SUCCESSFUL_STRATEGY,
        public_summary="Asking a targeted public symptom question produced useful evidence.",
        evidence_refs=(_evidence(EvidenceRefType.TOOL_OUTCOME, "tool_alpha"),),
        confidence=ReflectionConfidence.MEDIUM,
    )

    assert finding.evidence_refs

    with pytest.raises(ValidationError):
        ReflectionFinding(
            finding_type=ReflectionFindingType.SUCCESSFUL_STRATEGY,
            public_summary="No provenance.",
            evidence_refs=(),
            confidence=ReflectionConfidence.LOW,
        )


def test_reusable_lesson_requires_enough_provenance_and_allowed_memory_type() -> None:
    lesson = ReusableLessonProposal(
        lesson_type=ReusableLessonType.OUTCOME,
        public_safe_summary="A public tool outcome supported preserving this outcome-grounded lesson.",
        applicability_scope=_scope(),
        evidence_refs=(
            _evidence(EvidenceRefType.TOOL_OUTCOME, "tool_alpha"),
            _evidence(EvidenceRefType.ASSESSMENT, "assessment_alpha"),
        ),
        confidence=ReflectionConfidence.HIGH,
        proposed_memory_type=MemoryType.REFLECTION,
    )

    assert lesson.proposed_memory_type is MemoryType.REFLECTION

    with pytest.raises(ValidationError):
        ReusableLessonProposal(
            lesson_type=ReusableLessonType.OUTCOME,
            public_safe_summary="One evidence ref is not enough.",
            applicability_scope=_scope(),
            evidence_refs=(_evidence(EvidenceRefType.TOOL_OUTCOME, "tool_alpha"),),
            confidence=ReflectionConfidence.LOW,
            proposed_memory_type=MemoryType.REFLECTION,
        )

    with pytest.raises(ValidationError, match="not allowed"):
        ReusableLessonProposal(
            lesson_type=ReusableLessonType.OUTCOME,
            public_safe_summary="Relationship memories are not reflection lesson write targets.",
            applicability_scope=_scope(),
            evidence_refs=(
                _evidence(EvidenceRefType.TOOL_OUTCOME, "tool_alpha"),
                _evidence(EvidenceRefType.ASSESSMENT, "assessment_alpha"),
            ),
            confidence=ReflectionConfidence.LOW,
            proposed_memory_type=MemoryType.RELATIONSHIP,
        )


@pytest.mark.parametrize(
    ("lesson_type", "bad_evidence", "good_evidence"),
    [
        (
            ReusableLessonType.OUTCOME,
            (EvidenceRefType.PLAN, EvidenceRefType.PLAYER_CONTRIBUTION),
            (EvidenceRefType.TOOL_OUTCOME, EvidenceRefType.PLAYER_CONTRIBUTION),
        ),
        (
            ReusableLessonType.PLANNING,
            (EvidenceRefType.ACTION, EvidenceRefType.TOOL_OUTCOME),
            (EvidenceRefType.PLAN, EvidenceRefType.PLAN_EVALUATION),
        ),
        (
            ReusableLessonType.COOPERATION,
            (EvidenceRefType.ACTION, EvidenceRefType.TOOL_OUTCOME),
            (EvidenceRefType.PLAYER_CONTRIBUTION, EvidenceRefType.CONTRIBUTION_EVALUATION),
        ),
        (
            ReusableLessonType.MEMORY_HELPFULNESS,
            (EvidenceRefType.ACTION, EvidenceRefType.TOOL_OUTCOME),
            (EvidenceRefType.MEMORY_USAGE_TRACE, EvidenceRefType.PLAN_EVALUATION),
        ),
    ],
)
def test_lesson_type_requires_matching_evidence(
    lesson_type: ReusableLessonType,
    bad_evidence: tuple[EvidenceRefType, EvidenceRefType],
    good_evidence: tuple[EvidenceRefType, EvidenceRefType],
) -> None:
    with pytest.raises(ValidationError):
        ReusableLessonProposal(
            lesson_type=lesson_type,
            public_safe_summary="Bad evidence types should fail.",
            applicability_scope=_scope(),
            evidence_refs=(
                _evidence(bad_evidence[0], "bad_alpha"),
                _evidence(bad_evidence[1], "bad_beta"),
            ),
            confidence=ReflectionConfidence.LOW,
            proposed_memory_type=MemoryType.REFLECTION,
        )

    lesson = ReusableLessonProposal(
        lesson_type=lesson_type,
        public_safe_summary="Good evidence types should pass.",
        applicability_scope=_scope(),
        evidence_refs=(
            _evidence(good_evidence[0], "good_alpha"),
            _evidence(good_evidence[1], "good_beta"),
        ),
        confidence=ReflectionConfidence.MEDIUM,
        proposed_memory_type=MemoryType.REFLECTION,
    )

    assert lesson.lesson_type is lesson_type


def test_applicability_scope_is_bounded() -> None:
    scope = _scope()

    assert scope.public_case_stage == "stage_investigation"

    with pytest.raises(ValidationError, match="bounded"):
        ApplicabilityScope(
            scope_type=ApplicabilityScopeType.SIMILAR_PUBLIC_SYMPTOM_PATTERN,
            limitation="This unbounded scope should fail.",
        )

    with pytest.raises(ValidationError, match="unique"):
        ApplicabilityScope(
            scope_type=ApplicabilityScopeType.SIMILAR_PUBLIC_SYMPTOM_PATTERN,
            public_pattern_tags=("cough", "cough"),
            limitation="Duplicate tags should fail.",
        )


def test_reflection_proposal_has_no_tool_repository_or_authority_override_fields() -> None:
    finding = ReflectionFinding(
        finding_type=ReflectionFindingType.FAILED_STRATEGY,
        public_summary="The strategy had insufficient public evidence.",
        evidence_refs=(_evidence(EvidenceRefType.PLAN_EVALUATION, "plan_eval_alpha"),),
        confidence=ReflectionConfidence.MEDIUM,
    )

    proposal = ReflectionProposal(
        proposal_id="proposal_alpha",
        trigger_id=_trigger().trigger_id,
        findings=(finding,),
        overall_confidence=ReflectionConfidence.MEDIUM,
    )

    assert proposal.findings == (finding,)

    for forbidden_field in ("tool_call", "repository_write", "authority_override"):
        with pytest.raises(ValidationError):
            ReflectionProposal(
                proposal_id="proposal_alpha",
                trigger_id=_trigger().trigger_id,
                findings=(finding,),
                overall_confidence=ReflectionConfidence.MEDIUM,
                **{forbidden_field: "not_allowed"},
            )


def test_reflection_proposal_allows_empty_safe_fallback() -> None:
    proposal = ReflectionProposal(
        proposal_id="proposal_alpha",
        trigger_id=_trigger().trigger_id,
        findings=(),
        reusable_lesson_candidates=(),
        overall_confidence=ReflectionConfidence.LOW,
    )
    assert proposal.findings == ()
    assert proposal.reusable_lesson_candidates == ()
