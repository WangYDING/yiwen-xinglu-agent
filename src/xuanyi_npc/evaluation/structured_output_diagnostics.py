"""Sanitized M5-4 diagnostics for real GameNPCTurnProposal responses."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError

from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.domain.planning_contract import GameNPCTurnProposal


class StructuredFailureStage(str, Enum):
    PROVIDER_REQUEST_FAILURE = "provider_request_failure"
    PROVIDER_RESPONSE_EMPTY = "provider_response_empty"
    MALFORMED_JSON = "malformed_json"
    SCHEMA_MISMATCH = "schema_mismatch"
    SCHEMA_PARSE_SUCCESS = "schema_parse_success"


class SanitizedValidationIssue(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    path: tuple[str, ...] = ()


class StructuredAttemptDiagnostic(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_index: int = Field(ge=1, le=2)
    response_received: bool
    response_length: int = Field(ge=0)
    top_level_json_keys: tuple[str, ...] = ()
    stage: StructuredFailureStage
    validation_issues: tuple[SanitizedValidationIssue, ...] = ()
    adapter_error_code: str | None = None
    finish_reason: str | None = None


class StructuredOutputRootCauseReport(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    structured_output_mode: str
    provider_schema_sent: bool
    requested_schema_title: str | None = None
    configured_output_token_limit: int | None = Field(default=None, ge=1)
    attempts: tuple[StructuredAttemptDiagnostic, ...]


class PlanningAttemptTelemetry(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_index: int = Field(ge=1, le=2)
    provider_called: bool = False
    provider_response_received: bool | None = None
    response_length: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    adapter_error_code: str | None = None
    parser_reached: bool = False
    parse_success: bool | None = None
    schema_validation_reached: bool = False
    schema_validation_success: bool | None = None
    schema_error_code: str | None = None
    schema_error_path: tuple[str, ...] = ()
    deterministic_validation_reached: bool = False
    deterministic_validation_success: bool | None = None
    deterministic_error_code: str | None = None
    deterministic_error_path: tuple[str, ...] = ()
    capability: str | None = None
    action_type: str | None = None
    tool_name: str | None = None
    public_target_id: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    plan_step_id: str | None = None
    planning_intent: str | None = None
    argument_keys: tuple[str, ...] = ()
    authority_intent: str | None = None


class PlanningStructuredOutputTelemetry(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    run_id: str
    request_kind: str = "game_npc_planning"
    model: str
    configured_max_output_tokens: int = Field(ge=1)
    attempts: tuple[PlanningAttemptTelemetry, ...]
    repair_attempted: bool = False
    repair_result: str | None = None
    fallback_used: bool = False
    public_fallback_reason: str | None = None


class PlanningTelemetryCollector:
    """Opt-in mutable observer; snapshot is sanitized and immutable."""

    def __init__(self, *, request_id: str, run_id: str, model: str, configured_max_output_tokens: int) -> None:
        self.identity = (request_id, run_id, model, configured_max_output_tokens)
        self.attempts: dict[int, dict] = {}
        self.repair_attempted = False
        self.repair_result = None
        self.fallback_used = False
        self.public_fallback_reason = None
        self.current_attempt = 1

    def hook(self, event: str, data: dict) -> None:
        if "attempt_index" in data:
            self.current_attempt = int(data["attempt_index"])
        index = int(data.get("attempt_index", self.current_attempt))
        attempt = self.attempts.setdefault(index, {"attempt_index": index})
        if event == "attempt_started":
            attempt["provider_called"] = True
        elif event == "response_received":
            attempt.update(provider_response_received=True, response_length=data["response_length"], finish_reason=data.get("finish_reason"))
        elif event == "adapter_error":
            attempt.update(provider_response_received=False, adapter_error_code=data.get("adapter_error_code"), finish_reason=data.get("finish_reason"))
        elif event == "parser_reached":
            attempt["parser_reached"] = True
        elif event == "parse_succeeded":
            attempt["parse_success"] = True
        elif event == "parse_failed":
            attempt["parse_success"] = False
        elif event == "schema_validation_reached":
            attempt["schema_validation_reached"] = True
        elif event == "schema_validation_succeeded":
            attempt["schema_validation_success"] = True
        elif event == "schema_validation_failed":
            attempt.update(schema_validation_success=False, schema_error_code=data.get("error_code"), schema_error_path=data.get("error_path", ()))
        elif event == "deterministic_validation_reached":
            attempt["deterministic_validation_reached"] = True
        elif event == "deterministic_validation_succeeded":
            attempt["deterministic_validation_success"] = True
        elif event == "deterministic_validation_failed":
            attempt.update(deterministic_validation_success=False, deterministic_error_code=data.get("error_code"), deterministic_error_path=data.get("error_path", ()))
        elif event == "proposal_action_summary":
            attempt.update({key: data.get(key) for key in (
                "capability", "action_type", "tool_name", "public_target_id", "goal_id",
                "plan_id", "plan_step_id", "planning_intent", "authority_intent",
                "argument_keys",
            )})
        elif event == "repair_started":
            self.repair_attempted = True
            attempt["provider_called"] = True
        elif event == "repair_succeeded":
            self.repair_result = "succeeded"
        elif event == "repair_failed":
            self.repair_result = "failed"
        elif event == "fallback_used":
            self.fallback_used = True
            self.public_fallback_reason = data.get("fallback_reason")

    def snapshot(self) -> PlanningStructuredOutputTelemetry:
        request_id, run_id, model, limit = self.identity
        return PlanningStructuredOutputTelemetry(
            request_id=request_id,
            run_id=run_id,
            model=model,
            configured_max_output_tokens=limit,
            attempts=tuple(PlanningAttemptTelemetry(**self.attempts[index]) for index in sorted(self.attempts)),
            repair_attempted=self.repair_attempted,
            repair_result=self.repair_result,
            fallback_used=self.fallback_used,
            public_fallback_reason=self.public_fallback_reason,
        )


class CapturingAdapter:
    """In-memory response capture; no prompt, key, or raw response is serialized."""

    def __init__(self, adapter) -> None:
        self.adapter = adapter
        self.responses = []
        self.request_schema_titles = []
        self.failures = []
        self.request_output_limits = []

    def complete(self, request):
        self.request_schema_titles.append(request.response_schema.get("title"))
        self.request_output_limits.append(getattr(request, "max_output_tokens", None))
        try:
            response = self.adapter.complete(request)
        except Exception as error:
            self.failures.append(getattr(error, "code", type(error).__name__))
            raise
        self.responses.append(response)
        return response


def diagnose_captured_responses(*, model_name: str, capture: CapturingAdapter) -> StructuredOutputRootCauseReport:
    attempts = tuple(_diagnose_content(index, response.content) for index, response in enumerate(capture.responses, 1))
    if not attempts and capture.failures:
        attempts = (StructuredAttemptDiagnostic(
            attempt_index=1,
            response_received=False,
            response_length=0,
            stage=StructuredFailureStage.PROVIDER_REQUEST_FAILURE,
            adapter_error_code=capture.failures[0],
            finish_reason="length" if capture.failures[0] == "deepseek_output_truncated" else None,
        ),)
    return StructuredOutputRootCauseReport(
        model_name=model_name,
        structured_output_mode="json_object",
        provider_schema_sent=False,
        requested_schema_title=next((title for title in capture.request_schema_titles if title), None),
        configured_output_token_limit=next((value for value in capture.request_output_limits if value), None),
        attempts=attempts,
    )


def _diagnose_content(index: int, content: str) -> StructuredAttemptDiagnostic:
    if not content.strip():
        return StructuredAttemptDiagnostic(
            attempt_index=index,
            response_received=True,
            response_length=len(content),
            stage=StructuredFailureStage.PROVIDER_RESPONSE_EMPTY,
            finish_reason="stop",
        )
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return StructuredAttemptDiagnostic(
            attempt_index=index,
            response_received=True,
            response_length=len(content),
            stage=StructuredFailureStage.MALFORMED_JSON,
            finish_reason="stop",
        )
    keys = tuple(sorted(str(key) for key in payload)) if isinstance(payload, dict) else ()
    try:
        GameNPCTurnProposal.model_validate(payload)
    except ValidationError as error:
        issues = tuple(
            SanitizedValidationIssue(
                code=item["type"],
                path=tuple(str(value) for value in item["loc"]),
            )
            for item in error.errors(include_input=False, include_url=False)
        )
        return StructuredAttemptDiagnostic(
            attempt_index=index,
            response_received=True,
            response_length=len(content),
            top_level_json_keys=keys,
            stage=StructuredFailureStage.SCHEMA_MISMATCH,
            validation_issues=issues,
            finish_reason="stop",
        )
    return StructuredAttemptDiagnostic(
        attempt_index=index,
        response_received=True,
        response_length=len(content),
        top_level_json_keys=keys,
        stage=StructuredFailureStage.SCHEMA_PARSE_SUCCESS,
        finish_reason="stop",
    )


def main() -> int:
    import argparse
    import tempfile

    from xuanyi_npc.agents.deepseek import DeepSeekChatAdapter
    from xuanyi_npc.evaluation.real_agent_benchmark import (
        DeepSeekCooperativePilotExecutor,
        RealBenchmarkCondition,
        RealExecutionRequest,
    )
    from xuanyi_npc.evaluation.agent_benchmark import BenchmarkScenario

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    adapter = DeepSeekChatAdapter.from_env()
    capture = CapturingAdapter(adapter)
    with tempfile.TemporaryDirectory(prefix="xuanyi_m5_diag_") as directory:
        try:
            DeepSeekCooperativePilotExecutor(adapter=capture, artifact_root=Path(directory)).execute(
                RealExecutionRequest(
                    scenario_id=BenchmarkScenario.WRONG_PLAYER_SUGGESTION,
                    condition=RealBenchmarkCondition.STANDARD,
                    repeat_index=0,
                    max_turns=1,
                )
            )
        finally:
            adapter.close()
    report = diagnose_captured_responses(model_name=adapter.config.model, capture=capture)
    Path(args.output).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(report.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
