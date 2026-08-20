"""Shared bounded structured-output execution used by V0 and cooperative agents."""

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from pydantic import ValidationError

from xuanyi_npc.evaluation import AgentRepairKind, ModelUsage

from .llm import LLMAdapter, LLMAdapterError, LLMRequest, LLMResponse


OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class BoundedOutputResult(Generic[OutputT]):
    output: OutputT | None
    attempts: int
    repair_kind: AgentRepairKind | None
    usages: tuple[ModelUsage, ...]


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
            return BoundedOutputResult(None, 1, None, self.usage_from_error(exc))
        responses.append(first)
        self._emit("response_received", attempt_index=1, response_length=len(first.content), finish_reason="stop")
        try:
            output = parse(first)
            self._emit("attempt_succeeded", attempt_index=1)
            return BoundedOutputResult(output, 1, None, self.usages(responses))
        except (ValidationError, ValueError) as error:
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
                return BoundedOutputResult(
                    None,
                    2,
                    AgentRepairKind.FORMAT_REPAIR,
                    (*self.usages(responses), *self.usage_from_error(exc)),
                )
            responses.append(repaired)
            self._emit("response_received", attempt_index=2, response_length=len(repaired.content), finish_reason="stop")
            try:
                output = parse(repaired)
            except (ValidationError, ValueError) as error:
                self._emit("attempt_validation_failed", attempt_index=2, error_code=type(error).__name__)
                self._emit("repair_failed", attempt_index=2)
                output = None
            else:
                self._emit("attempt_succeeded", attempt_index=2)
                self._emit("repair_succeeded", attempt_index=2)
            return BoundedOutputResult(
                output,
                2,
                AgentRepairKind.FORMAT_REPAIR,
                self.usages(responses),
            )

    @staticmethod
    def usages(responses: list[LLMResponse]) -> tuple[ModelUsage, ...]:
        return tuple(item.usage for item in responses if item.usage is not None)

    @staticmethod
    def usage_from_error(error: Exception) -> tuple[ModelUsage, ...]:
        if isinstance(error, LLMAdapterError) and error.usage is not None:
            return (error.usage,)
        return ()
