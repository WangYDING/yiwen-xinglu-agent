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

    def __init__(self, adapter: LLMAdapter) -> None:
        self.adapter = adapter

    def run(
        self,
        request: LLMRequest,
        *,
        parse: Callable[[LLMResponse], OutputT],
        repair_request: Callable[[LLMRequest, LLMResponse, Exception], LLMRequest],
    ) -> BoundedOutputResult[OutputT]:
        responses: list[LLMResponse] = []
        try:
            first = self.adapter.complete(request)
        except Exception as exc:
            if isinstance(exc, LLMAdapterError) and exc.abort_episode:
                raise
            return BoundedOutputResult(None, 1, None, self.usage_from_error(exc))
        responses.append(first)
        try:
            return BoundedOutputResult(parse(first), 1, None, self.usages(responses))
        except (ValidationError, ValueError) as error:
            try:
                repaired = self.adapter.complete(repair_request(request, first, error))
            except Exception as exc:
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
            try:
                output = parse(repaired)
            except (ValidationError, ValueError):
                output = None
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

