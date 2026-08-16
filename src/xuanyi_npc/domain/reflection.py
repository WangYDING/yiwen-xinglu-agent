"""Outcome-grounded reflection contracts for cooperative Game NPC episodes.

M4 reflection is a bounded proposal layer. These models intentionally do not
perform semantic hidden-fact detection, repository writes, tool execution, or
authority changes; those belong to later deterministic validators/policies.
"""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from typing import Annotated

from pydantic import ConfigDict, Field, StrictInt, computed_field, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .memory import MemoryType


class ReflectionTriggerType(str, Enum):
    GOAL_COMPLETED = "goal_completed"
    GOAL_BLOCKED = "goal_blocked"
    PLAN_ABANDONED = "plan_abandoned"
    PLAN_REPEATEDLY_REVISED = "plan_repeatedly_revised"
    EPISODE_COMPLETED = "episode_completed"
    SAFETY_OR_AUTHORITY_BLOCK = "safety_or_authority_block"
    EVALUATION_OUTCOME_AVAILABLE = "evaluation_outcome_available"


def stable_reflection_trigger_id(
    *,
    trigger_type: ReflectionTriggerType,
    episode_id: str,
    case_id: str,
    lifecycle_event_id: str,
    goal_id: str | None = None,
    plan_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    """Return a deterministic idempotency key for one lifecycle event."""

    raw_key = "|".join(
        (
            trigger_type.value,
            episode_id,
            case_id,
            lifecycle_event_id,
            goal_id or "",
            plan_id or "",
            turn_id or "",
        )
    )
    return f"rtr_{sha256(raw_key.encode('utf-8')).hexdigest()[:24]}"


class ReflectionTrigger(DomainModel):
    """A lifecycle-bound reflection trigger with stable deterministic identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_id: Identifier
    trigger_type: ReflectionTriggerType
    episode_id: Identifier
    case_id: Identifier
    lifecycle_event_id: Identifier
    reason: NonEmptyText
    goal_id: Identifier | None = None
    plan_id: Identifier | None = None
    turn_id: Identifier | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def identity_key(self) -> str:
        return stable_reflection_trigger_id(
            trigger_type=self.trigger_type,
            episode_id=self.episode_id,
            case_id=self.case_id,
            lifecycle_event_id=self.lifecycle_event_id,
            goal_id=self.goal_id,
            plan_id=self.plan_id,
            turn_id=self.turn_id,
        )

    @model_validator(mode="after")
    def validate_identity(self) -> "ReflectionTrigger":
        if self.trigger_id != self.identity_key:
            raise ValueError("trigger_id must match the deterministic lifecycle identity")
        return self

    @classmethod
    def create(
        cls,
        *,
        trigger_type: ReflectionTriggerType,
        episode_id: str,
        case_id: str,
        lifecycle_event_id: str,
        reason: str,
        goal_id: str | None = None,
        plan_id: str | None = None,
        turn_id: str | None = None,
    ) -> "ReflectionTrigger":
        trigger_id = stable_reflection_trigger_id(
            trigger_type=trigger_type,
            episode_id=episode_id,
            case_id=case_id,
            lifecycle_event_id=lifecycle_event_id,
            goal_id=goal_id,
            plan_id=plan_id,
            turn_id=turn_id,
        )
        return cls(
            trigger_id=trigger_id,
            trigger_type=trigger_type,
            episode_id=episode_id,
            case_id=case_id,
            lifecycle_event_id=lifecycle_event_id,
            reason=reason,
            goal_id=goal_id,
            plan_id=plan_id,
            turn_id=turn_id,
        )


class EvidenceRefType(str, Enum):
    GOAL = "goal"
    PLAN = "plan"
    PLAN_STEP = "plan_step"
    PLAN_EVALUATION = "plan_evaluation"
    ACTION = "action"
    TOOL_OUTCOME = "tool_outcome"
    OBSERVATION_DELTA = "observation_delta"
    PLAYER_CONTRIBUTION = "player_contribution"
    CONTRIBUTION_EVALUATION = "contribution_evaluation"
    MEMORY_USAGE_TRACE = "memory_usage_trace"
    ASSESSMENT = "assessment"


class EvidenceRef(DomainModel):
    """Safe public provenance pointer into existing runtime/evaluation traces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref_type: EvidenceRefType
    ref_id: Identifier
    episode_id: Identifier
    case_id: Identifier
    public_summary: NonEmptyText


class ReflectionEvidenceBundle(DomainModel):
    """Bounded public evidence available to one reflection proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_id: Identifier
    case_id: Identifier
    trigger: ReflectionTrigger
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> "ReflectionEvidenceBundle":
        if self.trigger.episode_id != self.episode_id or self.trigger.case_id != self.case_id:
            raise ValueError("trigger must belong to the evidence bundle episode and case")
        seen: set[tuple[EvidenceRefType, str]] = set()
        for ref in self.evidence_refs:
            if ref.episode_id != self.episode_id or ref.case_id != self.case_id:
                raise ValueError("evidence refs must belong to the evidence bundle episode and case")
            key = (ref.ref_type, ref.ref_id)
            if key in seen:
                raise ValueError("evidence refs must be unique within a bundle")
            seen.add(key)
        return self


class ReflectionFindingType(str, Enum):
    SUCCESSFUL_STRATEGY = "successful_strategy"
    FAILED_STRATEGY = "failed_strategy"
    MISSED_OR_DELAYED_EVIDENCE = "missed_or_delayed_evidence"
    UNNECESSARY_ACTION = "unnecessary_action"
    COOPERATION_OBSERVATION = "cooperation_observation"
    MEMORY_HELPFULNESS = "memory_helpfulness"


class ReflectionConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReflectionFinding(DomainModel):
    """One model-authored finding, grounded by explicit provenance refs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_type: ReflectionFindingType
    public_summary: NonEmptyText
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)
    confidence: ReflectionConfidence


