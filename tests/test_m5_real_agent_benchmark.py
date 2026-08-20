import json
import time

import pytest

from xuanyi_npc.domain.actions import ToolName
from xuanyi_npc.domain.cooperative_memory import (
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
    MemoryUsageTrace,
)
from xuanyi_npc.evaluation import (
    AgentBenchmarkInitialConditions,
    BenchmarkExecutionMode,
    BenchmarkScenario,
    ModelUsage,
    RealAgentBenchmarkRunner,
    RealBenchmarkCondition,
    RealBenchmarkConfig,
    RealBenchmarkFailureCode,
    RealExecutionResult,
    RealModelUnavailableError,
    StructuredOutputFailure,
)

from .test_m5_agent_benchmark import turn


CONDITIONS = AgentBenchmarkInitialConditions(
    public_state_fingerprint="public_revision_0",
    contribution_fingerprint="same_public_contribution",
    authority_fingerprint="npc_authority_v1",
)


def usage():
    return ModelUsage(
        provider_model="fake-real-model",
        input_tokens=100,
        output_tokens=20,
        cache_hit_input_tokens=0,
        cache_miss_input_tokens=100,
        reasoning_tokens=0,
        latency_ms=12.5,
    )


class FakeRealExecutor:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        selected = ToolName.QUESTION_PATIENT
        memory_trace = None
        behavior_changed = None
        if request.condition is RealBenchmarkCondition.RELEVANT_MEMORY:
            selected = ToolName.OBSERVE_QI
            memory_trace = MemoryUsageTrace(
                retrieval_id="retrieval_real",
                retrieval_status=MemoryRetrievalStatus.SUCCESS,
                candidate_memory_ids=("memory_real",),
                selected_memory_ids=("memory_real",),
                declared_used_memory_ids=("memory_real",),
                accepted_used_memory_ids=("memory_real",),
                influence_types=("tool_priority",),
                attribution_status=MemoryUsageAttributionStatus.ACCEPTED,
                decision_influenced=True,
                tool_priority_influenced=True,
            )
            behavior_changed = True
        result = turn(
            f"turn_real_{request.repeat_index}_{request.condition.value}",
            tool=selected,
            target=f"investigation_{selected.value}",
        )
        decision = result.decision.model_copy(update={
            "llm_attempts": 2 if request.repeat_index == 1 else 1,
            "repair_kind": "format_repair" if request.repeat_index == 1 else None,
            "usages": (usage(),),
        })
        result = result.model_copy(update={"decision": decision, "memory_usage_trace": memory_trace})
        return RealExecutionResult(
            case_id="case_real_pilot",
            results=(result,),
            task_completed=True,
            scenario_success=True,
            initial_conditions=CONDITIONS,
            public_contribution="公开的 deterministic fake contribution",
            trace_reference=f"fake:{request.scenario_id.value}:{request.repeat_index}",
            relevant_memory_behavior_change=behavior_changed,
        )


def test_runner_repeats_real_scenarios_aggregates_stability_usage_and_memory_pair(tmp_path) -> None:
    executor = FakeRealExecutor()
    config = RealBenchmarkConfig(
        model_name="fake-real-model",
        scenario_ids=(BenchmarkScenario.PROMPT_INJECTION, BenchmarkScenario.RELEVANT_MEMORY),
        repeats=3,
        output_path=str(tmp_path / "report.json"),
    )
    report = RealAgentBenchmarkRunner(executor=executor).run(config)

    assert len(report.runs) == 9
    assert {run.execution_mode for run in report.runs} == {BenchmarkExecutionMode.REAL_LLM}
    assert [run.repeat_index for run in report.runs[:3]] == [0, 1, 2]
    assert report.total_input_tokens == 900
    assert report.total_output_tokens == 180
    assert report.total_tokens == 1080
    assert report.total_latency_ms == 112.5
    prompt = next(item for item in report.scenario_summaries if item.scenario_id is BenchmarkScenario.PROMPT_INJECTION)
    assert prompt.success_rate == 1.0
    assert prompt.authority_violation_rate == 0.0
    assert prompt.repair_rate == pytest.approx(1 / 3)
    pair = report.paired_summaries[0]
    assert pair.comparable_repeat_count == 3
    assert pair.behavior_change_frequency == 1.0
    assert pair.accepted_memory_usage_frequency == 1.0
    assert pair.legal_behavior_change_frequency == 1.0
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["config"]["repeats"] == 3


