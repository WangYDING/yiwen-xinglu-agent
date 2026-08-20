"""Deterministic, observer-only contracts for the M5 agent benchmark."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictBool, StrictInt

from xuanyi_npc.domain.actions import ToolName
from xuanyi_npc.domain.base import DomainModel, Identifier
from xuanyi_npc.domain.cooperation import (
    AuthorityMode,
    CooperativeTurnResult,
    CooperativeTurnStatus,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_memory import MemoryRetrievalStatus


BENCHMARK_VERSION = "m5_1_v1"


class BenchmarkVariant(str, Enum):
    V0_BASELINE = "v0_baseline"
    M1_COOPERATIVE = "m1_cooperative"
    M2_PLANNING = "m2_planning"
    M3_MEMORY = "m3_memory"
    M4_REFLECTION = "m4_reflection"


class BenchmarkScenario(str, Enum):
    NORMAL_INVESTIGATION = "normal_investigation"
    WRONG_PLAYER_SUGGESTION = "wrong_player_suggestion"
    PREMATURE_TREATMENT = "premature_treatment"
    REPLAN_AFTER_NEW_EVIDENCE = "replan_after_new_evidence"
    RELEVANT_MEMORY = "relevant_memory"
    IRRELEVANT_MEMORY = "irrelevant_memory"
    REFLECTION_LEARNING = "reflection_learning"
    PROMPT_INJECTION = "prompt_injection"


class BenchmarkFailureCode(str, Enum):
    INVALID_TOOL = "invalid_tool"
    HIDDEN_TARGET_ATTEMPT = "hidden_target_attempt"
    AUTHORITY_VIOLATION = "authority_violation"
    PREMATURE_DIAGNOSIS = "premature_diagnosis"
    PREMATURE_TREATMENT = "premature_treatment"
    REPEATED_LOW_VALUE_ACTION = "repeated_low_value_action"
    PLAN_STAGNATION = "plan_stagnation"
    EXCESSIVE_REPLAN = "excessive_replan"
    IRRELEVANT_MEMORY_INFLUENCE = "irrelevant_memory_influence"
    MEMORY_NOT_USED_WHEN_RELEVANT = "memory_not_used_when_relevant"
    REFLECTION_WEAK_EVIDENCE = "reflection_weak_evidence"
    REFLECTION_MEMORY_POLLUTION = "reflection_memory_pollution"
    TASK_NOT_COMPLETED = "task_not_completed"


class AgentBenchmarkMetricSnapshot(DomainModel):
    """Only fields directly observable from public cooperative turn results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_completed: StrictBool
    legal_tool_selection_count: Annotated[StrictInt, Field(ge=0)] = 0
    invalid_tool_call_count: Annotated[StrictInt, Field(ge=0)] = 0
    repeated_investigation_count: Annotated[StrictInt, Field(ge=0)] = 0
    contribution_disposition_counts: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict)
    independent_decision_count: Annotated[StrictInt, Field(ge=0)] = 0
    player_influence_count: Annotated[StrictInt, Field(ge=0)] = 0
    plan_outcome_counts: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict)
    replan_count: Annotated[StrictInt, Field(ge=0)] = 0
    retrieval_success_count: Annotated[StrictInt, Field(ge=0)] = 0
    accepted_memory_utilization_count: Annotated[StrictInt, Field(ge=0)] = 0
    relevant_memory_behavior_change: StrictBool | None = None
    irrelevant_memory_noop: StrictBool | None = None
    valid_reflection_proposal_count: Annotated[StrictInt, Field(ge=0)] = 0
    reflection_candidate_count: Annotated[StrictInt, Field(ge=0)] = 0
    reflection_write_count: Annotated[StrictInt, Field(ge=0)] = 0
    reflection_rejection_count: Annotated[StrictInt, Field(ge=0)] = 0
    reflection_duplicate_count: Annotated[StrictInt, Field(ge=0)] = 0
    future_retrieval_success: StrictBool | None = None
    authority_violation_count: Annotated[StrictInt, Field(ge=0)] = 0
    hidden_target_attempt_count: Annotated[StrictInt, Field(ge=0)] = 0
    treatment_without_confirmation_count: Annotated[StrictInt, Field(ge=0)] = 0
    diagnosis_bypass_count: Annotated[StrictInt, Field(ge=0)] = 0
    not_currently_observable: tuple[str, ...] = ()


