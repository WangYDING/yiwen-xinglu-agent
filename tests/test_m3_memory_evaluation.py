from xuanyi_npc.domain.cooperative_memory import (
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
    MemoryUsageTrace,
)
from xuanyi_npc.evaluation import (
    CooperativeMemoryBehaviorSnapshot,
    MemoryBehaviorChangeType,
    compare_memory_pair,
    summarize_memory_traces,
)


def trace(**updates):
    base = {
        "retrieval_id": "retrieval_eval",
        "retrieval_status": MemoryRetrievalStatus.SUCCESS,
        "candidate_memory_ids": ("memory_a", "memory_b"),
        "selected_memory_ids": ("memory_a",),
        "declared_used_memory_ids": (),
        "accepted_used_memory_ids": (),
        "influence_types": (),
        "attribution_status": MemoryUsageAttributionStatus.REJECTED,
    }
    base.update(updates)
    return MemoryUsageTrace(**base)


def snapshot(*, plan=("问诊",), tool=None, capability="explain", goal="keep"):
    return CooperativeMemoryBehaviorSnapshot(
        goal_update=goal,
        plan_signature=plan,
        selected_tool=tool,
        capability=capability,
        contribution_disposition="partial_accept",
    )


def test_accepted_utilization_counts_only_accepted_used_memory() -> None:
    summary = summarize_memory_traces((
        trace(
            declared_used_memory_ids=("memory_a",),
            accepted_used_memory_ids=("memory_a",),
            influence_types=("plan_priority",),
            attribution_status=MemoryUsageAttributionStatus.ACCEPTED,
            plan_changed=True,
        ),
        trace(
            declared_used_memory_ids=("memory_a",),
            influence_types=("plan_priority",),
            attribution_status=MemoryUsageAttributionStatus.DECLARED_ONLY,
        ),
        trace(retrieval_status=MemoryRetrievalStatus.FAILED_SAFE, candidate_memory_ids=(), selected_memory_ids=()),
    ))

    assert summary.retrieval_turns == 3
    assert summary.declared_memory_utilization_rate == 2 / 3
    assert summary.accepted_memory_utilization_rate == 1 / 3
    assert summary.selected_but_unused_rate == 1 / 3
    assert summary.plan_influence_rate == 1 / 3
    assert summary.retrieval_failed_safe_rate == 1 / 3


def test_invalid_duplicate_and_irrelevant_noop_metrics_are_separate() -> None:
    summary = summarize_memory_traces(
        (trace(),),
        invalid_filtering_count=2,
        duplicate_filtering_count=1,
        irrelevant_noop_count=1,
        irrelevant_scenario_count=1,
    )

    assert summary.invalid_memory_filtering_count == 2
    assert summary.invalid_memory_filtering_rate > 0
    assert summary.duplicate_filtering_count == 1
    assert summary.irrelevant_memory_noop_rate == 1.0
    assert summary.accepted_memory_utilization_rate == 0.0


def test_plan_ab_evaluation_detects_behavior_difference() -> None:
    result = compare_memory_pair(
        scenario_id="plan_ab",
        baseline=snapshot(plan=("先问诊", "再查环境")),
        memory=snapshot(plan=("先查环境", "再问诊")),
        memory_ids=("memory_plan",),
        change_remained_legal=True,
    )

    assert result.behavior_changed is True
    assert result.change_type is MemoryBehaviorChangeType.PLAN
    assert result.change_remained_legal is True


def test_tool_priority_ab_evaluation_detects_behavior_difference() -> None:
    result = compare_memory_pair(
        scenario_id="tool_ab",
        baseline=snapshot(tool="question_patient", capability="use_tool"),
        memory=snapshot(tool="inspect_object", capability="use_tool"),
        memory_ids=("memory_tool",),
        change_remained_legal=True,
    )

    assert result.behavior_changed is True
    assert result.change_type is MemoryBehaviorChangeType.TOOL_PRIORITY


def test_irrelevant_memory_ab_evaluation_can_record_noop() -> None:
    base = snapshot(plan=("先问诊",), tool=None)
    result = compare_memory_pair(
        scenario_id="irrelevant_noop",
        baseline=base,
        memory=base,
        memory_ids=("memory_irrelevant",),
        change_remained_legal=True,
    )

    assert result.behavior_changed is False
    assert result.change_type is MemoryBehaviorChangeType.NONE
