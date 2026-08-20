"""Auditable M4 lifecycle/consolidation metrics."""

from pydantic import ConfigDict, Field

from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.domain.reflection_lifecycle import (
    ReflectionLifecycleResult,
    ReflectionLifecycleStatus,
    ReflectionProposalStatus,
)
from xuanyi_npc.domain.reflection_memory import ReflectionMemoryWriteOutcome


class ReflectionEvaluationSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    eligible_trigger_count: int = Field(ge=0)
    reflection_attempt_count: int = Field(ge=0)
    valid_proposal_rate: float = Field(ge=0.0, le=1.0)
    repair_rate: float = Field(ge=0.0, le=1.0)
    fallback_rate: float = Field(ge=0.0, le=1.0)
    average_candidate_count: float = Field(ge=0.0)
    accepted_write_count: int = Field(ge=0)
    accepted_write_rate: float = Field(ge=0.0, le=1.0)
    duplicate_skip_rate: float = Field(ge=0.0, le=1.0)
    weak_evidence_rejection_rate: float = Field(ge=0.0, le=1.0)
    unsafe_rejection_rate: float = Field(ge=0.0, le=1.0)
    conflict_rejection_rate: float = Field(ge=0.0, le=1.0)
    scope_too_broad_rejection_rate: float = Field(ge=0.0, le=1.0)
    repository_failure_rate: float = Field(ge=0.0, le=1.0)
    idempotent_replay_success_count: int = Field(ge=0)
    future_retrieval_success_count: int = Field(ge=0)


def summarize_reflection_lifecycle(
    results: tuple[ReflectionLifecycleResult, ...],
    *,
    future_retrieval_success_count: int = 0,
) -> ReflectionEvaluationSummary:
    eligible = len(results)
    attempts = sum(item.reflection_attempt_count for item in results)
    decisions = tuple(
        decision for result in results for decision in result.write_decisions
    )
    denominator = len(decisions)

    def rate(count: int, total: int) -> float:
        return count / total if total else 0.0

    def outcomes(value: ReflectionMemoryWriteOutcome) -> int:
        return sum(item.outcome is value for item in decisions)

    candidates = sum(len(item.candidate_ids) for item in results)
    valid = sum(
        item.proposal_status is ReflectionProposalStatus.VALID for item in results
    )
    fallback = sum(
        item.status is ReflectionLifecycleStatus.FALLBACK for item in results
    )
    repaired = sum(item.repaired for item in results)
    writes = outcomes(ReflectionMemoryWriteOutcome.WRITE_NEW)
    return ReflectionEvaluationSummary(
        eligible_trigger_count=eligible,
        reflection_attempt_count=attempts,
        valid_proposal_rate=rate(valid, eligible),
        repair_rate=rate(repaired, attempts),
        fallback_rate=rate(fallback, eligible),
        average_candidate_count=rate(candidates, eligible),
        accepted_write_count=writes,
        accepted_write_rate=rate(writes, denominator),
        duplicate_skip_rate=rate(
            outcomes(ReflectionMemoryWriteOutcome.SKIP_DUPLICATE), denominator
        ),
        weak_evidence_rejection_rate=rate(
            outcomes(ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE), denominator
        ),
        unsafe_rejection_rate=rate(
            outcomes(ReflectionMemoryWriteOutcome.REJECT_UNSAFE), denominator
        ),
        conflict_rejection_rate=rate(
            outcomes(ReflectionMemoryWriteOutcome.REJECT_CONFLICT), denominator
        ),
        scope_too_broad_rejection_rate=rate(
            outcomes(ReflectionMemoryWriteOutcome.REJECT_SCOPE_TOO_BROAD), denominator
        ),
        repository_failure_rate=rate(
            outcomes(ReflectionMemoryWriteOutcome.REPOSITORY_FAILURE), denominator
        ),
        idempotent_replay_success_count=sum(
            item.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
            and item.reflection_attempt_count == 0
            for item in results
        ),
        future_retrieval_success_count=future_retrieval_success_count,
    )

