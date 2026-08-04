"""Minimal synchronous DeepSeek ChatCompletions adapter for M2b-P1."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Annotated, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from xuanyi_npc.domain.base import DomainModel, NonEmptyText
from xuanyi_npc.evaluation import (
    DeepSeekPilotPricing,
    ModelUsage,
    estimate_model_usage_cost,
    load_deepseek_pilot_pricing,
)

from .llm import ChatRole, LLMAdapterError, LLMRequest, LLMResponse


AGENT_ACTION_JSON_EXAMPLE = {
    "action_id": "agent_step_001",
    "action_type": "respond",
    "dialogue": "只依据可见信息给出下一步建议。",
    "tool_call": None,
    "confidence": 0.5,
}


class DeepSeekAdapterError(LLMAdapterError):
    """Base error with a stable, non-sensitive classification code."""

    code = "deepseek_adapter_error"

class DeepSeekConfigurationError(DeepSeekAdapterError):
    code = "deepseek_configuration_error"


class DeepSeekMissingAPIKeyError(DeepSeekConfigurationError):
    code = "deepseek_missing_api_key"


class DeepSeekAuthenticationError(DeepSeekAdapterError):
    code = "deepseek_authentication_error"


class DeepSeekRateLimitError(DeepSeekAdapterError):
    code = "deepseek_rate_limit_error"


class DeepSeekTimeoutError(DeepSeekAdapterError):
    code = "deepseek_timeout_error"


class DeepSeekTransportError(DeepSeekAdapterError):
    code = "deepseek_transport_error"


class DeepSeekProviderError(DeepSeekAdapterError):
    code = "deepseek_provider_error"


class DeepSeekInvalidJSONError(DeepSeekAdapterError):
    code = "deepseek_invalid_json_response"


class DeepSeekResponseFieldError(DeepSeekAdapterError):
    code = "deepseek_response_field_error"


class DeepSeekEmptyContentError(DeepSeekAdapterError):
    code = "deepseek_empty_content"


class DeepSeekTruncatedOutputError(DeepSeekAdapterError):
    code = "deepseek_output_truncated"


class DeepSeekModelUnavailableError(DeepSeekAdapterError):
    code = "deepseek_model_unavailable"

    def __init__(self, model: str, available_models: tuple[str, ...]) -> None:
        self.model = model
        self.available_models = available_models
        super().__init__("configured DeepSeek model is not available for this API key")


class DeepSeekAdapterConfig(DomainModel):
    """Explicit configuration; ``from_env`` is the only environment reader."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    api_key: SecretStr = Field(min_length=1)
    base_url: NonEmptyText = "https://api.deepseek.com"
    model: Literal["deepseek-v4-flash"] = "deepseek-v4-flash"
    timeout_seconds: Annotated[float, Field(gt=0, le=600)] = 60.0
    max_output_tokens: Annotated[int, Field(ge=1, le=384_000)] = 512
    pilot_max_cost_cny: Annotated[Decimal, Field(gt=0)] = Decimal("1.00")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("DeepSeek base URL must use https")
        if normalized.endswith("/beta"):
            raise ValueError("the beta API base URL is not allowed for this adapter")
        return normalized

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "DeepSeekAdapterConfig":
        source = os.environ if environ is None else environ
        api_key = source.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise DeepSeekMissingAPIKeyError(
                "DEEPSEEK_API_KEY is required; no default credential is allowed"
            )
        try:
            timeout_seconds = float(
                source.get("DEEPSEEK_TIMEOUT_SECONDS", "60")
            )
            max_output_tokens = int(
                source.get("DEEPSEEK_MAX_OUTPUT_TOKENS", "512")
            )
            pilot_max_cost_cny = Decimal(
                source.get("XUANYI_PILOT_MAX_COST_CNY", "1.00")
            )
            return cls(
                api_key=api_key,
                base_url=source.get(
                    "DEEPSEEK_BASE_URL",
                    "https://api.deepseek.com",
                ),
                model=source.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                pilot_max_cost_cny=pilot_max_cost_cny,
            )
        except (ArithmeticError, ValueError, ValidationError):
            raise DeepSeekConfigurationError(
                "DeepSeek environment configuration is invalid"
            ) from None