def test_json_and_jsonl_are_stable_and_contain_no_private_prompt(tmp_path) -> None:
    runner = RealAgentBenchmarkRunner(executor=FakeRealExecutor())
    report = runner.run(RealBenchmarkConfig(
        model_name="fake-real-model",
        scenario_ids=(BenchmarkScenario.WRONG_PLAYER_SUGGESTION,),
        repeats=1,
    ))
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    runner.write_jsonl(report, first)
    runner.write_jsonl(report, second)
    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert "api_key" not in text.lower()
    assert "raw_prompt" not in text.lower()


class ErrorExecutor:
    def __init__(self, error):
        self.error = error

    def execute(self, request):
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (RealModelUnavailableError(), RealBenchmarkFailureCode.MODEL_UNAVAILABLE),
        (StructuredOutputFailure(), RealBenchmarkFailureCode.STRUCTURED_OUTPUT_FAILURE),
        (RuntimeError("private detail"), RealBenchmarkFailureCode.UNEXPECTED_RUNNER_ERROR),
    ),
)
def test_runner_maps_errors_without_leaking_exception_text(error, expected) -> None:
    report = RealAgentBenchmarkRunner(executor=ErrorExecutor(error)).run(RealBenchmarkConfig(
        model_name="unavailable-model",
        scenario_ids=(BenchmarkScenario.PROMPT_INJECTION,),
        repeats=1,
    ))
    run = report.runs[0]
    assert run.model_failure_codes == (expected,)
    assert "private detail" not in run.model_dump_json()
    assert report.failure_distribution == {expected.value: 1}


class SlowExecutor:
    def execute(self, request):
        time.sleep(0.05)
        raise AssertionError("result should arrive after timeout")


def test_timeout_is_bounded_and_mapped() -> None:
    report = RealAgentBenchmarkRunner(executor=SlowExecutor()).run(RealBenchmarkConfig(
        model_name="slow-model",
        scenario_ids=(BenchmarkScenario.PROMPT_INJECTION,),
        repeats=1,
        timeout_seconds=0.01,
    ))
    assert report.runs[0].model_failure_codes == (RealBenchmarkFailureCode.MODEL_TIMEOUT,)


def test_execution_modes_remain_explicitly_separate() -> None:
    real = RealBenchmarkConfig(model_name="model", repeats=1)
    deterministic = real.model_copy(update={"execution_mode": BenchmarkExecutionMode.DETERMINISTIC})
    assert real.execution_mode is BenchmarkExecutionMode.REAL_LLM
    assert deterministic.execution_mode is BenchmarkExecutionMode.DETERMINISTIC


class PublicFallbackExecutor(FakeRealExecutor):
    def execute(self, request):
        execution = super().execute(request)
        result = execution.results[0]
        evaluation = result.decision.proposal.contribution_evaluation.model_copy(update={
            "reason_code": "model_output_unavailable",
        })
        proposal = result.decision.proposal.model_copy(update={"contribution_evaluation": evaluation})
        decision = result.decision.model_copy(update={"proposal": proposal, "usages": ()})
        return execution.model_copy(update={"results": (result.model_copy(update={"decision": decision}),)})


def test_public_fallback_reason_is_counted_when_planning_metadata_is_not_projected() -> None:
    report = RealAgentBenchmarkRunner(executor=PublicFallbackExecutor()).run(RealBenchmarkConfig(
        model_name="fake-real-model",
        scenario_ids=(BenchmarkScenario.PROMPT_INJECTION,),
        repeats=1,
    ))
    run = report.runs[0]
    assert run.fallback_count == 1
    assert run.repair_count == 1
    assert run.model_call_count == 2
    assert run.model_failure_codes == (
        RealBenchmarkFailureCode.FALLBACK_USED,
        RealBenchmarkFailureCode.REPAIR_EXHAUSTED,
    )
    assert run.total_tokens is None
