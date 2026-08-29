"""Shared bounded structured-output execution used by V0 and cooperative agents."""

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from pydantic import ValidationError

from .model_usage import AgentRepairKind, ModelUsage

from .llm import LLMAdapter, LLMAdapterError, LLMRequest, LLMResponse


OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class BoundedAttemptTelemetry:
    attempt_index: int
    attempt_kind: str
    provider_request_id: str | None
    configured_max_output_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None
    response_returned: bool
    failure_stage: str | None = None
    failure_code: str | None = None
    exception_class: str | None = None
    field_path: str | None = None
    error_count: int | None = None
    plan_first_step_intent: str | None = None
    plan_first_step_tool: str | None = None
    plan_first_step_public_target: str | None = None
    decision_action_type: str | None = None
    decision_tool: str | None = None
    decision_public_target: str | None = None


@dataclass(frozen=True)
class BoundedOutputResult(Generic[OutputT]):
    output: OutputT | None
    attempts: int
    repair_kind: AgentRepairKind | None
    usages: tuple[ModelUsage, ...]
    failure_stage: str | None = None
    failure_code: str | None = None
    exception_class: str | None = None
    finish_reason: str | None = None
    configured_max_output_tokens: int | None = None
    attempt_telemetry: tuple[BoundedAttemptTelemetry, ...] = ()
    repair_attempted: bool = False
    repair_succeeded: bool = False