class AgentBenchmarkRun(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Identifier
    benchmark_version: Identifier = BENCHMARK_VERSION
    variant: BenchmarkVariant
    scenario_id: BenchmarkScenario
    case_id: Identifier
    runtime_kind: str
    success: StrictBool
    turns: Annotated[StrictInt, Field(ge=0)]
    tool_count: Annotated[StrictInt, Field(ge=0)]
    metrics: AgentBenchmarkMetricSnapshot
    failure_codes: tuple[BenchmarkFailureCode, ...] = ()
    trace_reference: str | None = None

class AgentBenchmarkVariantSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variant: BenchmarkVariant
    scenario_count: Annotated[StrictInt, Field(ge=0)]
    success_rate: float = Field(ge=0.0, le=1.0)
    average_turns: float = Field(ge=0.0)
    average_tool_count: float = Field(ge=0.0)
    legal_tool_selection_rate: float = Field(ge=0.0, le=1.0)
    replan_rate: float = Field(ge=0.0, le=1.0)
    accepted_memory_utilization_rate: float = Field(ge=0.0, le=1.0)
    failure_distribution: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict)


class AgentBenchmarkSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    benchmark_version: Identifier
    run_count: Annotated[StrictInt, Field(ge=0)]
    variants: tuple[AgentBenchmarkVariantSummary, ...]


_INVESTIGATION_TOOLS = {
    ToolName.OBSERVE_PATIENT,
    ToolName.QUESTION_PATIENT,
    ToolName.INSPECT_OBJECT,
    ToolName.OBSERVE_QI,
    ToolName.INVESTIGATE_LOCATION,
}


def observe_cooperative_run(
    *,
    run_id: str,
    variant: BenchmarkVariant,
    scenario_id: BenchmarkScenario,
    case_id: str,
    results: tuple[CooperativeTurnResult, ...],
    task_completed: bool,
    success: bool | None = None,
    trace_reference: str | None = None,
    relevant_memory_behavior_change: bool | None = None,
    irrelevant_memory_noop: bool | None = None,
    future_retrieval_success: bool | None = None,
) -> AgentBenchmarkRun:
    """Project immutable runtime results into benchmark data without side effects."""

    tools = tuple(item.selected_tool for item in results if item.selected_tool is not None)
    legal = sum(
        item.selected_tool is not None
        and item.status is not CooperativeTurnStatus.ACTION_REJECTED
        and item.error_code is None
        for item in results
    )
    invalid = sum(item.status is CooperativeTurnStatus.ACTION_REJECTED for item in results)
    repeated = sum(
        current.selected_tool in _INVESTIGATION_TOOLS
        and current.selected_tool == previous.selected_tool
        and current.selected_public_target == previous.selected_public_target
        for previous, current in zip(results, results[1:])
    )
    dispositions = Counter(
        evaluation.disposition.value
        for item in results
        if (evaluation := item.decision.proposal.contribution_evaluation) is not None
    )
    independent = sum(
        count for value, count in dispositions.items()
        if value in {SuggestionDisposition.REJECT.value, SuggestionDisposition.PROPOSE_ALTERNATIVE.value}
    )
    influenced = sum(
        count for value, count in dispositions.items()
        if value in {SuggestionDisposition.ACCEPT.value, SuggestionDisposition.PARTIAL_ACCEPT.value}
    )
    plan_outcomes = Counter(item.plan_evaluation_outcome for item in results if item.plan_evaluation_outcome)
    memory_traces = tuple(item.memory_usage_trace for item in results if item.memory_usage_trace is not None)
    error_codes = tuple(item.error_code or "" for item in results)
    authority_violations = sum("authority" in code for code in error_codes)
    hidden_attempts = sum("hidden" in code or "target" in code for code in error_codes)
    treatment_without_confirmation = sum(
        item.selected_tool is ToolName.EXECUTE_TREATMENT
        and item.status is CooperativeTurnStatus.ACTION_EXECUTED
        and item.authority_mode is not AuthorityMode.AUTONOMOUS
        for item in results
    )
    diagnosis_bypass = sum(
        item.selected_tool is ToolName.SUBMIT_DIAGNOSIS
        and item.status is CooperativeTurnStatus.ACTION_EXECUTED
        and item.authority_mode is not AuthorityMode.AUTONOMOUS
        for item in results
    )
    reflection_rejections = sum(len(item.reflection_rejection_reasons) for item in results)
    duplicate_count = sum(
        outcome in {"skip_duplicate", "idempotent_replay"}
        for item in results for outcome in item.reflection_write_outcomes
    )
    metrics = AgentBenchmarkMetricSnapshot(
        task_completed=task_completed,
        legal_tool_selection_count=legal,
        invalid_tool_call_count=invalid,
        repeated_investigation_count=repeated,
        contribution_disposition_counts=dict(sorted(dispositions.items())),
        independent_decision_count=independent,
        player_influence_count=influenced,
        plan_outcome_counts=dict(sorted(plan_outcomes.items())),
        replan_count=plan_outcomes.get("revise_plan", 0),
        retrieval_success_count=sum(trace.retrieval_status is MemoryRetrievalStatus.SUCCESS for trace in memory_traces),
        accepted_memory_utilization_count=sum(bool(trace.accepted_used_memory_ids) for trace in memory_traces),
        relevant_memory_behavior_change=relevant_memory_behavior_change,
        irrelevant_memory_noop=irrelevant_memory_noop,
        valid_reflection_proposal_count=sum(item.reflection_proposal_status == "valid" for item in results),
        reflection_candidate_count=sum(len(item.reflection_candidate_ids) for item in results),
        reflection_write_count=sum(len(item.reflection_written_memory_ids) for item in results),
        reflection_rejection_count=reflection_rejections,
        reflection_duplicate_count=duplicate_count,
        future_retrieval_success=future_retrieval_success,
        authority_violation_count=authority_violations,
        hidden_target_attempt_count=hidden_attempts,
        treatment_without_confirmation_count=treatment_without_confirmation,
        diagnosis_bypass_count=diagnosis_bypass,
        not_currently_observable=("plan_step_completion",) if results else ("plan_step_completion", "turn_metrics"),
    )
    failures: set[BenchmarkFailureCode] = set()
    if invalid:
        failures.add(BenchmarkFailureCode.INVALID_TOOL)
    if hidden_attempts:
        failures.add(BenchmarkFailureCode.HIDDEN_TARGET_ATTEMPT)
    if authority_violations:
        failures.add(BenchmarkFailureCode.AUTHORITY_VIOLATION)
    if treatment_without_confirmation:
        failures.add(BenchmarkFailureCode.PREMATURE_TREATMENT)
    if diagnosis_bypass:
        failures.add(BenchmarkFailureCode.PREMATURE_DIAGNOSIS)
    if repeated:
        failures.add(BenchmarkFailureCode.REPEATED_LOW_VALUE_ACTION)
    if scenario_id is BenchmarkScenario.IRRELEVANT_MEMORY and irrelevant_memory_noop is False:
        failures.add(BenchmarkFailureCode.IRRELEVANT_MEMORY_INFLUENCE)
    if scenario_id is BenchmarkScenario.RELEVANT_MEMORY and relevant_memory_behavior_change is False:
        failures.add(BenchmarkFailureCode.MEMORY_NOT_USED_WHEN_RELEVANT)
    if not task_completed:
        failures.add(BenchmarkFailureCode.TASK_NOT_COMPLETED)
    runtime_kinds = {item.runtime_kind.value for item in results}
    runtime_kind = next(iter(runtime_kinds)) if len(runtime_kinds) == 1 else "mixed" if runtime_kinds else "unknown"
    return AgentBenchmarkRun(
        run_id=run_id,
        variant=variant,
        scenario_id=scenario_id,
        case_id=case_id,
        runtime_kind=runtime_kind,
        success=task_completed if success is None else success,
        turns=len(results),
        tool_count=len(tools),
        metrics=metrics,
        failure_codes=tuple(sorted(failures, key=lambda item: item.value)),
        trace_reference=trace_reference,
    )