class ReusableLessonType(str, Enum):
    OUTCOME = "outcome"
    PLANNING = "planning"
    COOPERATION = "cooperation"
    MEMORY_HELPFULNESS = "memory_helpfulness"


class ApplicabilityScopeType(str, Enum):
    SAME_CASE_STAGE = "same_case_stage"
    SIMILAR_PUBLIC_SYMPTOM_PATTERN = "similar_public_symptom_pattern"
    SIMILAR_GOAL_TYPE = "similar_goal_type"
    SIMILAR_PLAYER_BEHAVIOR = "similar_player_behavior"
    SIMILAR_TOOL_OUTCOME_PATTERN = "similar_tool_outcome_pattern"


class ApplicabilityScope(DomainModel):
    """Finite, bounded scope for future retrieval/use; never unrestricted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_type: ApplicabilityScopeType
    public_case_stage: Identifier | None = None
    public_pattern_tags: tuple[Identifier, ...] = Field(default_factory=tuple, max_length=5)
    limitation: NonEmptyText

    @model_validator(mode="after")
    def validate_scope(self) -> "ApplicabilityScope":
        if not self.public_case_stage and not self.public_pattern_tags:
            raise ValueError("applicability scope must include a bounded stage or public pattern tag")
        if len(set(self.public_pattern_tags)) != len(self.public_pattern_tags):
            raise ValueError("public pattern tags must be unique")
        return self


REFLECTION_MEMORY_TYPE_ALLOWLIST = frozenset(
    {
        MemoryType.EPISODIC,
        MemoryType.LEARNING,
        MemoryType.REFLECTION,
    }
)


class ReusableLessonProposal(DomainModel):
    """A bounded candidate lesson; it is not a persisted memory write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lesson_type: ReusableLessonType
    public_safe_summary: NonEmptyText
    applicability_scope: ApplicabilityScope
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=2)
    confidence: ReflectionConfidence
    proposed_memory_type: MemoryType

    @model_validator(mode="after")
    def validate_lesson(self) -> "ReusableLessonProposal":
        if self.proposed_memory_type not in REFLECTION_MEMORY_TYPE_ALLOWLIST:
            raise ValueError("proposed memory type is not allowed for reflection lessons")
        evidence_types = {ref.ref_type for ref in self.evidence_refs}
        if self.lesson_type is ReusableLessonType.OUTCOME and not (
            {EvidenceRefType.TOOL_OUTCOME, EvidenceRefType.ASSESSMENT} & evidence_types
        ):
            raise ValueError("outcome lessons require tool outcome or assessment evidence")
        if self.lesson_type is ReusableLessonType.PLANNING and not (
            {EvidenceRefType.PLAN, EvidenceRefType.PLAN_EVALUATION} & evidence_types
        ):
            raise ValueError("planning lessons require plan or plan evaluation evidence")
        if self.lesson_type is ReusableLessonType.COOPERATION and not (
            {EvidenceRefType.PLAYER_CONTRIBUTION, EvidenceRefType.CONTRIBUTION_EVALUATION} & evidence_types
        ):
            raise ValueError("cooperation lessons require player contribution evidence")
        if (
            self.lesson_type is ReusableLessonType.MEMORY_HELPFULNESS
            and EvidenceRefType.MEMORY_USAGE_TRACE not in evidence_types
        ):
            raise ValueError("memory-helpfulness lessons require memory usage trace evidence")
        return self


class ReflectionProposal(DomainModel):
    """Structured reflection proposal only; no tool calls or repository writes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: Identifier
    trigger_id: Identifier
    findings: tuple[ReflectionFinding, ...] = Field(default_factory=tuple, max_length=12)
    reusable_lesson_candidates: tuple[ReusableLessonProposal, ...] = Field(default_factory=tuple, max_length=5)
    overall_confidence: ReflectionConfidence
    proposal_revision: Annotated[StrictInt, Field(ge=1, le=10)] = 1

    @model_validator(mode="after")
    def validate_proposal(self) -> "ReflectionProposal":
        if not self.findings and not self.reusable_lesson_candidates:
            raise ValueError("reflection proposal must contain at least one finding or reusable lesson")
        return self
