from decimal import Decimal
from types import SimpleNamespace

from xuanyi_npc.agents.bounded_output import BoundedAttemptTelemetry
from xuanyi_npc.agents.deepseek import DeepSeekRequestBudgetGuard
from xuanyi_npc.agents.model_usage import ModelUsage
from xuanyi_npc.evaluation.v2_runner import (
    append_exception_turn_events,
    provider_budget_snapshot,
    turn_usage_incomplete,
)


def _usage(request_id: str = "req_exception") -> ModelUsage:
    return ModelUsage(
        provider_model="deepseek-flash",
        input_tokens=100,
        output_tokens=20,
        cache_hit_input_tokens=0,
        cache_miss_input_tokens=100,
        reasoning_tokens=0,
        latency_ms=12.5,
        estimated_cost=Decimal("0.0123"),
        cost_currency="CNY",
        provider_request_id=request_id,
        system_fingerprint="fp_test",
    )


def _attempt(*, request_id="req_exception", content="{}"):
    return BoundedAttemptTelemetry(
        attempt_index=1,
        attempt_kind="initial",
        provider_request_id=request_id,
        configured_max_output_tokens=2048,
        input_tokens=100,
        output_tokens=20,
        finish_reason="stop",
        response_returned=True,
        duration_ms=12.5,
        response_content=content,
        failure_stage="goal_plan_policy",
        failure_code="GoalPlanPolicyError",
        exception_class="GoalPlanPolicyError",
        field_path="plan_update.update",
    )


class _Agent:
    def __init__(self, *, usages):
        self.execution = SimpleNamespace(
            usages=usages,
            attempt_telemetry=(_attempt(),),
            output=None,
            failure_code="planning_output_invalid",
        )

    def last_planning_input(self):
        return None

    def last_planning_execution(self):
        return self.execution

    def last_planning_proposal(self):
        return SimpleNamespace(model_dump=lambda mode: {"safe": "fallback"})


def test_runtime_exception_preserves_completed_attempt_usage_and_validation_evidence():
    events = []

    recovered, unknown = append_exception_turn_events(
        events, run_id="t01_r01", turn=9, agent=_Agent(usages=(_usage(),)),
        error=RuntimeError("later runtime policy failure"),
    )

    assert recovered == (_usage(),)
    assert unknown is False
    attempt = next(item for item in events if item.event_type == "model_request_finished")
    assert attempt.data["usage_status"] == "KNOWN"
    assert attempt.data["duration_ms"] == 12.5
    assert attempt.data["structured_output"] == "{}"
    assert attempt.data["validation_error_code"] == "GoalPlanPolicyError"
    assert any(item.event_type == "proposal_finalized" for item in events)
    assert events[-1].event_type == "runtime_exception"


def test_missing_provider_usage_is_unknown_not_zero():
    events = []

    recovered, unknown = append_exception_turn_events(
        events, run_id="t01_r01", turn=9, agent=_Agent(usages=()),
        error=RuntimeError("later runtime policy failure"),
    )

    assert recovered == ()
    assert unknown is True
    attempt = next(item for item in events if item.event_type == "model_request_finished")
    assert attempt.data["usage_status"] == "UNKNOWN"
    assert attempt.data["estimated_cost"] is None


def test_successful_turn_with_returned_response_but_no_usage_is_incomplete():
    agent = _Agent(usages=())
    result = SimpleNamespace(decision=SimpleNamespace(usages=()))

    assert turn_usage_incomplete(agent, result) is True


def test_budget_snapshot_is_available_independently_of_turn_artifacts():
    guard = DeepSeekRequestBudgetGuard(Decimal("2.00"))
    adapter = SimpleNamespace(request_budget=guard)

    snapshot = provider_budget_snapshot(adapter)

    assert snapshot == {
        "max_cost_cny": "2.00",
        "known_cost_cny": "0",
        "maximum_committed_cost_cny": "0",
        "can_start_episode": True,
        "halted": False,
        "stop_reason": None,
    }
