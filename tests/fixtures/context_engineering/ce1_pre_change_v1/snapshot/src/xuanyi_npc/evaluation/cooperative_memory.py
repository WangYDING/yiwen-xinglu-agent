"""M3-4 evaluation helpers for cooperative memory behavior."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier
from xuanyi_npc.domain.cooperative_memory import (
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
    MemoryUsageTrace,
)


class MemoryBehaviorChangeType(str, Enum):
    NONE = "none"
    GOAL = "goal"
    PLAN = "plan"
    DECISION = "decision"
    TOOL_PRIORITY = "tool_priority"
    COMMUNICATION = "communication"
    MIXED = "mixed"


class CooperativeMemoryBehaviorSnapshot(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    goal_update: str
    plan_signature: tuple[str, ...] = ()
    selected_tool: str | None = None
    capability: str
    contribution_disposition: str | None = None


class CooperativeMemoryABResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    scenario_id: Identifier
    baseline: CooperativeMemoryBehaviorSnapshot
    memory: CooperativeMemoryBehaviorSnapshot
    behavior_changed: StrictBool
    change_type: MemoryBehaviorChangeType
    memory_ids: tuple[Identifier, ...] = ()
    change_remained_legal: StrictBool


class MemoryEvaluationSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retrieval_turns: Annotated[StrictInt, Field(ge=0)]
    retrieval_success_rate: float = Field(ge=0.0, le=1.0)
    retrieval_empty_rate: float = Field(ge=0.0, le=1.0)
    retrieval_unavailable_rate: float = Field(ge=0.0, le=1.0)
    retrieval_failed_safe_rate: float = Field(ge=0.0, le=1.0)
    average_candidate_count: float = Field(ge=0.0)
    average_selected_count: float = Field(ge=0.0)
    invalid_memory_filtering_count: Annotated[StrictInt, Field(ge=0)] = 0
    invalid_memory_filtering_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_filtering_count: Annotated[StrictInt, Field(ge=0)] = 0
    duplicate_filtering_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    declared_memory_utilization_rate: float = Field(ge=0.0, le=1.0)
    accepted_memory_utilization_rate: float = Field(ge=0.0, le=1.0)
    retrieved_but_unused_rate: float = Field(ge=0.0, le=1.0)
    selected_but_unused_rate: float = Field(ge=0.0, le=1.0)
    attribution_accepted_rate: float = Field(ge=0.0, le=1.0)
    attribution_declared_only_rate: float = Field(ge=0.0, le=1.0)
    attribution_ambiguous_rate: float = Field(ge=0.0, le=1.0)
    attribution_rejected_rate: float = Field(ge=0.0, le=1.0)
    goal_influence_rate: float = Field(ge=0.0, le=1.0)
    plan_influence_rate: float = Field(ge=0.0, le=1.0)
    decision_influence_rate: float = Field(ge=0.0, le=1.0)
    tool_priority_influence_rate: float = Field(ge=0.0, le=1.0)
    communication_influence_rate: float = Field(ge=0.0, le=1.0)
    irrelevant_memory_noop_rate: float = Field(default=0.0, ge=0.0, le=1.0)


def summarize_memory_traces(
    traces: tuple[MemoryUsageTrace, ...],
    *,
    invalid_filtering_count: int = 0,
    duplicate_filtering_count: int = 0,
    irrelevant_noop_count: int = 0,
    irrelevant_scenario_count: int = 0,
) -> MemoryEvaluationSummary:
    turns = len(traces)

    def rate(count: int, denominator: int = turns) -> float:
        return 0.0 if denominator == 0 else count / denominator

    success = sum(item.retrieval_status is MemoryRetrievalStatus.SUCCESS for item in traces)
    empty = sum(item.retrieval_status is MemoryRetrievalStatus.EMPTY for item in traces)
    unavailable = sum(item.retrieval_status is MemoryRetrievalStatus.UNAVAILABLE for item in traces)
    failed_safe = sum(item.retrieval_status is MemoryRetrievalStatus.FAILED_SAFE for item in traces)
    declared = sum(bool(item.declared_used_memory_ids) for item in traces)
    accepted = sum(bool(item.accepted_used_memory_ids) for item in traces)
    retrieved_unused = sum(bool(item.candidate_memory_ids) and not item.accepted_used_memory_ids for item in traces)
    selected_unused = sum(bool(item.selected_memory_ids) and not item.accepted_used_memory_ids for item in traces)
    accepted_status = sum(item.attribution_status is MemoryUsageAttributionStatus.ACCEPTED for item in traces)
    declared_only = sum(item.attribution_status is MemoryUsageAttributionStatus.DECLARED_ONLY for item in traces)
    ambiguous = sum(item.attribution_status is MemoryUsageAttributionStatus.AMBIGUOUS for item in traces)
    rejected = sum(item.attribution_status is MemoryUsageAttributionStatus.REJECTED for item in traces)
    candidates = sum(len(item.candidate_memory_ids) for item in traces)
    selected_count = sum(len(item.selected_memory_ids) for item in traces)
    total_invalid_inputs = candidates + invalid_filtering_count
    total_duplicate_inputs = candidates + duplicate_filtering_count
    return MemoryEvaluationSummary(
        retrieval_turns=turns,
        retrieval_success_rate=rate(success),
        retrieval_empty_rate=rate(empty),
        retrieval_unavailable_rate=rate(unavailable),
        retrieval_failed_safe_rate=rate(failed_safe),
        average_candidate_count=0.0 if turns == 0 else candidates / turns,
        average_selected_count=0.0 if turns == 0 else selected_count / turns,
        invalid_memory_filtering_count=invalid_filtering_count,
        invalid_memory_filtering_rate=rate(invalid_filtering_count, total_invalid_inputs),
        duplicate_filtering_count=duplicate_filtering_count,
        duplicate_filtering_rate=rate(duplicate_filtering_count, total_duplicate_inputs),
        declared_memory_utilization_rate=rate(declared),
        accepted_memory_utilization_rate=rate(accepted),
        retrieved_but_unused_rate=rate(retrieved_unused),
        selected_but_unused_rate=rate(selected_unused),
        attribution_accepted_rate=rate(accepted_status),
        attribution_declared_only_rate=rate(declared_only),
        attribution_ambiguous_rate=rate(ambiguous),
        attribution_rejected_rate=rate(rejected),
        goal_influence_rate=rate(sum(item.goal_changed for item in traces)),
        plan_influence_rate=rate(sum(item.plan_changed for item in traces)),
        decision_influence_rate=rate(sum(item.decision_influenced for item in traces)),
        tool_priority_influence_rate=rate(sum(item.tool_priority_influenced for item in traces)),
        communication_influence_rate=rate(sum(item.communication_influenced for item in traces)),
        irrelevant_memory_noop_rate=rate(irrelevant_noop_count, irrelevant_scenario_count),
    )


def compare_memory_pair(
    *,
    scenario_id: str,
    baseline: CooperativeMemoryBehaviorSnapshot,
    memory: CooperativeMemoryBehaviorSnapshot,
    memory_ids: tuple[str, ...],
    change_remained_legal: bool,
) -> CooperativeMemoryABResult:
    changes = {
        MemoryBehaviorChangeType.GOAL: baseline.goal_update != memory.goal_update,
        MemoryBehaviorChangeType.PLAN: baseline.plan_signature != memory.plan_signature,
        MemoryBehaviorChangeType.TOOL_PRIORITY: baseline.selected_tool != memory.selected_tool,
        MemoryBehaviorChangeType.COMMUNICATION: baseline.capability != memory.capability,
        MemoryBehaviorChangeType.DECISION: baseline.contribution_disposition != memory.contribution_disposition,
    }
    active = tuple(kind for kind, changed in changes.items() if changed)
    if not active:
        change_type = MemoryBehaviorChangeType.NONE
    elif len(active) == 1:
        change_type = active[0]
    else:
        change_type = MemoryBehaviorChangeType.MIXED
    return CooperativeMemoryABResult(
        scenario_id=scenario_id,
        baseline=baseline,
        memory=memory,
        behavior_changed=bool(active),
        change_type=change_type,
        memory_ids=memory_ids,
        change_remained_legal=change_remained_legal,
    )
