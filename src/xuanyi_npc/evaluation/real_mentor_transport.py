"""Dedicated DeepSeek transport for the R6 real MentorAction pilot."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMRequest
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.evaluation.episode import ModelUsage


MODEL_ID = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
MAX_OUTPUT_TOKENS = 512
AUTHORIZED_BUDGET_CNY = Decimal("0.05")


class MentorPilotTransportError(RuntimeError):
    def __init__(self, code: str, *, usage: ModelUsage | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.usage = usage


class MentorPilotPricing(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_id: Identifier
    provider: str
    model: str
    observed_date: str
    source_url: NonEmptyText
    currency: str
    unit_tokens: int = Field(gt=0)
    input_cache_hit_cny_per_million: Decimal = Field(ge=0)
    input_cache_miss_cny_per_million: Decimal = Field(ge=0)
    output_cny_per_million: Decimal = Field(ge=0)
    reservation_framing_bytes: int = Field(ge=256)

    def validate_identity(self) -> None:
        if self.provider != "deepseek" or self.model != MODEL_ID or self.currency != "CNY":
            raise ValueError("mentor pilot pricing identity mismatch")


def load_mentor_pilot_pricing(path: Path | str) -> MentorPilotPricing:
    pricing = MentorPilotPricing.model_validate_json(Path(path).read_text(encoding="utf-8"))
    pricing.validate_identity()
    return pricing


class MentorPilotBudget:
    """Reserve worst-case request cost, then settle only from provider usage."""

    def __init__(self, limit: Decimal, pricing: MentorPilotPricing) -> None:
        if limit != AUTHORIZED_BUDGET_CNY:
            raise ValueError("pilot budget must equal the frozen 0.05 CNY authorization")
        self.limit = limit
        self.pricing = pricing
        self.confirmed_cost = Decimal("0")
        self.unverified_reserve = Decimal("0")
        self.active_reserve: Decimal | None = None
        self.halted = False

    @property
    def maximum_committed_cost(self) -> Decimal:
        return self.confirmed_cost + self.unverified_reserve + (self.active_reserve or Decimal("0"))

    def estimate(self, payload: Mapping[str, Any]) -> Decimal:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        input_upper = len(encoded) + self.pricing.reservation_framing_bytes
        unit = Decimal(self.pricing.unit_tokens)
        return (
            Decimal(input_upper) * self.pricing.input_cache_miss_cny_per_million
            + Decimal(MAX_OUTPUT_TOKENS) * self.pricing.output_cny_per_million
        ) / unit

    def reserve(self, payload: Mapping[str, Any]) -> Decimal:
        if self.halted or self.active_reserve is not None:
            raise MentorPilotTransportError("budget_halted")
        amount = self.estimate(payload)
        if self.confirmed_cost + self.unverified_reserve + amount > self.limit:
            raise MentorPilotTransportError("budget_exceeded")
        self.active_reserve = amount
        return amount

    def settle(self, usage: ModelUsage) -> Decimal:
        if self.active_reserve is None:
            raise RuntimeError("no active reservation")
        unit = Decimal(self.pricing.unit_tokens)
        cost = (
            Decimal(usage.cache_hit_input_tokens) * self.pricing.input_cache_hit_cny_per_million
            + Decimal(usage.cache_miss_input_tokens) * self.pricing.input_cache_miss_cny_per_million
            + Decimal(usage.output_tokens) * self.pricing.output_cny_per_million
        ) / unit
        if cost > self.active_reserve:
            self.halt_unverified()
            raise MentorPilotTransportError("usage_exceeds_reservation")
        self.confirmed_cost += cost
        self.active_reserve = None
        return cost

    def halt_unverified(self) -> None:
        if self.active_reserve is not None:
            self.unverified_reserve += self.active_reserve
            self.active_reserve = None
        self.halted = True


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str


class _Models(BaseModel):
    model_config = ConfigDict(extra="ignore")
    object: str
    data: tuple[_Model, ...]


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    prompt_cache_hit_tokens: int = Field(ge=0)
    prompt_cache_miss_tokens: int = Field(ge=0)


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    finish_reason: str
    message: _Message


class _Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    model: str
    choices: tuple[_Choice, ...] = Field(min_length=1)
    usage: _Usage


@dataclass(frozen=True)
class MentorTransportResponse:
    content: str
    usage: ModelUsage
    raw_response: dict[str, Any]


class RealMentorDeepSeekTransport:
    """No-retry HTTP boundary that knows only MentorAction requests."""

    def __init__(self, api_key: SecretStr, budget: MentorPilotBudget, *, timeout_seconds: float = 30, client: httpx.Client | None = None, monotonic: Callable[[], float] = time.perf_counter) -> None:
        self.api_key = api_key
        self.budget = budget
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client()
        self.owns_client = client is None
        self.monotonic = monotonic
        self.models_calls = 0
        self.chat_calls = 0

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

    def discover_flash(self) -> tuple[str, ...]:
        if self.models_calls >= 1:
            raise MentorPilotTransportError("models_call_limit")
        self.models_calls += 1
        response = self._send("GET", "/models")
        try:
            envelope = _Models.model_validate(response.json())
        except (ValueError, ValidationError):
            raise MentorPilotTransportError("models_schema_invalid") from None
        models = tuple(item.id for item in envelope.data)
        if MODEL_ID not in models:
            raise MentorPilotTransportError("configured_model_unavailable")
        return models

    def complete(self, request: LLMRequest) -> MentorTransportResponse:
        payload = self.build_payload(request)
        self.budget.reserve(payload)
        self.chat_calls += 1
        started = self.monotonic()
        try:
            response = self._send("POST", "/chat/completions", payload)
            latency = (self.monotonic() - started) * 1000
            try:
                raw = response.json()
                envelope = _Completion.model_validate(raw)
            except (ValueError, ValidationError):
                self.budget.halt_unverified()
                raise MentorPilotTransportError("chat_schema_or_usage_invalid") from None
            usage = ModelUsage(
                provider_model=envelope.model,
                input_tokens=envelope.usage.prompt_tokens,
                output_tokens=envelope.usage.completion_tokens,
                cache_hit_input_tokens=envelope.usage.prompt_cache_hit_tokens,
                cache_miss_input_tokens=envelope.usage.prompt_cache_miss_tokens,
                reasoning_tokens=0,
                latency_ms=latency,
                estimated_cost=Decimal("0"),
                cost_currency="CNY",
                provider_request_id=envelope.id,
            )
            self.budget.settle(usage)
            if envelope.model != MODEL_ID:
                raise MentorPilotTransportError("response_model_mismatch", usage=usage)
            if envelope.choices[0].finish_reason != "stop":
                raise MentorPilotTransportError("completion_not_complete", usage=usage)
            return MentorTransportResponse(envelope.choices[0].message.content, usage, raw)
        except MentorPilotTransportError as exc:
            if exc.usage is None and self.budget.active_reserve is not None:
                self.budget.halt_unverified()
            raise
        except httpx.TimeoutException:
            self.budget.halt_unverified()
            raise MentorPilotTransportError("timeout") from None
        except httpx.HTTPError:
            self.budget.halt_unverified()
            raise MentorPilotTransportError("transport_error") from None

    @staticmethod
    def build_payload(request: LLMRequest) -> dict[str, Any]:
        messages = [{"role": item.role.value, "content": item.content} for item in request.messages]
        schema_instruction = "只输出一个符合以下 MentorAction JSON Schema 的JSON对象，不得输出代码块：" + json.dumps(request.response_schema, ensure_ascii=False, sort_keys=True)
        messages.append({"role": "user", "content": schema_instruction})
        return {"model": MODEL_ID, "messages": messages, "stream": False, "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS}

    def _send(self, method: str, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        response = self.client.request(method, BASE_URL + path, headers={"Authorization": "Bearer " + self.api_key.get_secret_value(), "Content-Type": "application/json"}, json=payload, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise MentorPilotTransportError("provider_http_error")
        return response
