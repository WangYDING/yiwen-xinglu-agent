"""Replaceable language-model boundary used by cooperative agents."""

from enum import Enum
from typing import Annotated, Protocol, runtime_checkable

from pydantic import ConfigDict, Field, JsonValue, StrictStr, StringConstraints

from xuanyi_npc.domain.base import DomainModel
from .model_usage import ModelUsage


PromptText = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000),
]


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    role: ChatRole
    content: PromptText


class LLMRequest(DomainModel):
    """Provider-neutral request containing only already-filtered context."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    messages: tuple[ChatMessage, ...] = Field(min_length=2)
    response_schema: dict[str, JsonValue]


class LLMResponse(DomainModel):
    """Raw provider response validated before any action can execute."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    content: PromptText
    usage: ModelUsage | None = None


class LLMAdapterError(RuntimeError):
    """Raised by an adapter when a model response cannot be obtained."""

    def __init__(
        self,
        message: str,
        *,
        usage: ModelUsage | None = None,
        abort_episode: bool = False,
        latency_ms: float | None = None,
    ) -> None:
        if latency_ms is not None and latency_ms < 0:
            raise ValueError("adapter error latency cannot be negative")
        super().__init__(message)
        self.usage = usage
        self.abort_episode = abort_episode
        self.latency_ms = latency_ms
        self.prior_usages: tuple[ModelUsage, ...] = ()


@runtime_checkable
class LLMAdapter(Protocol):
    """Minimal synchronous interface replaceable by a real or fake provider."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return one raw model response for a validated provider-neutral request."""
