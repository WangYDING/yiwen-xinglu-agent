"""Final-payload token budgeting. No world reads and no model-based summaries."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json
from typing import Callable

from tokenizers import Tokenizer

from .llm import LLMAdapterError, LLMRequest


class ContextBudgetExceeded(LLMAdapterError):
    code = "context_budget_exceeded"


@dataclass(frozen=True)
class ModelContextProfile:
    # Application cap, intentionally smaller than the provider's advertised window.
    context_window: int = 65_536
    safety_margin: int = 1024
    framing_per_message: int = 16
    framing_base: int = 16

    def __post_init__(self):
        if self.context_window <= 0 or min(self.safety_margin, self.framing_per_message, self.framing_base) < 0:
            raise ValueError("invalid context budget profile")


@lru_cache(maxsize=1)
def _tokenizer():
    data = files("xuanyi_npc.resources").joinpath("tokenizer/deepseek_v4_tokenizer.json").read_bytes()
    return Tokenizer.from_str(data.decode("utf-8")), sha256(data).hexdigest()


@dataclass(frozen=True)
class ContextBudgetTrace:
    content_tokens: int
    framing_estimate: int
    output_tokens: int
    safety_margin: int
    context_window: int
    selection: str
    tokenizer_sha256: str
    payload_sha256: str
    retained_memory_ids: tuple[str, ...]
    token_count_method: str = "deepseek_v4_tokenizer_plus_estimated_framing"


@dataclass(frozen=True)
class PreparedProviderRequest:
    payload: dict
    trace: ContextBudgetTrace


def prepare_request(request: LLMRequest, render: Callable[[LLMRequest], dict], profile: ModelContextProfile) -> PreparedProviderRequest:
    tokenizer, identity = _tokenizer()
    candidates = [(request.messages, "unchanged", request.retained_memory_ids)]
    candidates.extend((v.messages, v.reason, v.retained_memory_ids) for v in request.context_variants)
    for messages, reason, memory_ids in candidates:
        payload = render(request.model_copy(update={"messages": messages}))
        content_tokens = sum(len(tokenizer.encode(m["content"], add_special_tokens=False).ids) for m in payload["messages"])
        framing = profile.framing_base + profile.framing_per_message * len(payload["messages"])
        output = payload["max_tokens"]
        trace = ContextBudgetTrace(
            content_tokens, framing, output, profile.safety_margin,
            profile.context_window, reason, identity,
            sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            memory_ids,
        )
        if content_tokens + framing + output + profile.safety_margin <= profile.context_window:
            return PreparedProviderRequest(payload, trace)
    error = ContextBudgetExceeded("required public context cannot fit the configured token budget; no request sent")
    error.budget_trace = trace
    error.configured_max_output_tokens = trace.output_tokens
    error.failure_stage = "context_budget"
    raise error
