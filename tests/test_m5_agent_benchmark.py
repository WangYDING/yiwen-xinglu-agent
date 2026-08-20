import json

from xuanyi_npc.domain.actions import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind,
    AuthorityMode,
    CooperativeTurnResult,
    CooperativeTurnStatus,
    GameNPCDecision,
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContributionEvaluation,
    SuggestionDisposition,
)
from xuanyi_npc.evaluation import (
    BenchmarkFailureCode,
    BenchmarkScenario,
    BenchmarkVariant,
    observe_cooperative_run,
    summarize_benchmark_runs,
)


def turn(
    turn_id: str,
    *,
    tool: ToolName,
    target: str,
    status: CooperativeTurnStatus = CooperativeTurnStatus.ACTION_EXECUTED,
    authority: AuthorityMode = AuthorityMode.AUTONOMOUS,
    disposition: SuggestionDisposition = SuggestionDisposition.ACCEPT,
    error_code: str | None = None,
    plan_outcome: str | None = None,
) -> CooperativeTurnResult:
    decision = GameNPCDecision(
        decision_id=f"decision_{turn_id}",
        turn_id=turn_id,
        proposal=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=turn_id,
                disposition=disposition,
                reason_code="fixture_reason",
                explanation="确定性夹具评价。",
            ),
            capability=NPCCapability.USE_TOOL,
            action=AgentAction(
                action_id=f"action_{turn_id}",
                action_type=AgentActionType.USE_TOOL,
                dialogue="执行公开调查。",
                tool_call=ToolCallRequest(
                    name=tool,
                    arguments={"investigation_id": target},
                ),
                confidence=1.0,
            ),
            explanation="确定性夹具决策。",
        ),
        llm_attempts=1,
        used_fallback=False,
    )
    return CooperativeTurnResult(
        turn_id=turn_id,
        status=status,
        decision=decision,
        runtime_kind=AgentRuntimeKind.TEST_DOUBLE,
        authority_mode=authority,
        selected_tool=tool,
        selected_public_target=target,
        public_rationale="公开理由。",
        error_code=error_code,
        plan_evaluation_outcome=plan_outcome,
    )


def benchmark_run(*, run_id: str, variant: BenchmarkVariant, completed: bool = True):
    return observe_cooperative_run(
        run_id=run_id,
        variant=variant,
        scenario_id=BenchmarkScenario.NORMAL_INVESTIGATION,
        case_id="case_benchmark",
        results=(turn("turn_fixture", tool=ToolName.QUESTION_PATIENT, target="investigation_patient"),),
        task_completed=completed,
        trace_reference="fixture:normal_investigation",
    )


def test_contract_expresses_all_required_variants_and_scenarios() -> None:
    assert {item.name for item in BenchmarkVariant} == {
        "V0_BASELINE", "M1_COOPERATIVE", "M2_PLANNING", "M3_MEMORY", "M4_REFLECTION"
    }
    assert {item.name for item in BenchmarkScenario} == {
        "NORMAL_INVESTIGATION",
        "WRONG_PLAYER_SUGGESTION",
        "PREMATURE_TREATMENT",
        "REPLAN_AFTER_NEW_EVIDENCE",
        "RELEVANT_MEMORY",
        "IRRELEVANT_MEMORY",
        "REFLECTION_LEARNING",
        "PROMPT_INJECTION",
    }


def test_observer_collects_deterministic_tool_cooperation_planning_and_safety_metrics() -> None:
    results = (
        turn(
            "turn_wrong_suggestion",
            tool=ToolName.QUESTION_PATIENT,
            target="investigation_patient",
            disposition=SuggestionDisposition.PROPOSE_ALTERNATIVE,
            plan_outcome="revise_plan",
        ),
        turn(
            "turn_injection",
            tool=ToolName.EXECUTE_TREATMENT,
            target="treatment_herbs",
            status=CooperativeTurnStatus.CONFIRMATION_REQUIRED,
            authority=AuthorityMode.CONFIRMATION_REQUIRED,
            disposition=SuggestionDisposition.REJECT,
        ),
    )
    run = observe_cooperative_run(
        run_id="run_observer",
        variant=BenchmarkVariant.M2_PLANNING,
        scenario_id=BenchmarkScenario.PROMPT_INJECTION,
        case_id="case_benchmark",
        results=results,
        task_completed=True,
    )

    assert run.turns == 2
    assert run.tool_count == 2
    assert run.metrics.legal_tool_selection_count == 2
    assert run.metrics.independent_decision_count == 2
    assert run.metrics.replan_count == 1
    assert run.metrics.treatment_without_confirmation_count == 0
    assert BenchmarkFailureCode.AUTHORITY_VIOLATION not in run.failure_codes
    assert "plan_step_completion" in run.metrics.not_currently_observable


def test_repeated_fixture_is_byte_for_byte_json_reproducible() -> None:
    first = benchmark_run(run_id="run_repeat", variant=BenchmarkVariant.M1_COOPERATIVE)
    second = benchmark_run(run_id="run_repeat", variant=BenchmarkVariant.M1_COOPERATIVE)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert json.loads(first.model_dump_json())["variant"] == "m1_cooperative"


def test_summary_compares_two_variants_and_has_stable_failure_distribution() -> None:
    baseline = benchmark_run(
        run_id="run_baseline",
        variant=BenchmarkVariant.V0_BASELINE,
        completed=False,
    )
    cooperative = benchmark_run(
        run_id="run_cooperative",
        variant=BenchmarkVariant.M1_COOPERATIVE,
    )
    summary = summarize_benchmark_runs((cooperative, baseline))

    assert summary.run_count == 2
    assert [item.variant for item in summary.variants] == [
        BenchmarkVariant.V0_BASELINE,
        BenchmarkVariant.M1_COOPERATIVE,
    ]
    assert summary.variants[0].success_rate == 0.0
    assert summary.variants[0].failure_distribution == {"task_not_completed": 1}
    assert summary.variants[1].success_rate == 1.0
    assert json.loads(summary.model_dump_json())["run_count"] == 2


def test_irrelevant_memory_influence_maps_to_closed_failure_taxonomy() -> None:
    run = observe_cooperative_run(
        run_id="run_irrelevant",
        variant=BenchmarkVariant.M3_MEMORY,
        scenario_id=BenchmarkScenario.IRRELEVANT_MEMORY,
        case_id="case_benchmark",
        results=(turn("turn_irrelevant", tool=ToolName.OBSERVE_QI, target="investigation_qi"),),
        task_completed=True,
        irrelevant_memory_noop=False,
    )

    assert run.failure_codes == (BenchmarkFailureCode.IRRELEVANT_MEMORY_INFLUENCE,)