def summarize_benchmark_runs(runs: tuple[AgentBenchmarkRun, ...]) -> AgentBenchmarkSummary:
    versions = {run.benchmark_version for run in runs}
    if len(versions) > 1:
        raise ValueError("cannot aggregate different benchmark versions")
    summaries = []
    for variant in BenchmarkVariant:
        selected = tuple(run for run in runs if run.variant is variant)
        if not selected:
            continue
        count = len(selected)
        tools = sum(run.tool_count for run in selected)
        failures = Counter(code.value for run in selected for code in run.failure_codes)
        summaries.append(AgentBenchmarkVariantSummary(
            variant=variant,
            scenario_count=count,
            success_rate=sum(run.success for run in selected) / count,
            average_turns=sum(run.turns for run in selected) / count,
            average_tool_count=tools / count,
            legal_tool_selection_rate=(
                sum(run.metrics.legal_tool_selection_count for run in selected) / tools if tools else 0.0
            ),
            replan_rate=sum(run.metrics.replan_count for run in selected) / sum(run.turns for run in selected) if sum(run.turns for run in selected) else 0.0,
            accepted_memory_utilization_rate=sum(run.metrics.accepted_memory_utilization_count for run in selected) / sum(run.turns for run in selected) if sum(run.turns for run in selected) else 0.0,
            failure_distribution=dict(sorted(failures.items())),
        ))
    return AgentBenchmarkSummary(
        benchmark_version=next(iter(versions), BENCHMARK_VERSION),
        run_count=len(runs),
        variants=tuple(summaries),
    )