class DeepSeekModelDiscovery(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    configured_model: NonEmptyText
    available_models: tuple[NonEmptyText, ...]
    configured_model_available: bool


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1)


class _ModelsEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    object: Literal["list"]
    data: tuple[_ProviderModel, ...]


class _CompletionMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    content: str | None


class _CompletionChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    finish_reason: str
    message: _CompletionMessage


class _CompletionTokenDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    reasoning_tokens: Annotated[int, Field(ge=0)] = 0


class _CompletionUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    prompt_cache_hit_tokens: Annotated[int, Field(ge=0)] | None = None
    prompt_cache_miss_tokens: Annotated[int, Field(ge=0)] | None = None
    completion_tokens_details: _CompletionTokenDetails | None = None


class _ChatCompletionEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    choices: tuple[_CompletionChoice, ...] = Field(min_length=1)
    model: str = Field(min_length=1)
    system_fingerprint: str | None = None
    usage: _CompletionUsage


class DeepSeekChatAdapter:
    """Direct HTTP adapter with no implicit retry and no Prompt logging."""

    def __init__(
        self,
        config: DeepSeekAdapterConfig,
        *,
        client: httpx.Client | None = None,
        pricing: DeepSeekPilotPricing | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.config = config
        self.pricing = pricing or load_deepseek_pilot_pricing()
        if self.pricing.model != self.config.model:
            raise DeepSeekConfigurationError(
                "pricing snapshot model does not match configured model"
            )
        self._client = client or httpx.Client()
        self._owns_client = client is None
        self._monotonic = monotonic

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        client: httpx.Client | None = None,
        pricing: DeepSeekPilotPricing | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> "DeepSeekChatAdapter":
        return cls(
            DeepSeekAdapterConfig.from_env(environ),
            client=client,
            pricing=pricing,
            monotonic=monotonic,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DeepSeekChatAdapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def discover_models(self) -> DeepSeekModelDiscovery:
        response = self._send("GET", "/models")
        payload = self._decode_json(response)
        try:
            envelope = _ModelsEnvelope.model_validate(payload)
        except ValidationError:
            raise DeepSeekResponseFieldError(
                "DeepSeek models response is missing required fields"
            ) from None
        available = tuple(model.id for model in envelope.data)
        return DeepSeekModelDiscovery(
            configured_model=self.config.model,
            available_models=available,
            configured_model_available=self.config.model in available,
        )

    def require_configured_model(self) -> DeepSeekModelDiscovery:
        discovery = self.discover_models()
        if not discovery.configured_model_available:
            raise DeepSeekModelUnavailableError(
                discovery.configured_model,
                discovery.available_models,
            )
        return discovery

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = self._monotonic()
        response = self._send(
            "POST",
            "/chat/completions",
            json_body=self._chat_payload(request),
        )
        latency_ms = float((self._monotonic() - started) * 1000)
        payload = self._decode_json(response)
        try:
            envelope = _ChatCompletionEnvelope.model_validate(payload)
        except ValidationError:
            raise DeepSeekResponseFieldError(
                "DeepSeek chat response is missing or has invalid required fields"
            ) from None

        choice = envelope.choices[0]
        try:
            usage = self._model_usage(envelope, latency_ms)
        except ValidationError:
            raise DeepSeekResponseFieldError(
                "DeepSeek usage response contains inconsistent fields"
            ) from None
        if choice.finish_reason == "length":
            raise DeepSeekTruncatedOutputError(
                "DeepSeek output was truncated at the configured token limit",
                usage=usage,
            )
        if choice.finish_reason != "stop":
            raise DeepSeekProviderError(
                "DeepSeek completion did not finish normally",
                usage=usage,
            )
        content = choice.message.content
        if content is None or not content.strip():
            raise DeepSeekEmptyContentError(
                "DeepSeek returned an empty final content field",
                usage=usage,
            )

        return LLMResponse(content=content, usage=usage)

    def _chat_payload(self, request: LLMRequest) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        for message in request.messages:
            role = message.role.value
            content = message.content
            if message.role is ChatRole.TOOL:
                role = ChatRole.USER.value
                content = f"应用层工具反馈：{content}"
            messages.append({"role": role, "content": content})

        json_instruction = (
            "\n你必须只输出一个 JSON 对象，不得使用 Markdown 代码块。"
            "输出必须符合下列 AgentAction JSON Schema；示例只展示结构，"
            "action_id 必须使用当前上下文指定值。\n"
            f"JSON Schema: {json.dumps(request.response_schema, ensure_ascii=False)}\n"
            "AgentAction JSON 示例: "
            f"{json.dumps(AGENT_ACTION_JSON_EXAMPLE, ensure_ascii=False)}"
        )
        if messages and messages[0]["role"] == ChatRole.SYSTEM.value:
            messages[0] = {
                "role": ChatRole.SYSTEM.value,
                "content": messages[0]["content"] + json_instruction,
            }
        else:
            messages.insert(
                0,
                {"role": ChatRole.SYSTEM.value, "content": json_instruction},
            )
        return {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": self.config.max_output_tokens,
        }

    def _model_usage(
        self,
        envelope: _ChatCompletionEnvelope,
        latency_ms: float,
    ) -> ModelUsage:
        raw = envelope.usage
        cache_hit, cache_miss = self._cache_breakdown(raw)
        reasoning_tokens = (
            raw.completion_tokens_details.reasoning_tokens
            if raw.completion_tokens_details is not None
            else 0
        )
        estimated_cost = estimate_model_usage_cost(
            cache_hit_input_tokens=cache_hit,
            cache_miss_input_tokens=cache_miss,
            output_tokens=raw.completion_tokens,
            pricing=self.pricing,
        )
        return ModelUsage(
            provider_model=envelope.model,
            input_tokens=raw.prompt_tokens,
            output_tokens=raw.completion_tokens,
            cache_hit_input_tokens=cache_hit,
            cache_miss_input_tokens=cache_miss,
            reasoning_tokens=reasoning_tokens,
            latency_ms=latency_ms,
            estimated_cost=estimated_cost,
            cost_currency=self.pricing.currency,
            provider_request_id=envelope.id,
            system_fingerprint=envelope.system_fingerprint,
        )

    @staticmethod
    def _cache_breakdown(usage: _CompletionUsage) -> tuple[int, int]:
        total = usage.prompt_tokens
        hit = usage.prompt_cache_hit_tokens
        miss = usage.prompt_cache_miss_tokens
        if hit is None and miss is None:
            return 0, total
        if hit is None:
            assert miss is not None
            if miss > total:
                raise DeepSeekResponseFieldError(
                    "cache miss tokens exceed total prompt tokens"
                )
            return total - miss, miss
        if miss is None:
            if hit > total:
                raise DeepSeekResponseFieldError(
                    "cache hit tokens exceed total prompt tokens"
                )
            return hit, total - hit
        if hit + miss != total:
            raise DeepSeekResponseFieldError(
                "cache token breakdown does not match total prompt tokens"
            )
        return hit, miss

    def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                f"{self.config.base_url}{path}",
                headers={
                    "Authorization": (
                        f"Bearer {self.config.api_key.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                },
                json=json_body,
                timeout=self.config.timeout_seconds,
            )
        except httpx.TimeoutException:
            raise DeepSeekTimeoutError("DeepSeek request timed out") from None
        except httpx.HTTPError:
            raise DeepSeekTransportError(
                "DeepSeek transport request failed"
            ) from None

        if response.status_code in (401, 403):
            raise DeepSeekAuthenticationError(
                "DeepSeek rejected the API credential or model permission"
            )
        if response.status_code == 429:
            raise DeepSeekRateLimitError("DeepSeek rate limit was reached")
        if response.status_code >= 500:
            raise DeepSeekProviderError("DeepSeek service returned a server error")
        if response.status_code >= 400:
            raise DeepSeekProviderError("DeepSeek service rejected the request")
        return response

    @staticmethod
    def _decode_json(response: httpx.Response) -> object:
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            raise DeepSeekInvalidJSONError(
                "DeepSeek response body is not valid JSON"
            ) from None
