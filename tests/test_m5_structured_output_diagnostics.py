from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.agents.bounded_output import BoundedStructuredOutput
from xuanyi_npc.evaluation.structured_output_diagnostics import (
    CapturingAdapter,
    PlanningTelemetryCollector,
    StructuredFailureStage,
    diagnose_captured_responses,
)


class FakeAdapter:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def complete(self, request):
        return LLMResponse(content=self.outputs.pop(0))


def test_diagnostics_distinguish_malformed_and_schema_mismatch_without_raw_content() -> None:
    capture = CapturingAdapter(FakeAdapter(("not json", '{"action_id":"npc_turn"}')))
    request = type("Request", (), {"response_schema": {"title": "GameNPCTurnProposal"}})()
    capture.complete(request)
    capture.complete(request)
    report = diagnose_captured_responses(model_name="fake", capture=capture)
    assert report.attempts[0].stage is StructuredFailureStage.MALFORMED_JSON
    assert report.attempts[1].stage is StructuredFailureStage.SCHEMA_MISMATCH
    assert report.attempts[1].top_level_json_keys == ("action_id",)
    assert {item.path for item in report.attempts[1].validation_issues} == {
        ("goal_update",), ("plan_update",), ("decision",), ("action_id",)
    }
    assert "not json" not in report.model_dump_json()


def test_adapter_failure_is_not_misclassified_as_repair_exhaustion() -> None:
    class TruncatedAdapter:
        def complete(self, request):
            error = RuntimeError("private provider detail")
            error.code = "deepseek_output_truncated"
            raise error

    capture = CapturingAdapter(TruncatedAdapter())
    request = type("Request", (), {"response_schema": {"title": "GameNPCTurnProposal"}})()
    try:
        capture.complete(request)
    except RuntimeError:
        pass
    report = diagnose_captured_responses(model_name="fake", capture=capture)
    assert report.attempts[0].stage is StructuredFailureStage.PROVIDER_REQUEST_FAILURE
    assert report.attempts[0].adapter_error_code == "deepseek_output_truncated"
    assert len(report.attempts) == 1


def test_stage_telemetry_distinguishes_truncation_from_unreached_parser() -> None:
    collector = PlanningTelemetryCollector(request_id="request_1", run_id="run_1", model="fake", configured_max_output_tokens=2048)
    collector.hook("attempt_started", {"attempt_index": 1})
    collector.hook("adapter_error", {"attempt_index": 1, "adapter_error_code": "deepseek_output_truncated", "finish_reason": "length"})
    collector.hook("fallback_used", {"fallback_reason": "model_output_unavailable"})
    trace = collector.snapshot()
    attempt = trace.attempts[0]
    assert attempt.provider_called is True
    assert attempt.finish_reason == "length"
    assert attempt.parser_reached is False
    assert attempt.parse_success is None
    assert trace.repair_attempted is False
    assert trace.fallback_used is True


def test_stage_telemetry_records_schema_failure_and_repair_success() -> None:
    collector = PlanningTelemetryCollector(request_id="request_2", run_id="run_2", model="fake", configured_max_output_tokens=2048)
    for event, data in (
        ("attempt_started", {"attempt_index": 1}),
        ("response_received", {"attempt_index": 1, "response_length": 20, "finish_reason": "stop"}),
        ("parser_reached", {}),
        ("schema_validation_reached", {}),
        ("schema_validation_failed", {"error_code": "missing", "error_path": ("decision",)}),
        ("parse_failed", {"error_code": "missing"}),
        ("repair_started", {"attempt_index": 2}),
        ("response_received", {"attempt_index": 2, "response_length": 100, "finish_reason": "stop"}),
        ("parser_reached", {}),
        ("schema_validation_reached", {}),
        ("parse_succeeded", {}),
        ("schema_validation_succeeded", {}),
        ("deterministic_validation_reached", {}),
        ("deterministic_validation_succeeded", {}),
        ("repair_succeeded", {"attempt_index": 2}),
    ):
        collector.hook(event, data)
    trace = collector.snapshot()
    assert trace.attempts[0].schema_error_path == ("decision",)
    assert trace.attempts[1].deterministic_validation_success is True
    assert trace.repair_attempted is True
    assert trace.repair_result == "succeeded"
    assert trace.fallback_used is False


def test_stage_telemetry_keeps_ordinary_provider_error_distinct() -> None:
    collector = PlanningTelemetryCollector(request_id="request_3", run_id="run_3", model="fake", configured_max_output_tokens=2048)
    collector.hook("attempt_started", {"attempt_index": 1})
    collector.hook("adapter_error", {"attempt_index": 1, "adapter_error_code": "deepseek_timeout_error", "finish_reason": None})
    attempt = collector.snapshot().attempts[0]
    assert attempt.adapter_error_code == "deepseek_timeout_error"
    assert attempt.finish_reason is None


def test_bounded_direct_success_and_repair_failure_are_observed_without_inference() -> None:
    direct = PlanningTelemetryCollector(request_id="request_4", run_id="run_4", model="fake", configured_max_output_tokens=2048)
    direct_result = BoundedStructuredOutput(FakeAdapter(("valid",)), direct.hook).run(
        object(), parse=lambda response: response.content,
        repair_request=lambda request, response, error: request,
    )
    assert direct_result.output == "valid"
    assert direct.snapshot().attempts[0].provider_response_received is True
    assert direct.snapshot().repair_attempted is False

    failed = PlanningTelemetryCollector(request_id="request_5", run_id="run_5", model="fake", configured_max_output_tokens=2048)
    failed_result = BoundedStructuredOutput(FakeAdapter(("bad", "still bad")), failed.hook).run(
        object(),
        parse=lambda response: (_ for _ in ()).throw(ValueError("invalid")),
        repair_request=lambda request, response, error: request,
    )
    assert failed_result.output is None
    assert failed.snapshot().repair_attempted is True
    assert failed.snapshot().repair_result == "failed"


def test_public_action_summary_and_contract_code_are_sanitized_structured_fields() -> None:
    collector = PlanningTelemetryCollector(request_id="request_6", run_id="run_6", model="fake", configured_max_output_tokens=2048)
    collector.hook("proposal_action_summary", {
        "capability": "use_tool", "action_type": "use_tool", "tool_name": "observe_qi",
        "public_target_id": "investigation_qi", "goal_id": "goal_case", "plan_id": None,
        "plan_step_id": None, "planning_intent": None, "authority_intent": "investigation",
        "argument_keys": ("investigation_id",),
    })
    collector.hook("deterministic_validation_failed", {
        "error_code": "action_mismatch", "error_path": ("decision", "action", "tool_call"),
    })
    attempt = collector.snapshot().attempts[0]
    assert attempt.tool_name == "observe_qi"
    assert attempt.public_target_id == "investigation_qi"
    assert attempt.deterministic_error_code == "action_mismatch"
    assert attempt.deterministic_error_path == ("decision", "action", "tool_call")
    assert attempt.argument_keys == ("investigation_id",)
