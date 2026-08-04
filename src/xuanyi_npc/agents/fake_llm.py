"""Scripted adapter for deterministic demos and automated tests."""

from collections import deque
from collections.abc import Iterable

from .llm import LLMAdapterError, LLMRequest, LLMResponse


ScriptedItem = str | LLMResponse | Exception


class ScriptedFakeLLM:
    """Return predefined responses while recording every received request."""

    def __init__(self, responses: Iterable[ScriptedItem]) -> None:
        self._responses = deque(responses)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise LLMAdapterError("scripted Fake LLM has no response left")
        item = self._responses.popleft()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(content=item)

    @property
    def remaining_responses(self) -> int:
        return len(self._responses)