class BoundedStructuredOutput:
    """One initial model call and at most one format-repair call."""

    def __init__(self, adapter: LLMAdapter, diagnostic_hook: Callable[[str, dict], None] | None = None) -> None:
        self.adapter = adapter
        self.diagnostic_hook = diagnostic_hook

    def _emit(self, event: str, **data) -> None:
        if self.diagnostic_hook is not None:
            self.diagnostic_hook(event, data)

    def run(
        self,
        request: LLMRequest,
        *,
        parse: Callable[[LLMResponse], OutputT],
        repair_request: Callable[[LLMRequest, LLMResponse, Exception], LLMRequest],
    ) -> BoundedOutputResult[OutputT]:
        responses: list[LLMResponse] = []
        self._emit("attempt_started", attempt_index=1)
        try:
            first = self.adapter.complete(request)
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            self._emit("adapter_error", attempt_index=1, adapter_error_code=code, finish_reason="length" if code == "deepseek_output_truncated" else None)
            if isinstance(exc, LLMAdapterError) and exc.abort_episode:
                raise
            return self.failure_result(
                exc, attempts=1, repair_kind=None,
                attempt_index=1, attempt_kind="initial",
            )
        responses.append(first)
        first_attempt = self.response_attempt(first, 1, "initial")
        self._emit("response_received", attempt_index=1, response_length=len(first.content), finish_reason="stop")
        try:
            output = parse(first)
            self._emit("attempt_succeeded", attempt_index=1)
            return BoundedOutputResult(
                output, 1, None, self.usages(responses),
                attempt_telemetry=(first_attempt,),
            )
        except (ValidationError, ValueError) as error:
            first_attempt = self.validation_failure_attempt(first_attempt, error)
            self._emit("attempt_validation_failed", attempt_index=1, error_code=type(error).__name__)
            self._emit("repair_started", attempt_index=2)
            try:
                repaired = self.adapter.complete(repair_request(request, first, error))
            except Exception as exc:
                code = getattr(exc, "code", type(exc).__name__)
                self._emit("adapter_error", attempt_index=2, adapter_error_code=code, finish_reason="length" if code == "deepseek_output_truncated" else None)
                self._emit("repair_failed", attempt_index=2)
                if isinstance(exc, LLMAdapterError) and exc.abort_episode:
                    exc.prior_usages = (*self.usages(responses), *exc.prior_usages)
                    raise
                return self.failure_result(
                    exc,
                    attempts=2,
                    repair_kind=AgentRepairKind.FORMAT_REPAIR,
                    prior_usages=self.usages(responses),
                    prior_attempts=(first_attempt,),
                    attempt_index=2,
                    attempt_kind="repair",
                )
            responses.append(repaired)
            repair_attempt = self.response_attempt(repaired, 2, "repair")
            self._emit("response_received", attempt_index=2, response_length=len(repaired.content), finish_reason="stop")
            try:
                output = parse(repaired)
            except (ValidationError, ValueError) as error:
                self._emit("attempt_validation_failed", attempt_index=2, error_code=type(error).__name__)
                self._emit("repair_failed", attempt_index=2)
                output = None
                repair_attempt = self.validation_failure_attempt(repair_attempt, error)
            else:
                self._emit("attempt_succeeded", attempt_index=2)
                self._emit("repair_succeeded", attempt_index=2)
            return BoundedOutputResult(
                output,
                2,
                AgentRepairKind.FORMAT_REPAIR,
                self.usages(responses),
                failure_stage=repair_attempt.failure_stage,
                failure_code=repair_attempt.failure_code,
                exception_class=repair_attempt.exception_class,
                finish_reason=repair_attempt.finish_reason,
                configured_max_output_tokens=repair_attempt.configured_max_output_tokens,
                attempt_telemetry=(first_attempt, repair_attempt),
                repair_attempted=True,
                repair_succeeded=output is not None,
            )

    @staticmethod
    def usages(responses: list[LLMResponse]) -> tuple[ModelUsage, ...]:
        return tuple(item.usage for item in responses if item.usage is not None)

    @staticmethod
    def usage_from_error(error: Exception) -> tuple[ModelUsage, ...]:
        if isinstance(error, LLMAdapterError) and error.usage is not None:
            return (error.usage,)
        return ()

    @classmethod
    def failure_result(
        cls,
        error: Exception,
        *,
        attempts: int,
        repair_kind: AgentRepairKind | None,
        prior_usages: tuple[ModelUsage, ...] = (),
        prior_attempts: tuple[BoundedAttemptTelemetry, ...] = (),
        attempt_index: int,
        attempt_kind: str,
    ) -> BoundedOutputResult:
        usage = error.usage if isinstance(error, LLMAdapterError) else None
        attempt = BoundedAttemptTelemetry(
            attempt_index=attempt_index,
            attempt_kind=attempt_kind,
            provider_request_id=usage.provider_request_id if usage else None,
            configured_max_output_tokens=getattr(
                error, "configured_max_output_tokens", None
            ),
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            finish_reason=getattr(error, "finish_reason", None),
            response_returned=False,
            failure_stage=getattr(error, "failure_stage", "adapter"),
            failure_code=getattr(error, "code", type(error).__name__),
            exception_class=type(error).__name__,
        )
        return BoundedOutputResult(
            output=None,
            attempts=attempts,
            repair_kind=repair_kind,
            usages=(*prior_usages, *cls.usage_from_error(error)),
            failure_stage=getattr(error, "failure_stage", "adapter"),
            failure_code=getattr(error, "code", type(error).__name__),
            exception_class=type(error).__name__,
            finish_reason=getattr(error, "finish_reason", None),
            configured_max_output_tokens=getattr(
                error, "configured_max_output_tokens", None
            ),
            attempt_telemetry=(*prior_attempts, attempt),
            repair_attempted=attempt_index == 2,
            repair_succeeded=False,
        )

    def response_attempt(
        self, response: LLMResponse, attempt_index: int, attempt_kind: str
    ) -> BoundedAttemptTelemetry:
        usage = response.usage
        config = getattr(self.adapter, "config", None)
        configured_max = getattr(config, "max_output_tokens", None)
        return BoundedAttemptTelemetry(
            attempt_index=attempt_index,
            attempt_kind=attempt_kind,
            provider_request_id=usage.provider_request_id if usage else None,
            configured_max_output_tokens=(
                configured_max if isinstance(configured_max, int) else None
            ),
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            finish_reason="stop",
            response_returned=True,
        )

    @staticmethod
    def validation_failure_attempt(
        attempt: BoundedAttemptTelemetry, error: Exception
    ) -> BoundedAttemptTelemetry:
        if isinstance(error, ValidationError):
            errors = error.errors(include_input=False, include_url=False)
            first = errors[0] if errors else None
            failure_code = first["type"] if first is not None else "ValidationError"
            field_path = (
                ".".join(str(item) for item in first["loc"])
                if first is not None else None
            )
            error_count = len(errors)
        else:
            failure_code = getattr(error, "code", type(error).__name__)
            field_path = getattr(error, "field_path", None)
            error_count = getattr(error, "error_count", None)
        return BoundedAttemptTelemetry(
            **{
                **attempt.__dict__,
                "failure_stage": getattr(error, "failure_stage", "validation"),
                "failure_code": failure_code,
                "exception_class": getattr(
                    error, "source_exception_class", type(error).__name__
                ),
                "field_path": field_path,
                "error_count": error_count,
                **getattr(error, "sanitized_proposal_summary", {}),
            }
        )
