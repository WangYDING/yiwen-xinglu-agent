import json
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from xuanyi_npc.agents import (
    ChatMessage,
    ChatRole,
    DeepSeekAdapterConfig,
    DeepSeekAuthenticationError,
    DeepSeekChatAdapter,
    DeepSeekEmptyContentError,
    DeepSeekInvalidJSONError,
    DeepSeekMissingAPIKeyError,
    DeepSeekModelUnavailableError,
    DeepSeekProviderError,
    DeepSeekRateLimitError,
    DeepSeekResponseFieldError,
    DeepSeekTimeoutError,
    DeepSeekTruncatedOutputError,
    LLMRequest,
)
from xuanyi_npc.domain import AgentAction


PLACEHOLDER_CREDENTIAL = "unit-test-placeholder"


def adapter_config(**updates: object) -> DeepSeekAdapterConfig:
    values: dict[str, object] = {
        "api_key": PLACEHOLDER_CREDENTIAL,
        "base_url": "https://api.deepseek.test",
    }
    values.update(updates)
    return DeepSeekAdapterConfig(**values)


def llm_request(*, include_tool_feedback: bool = False) -> LLMRequest:
    messages = [
        ChatMessage(role=ChatRole.SYSTEM, content="只依据安全视图输出 JSON。"),
        ChatMessage(role=ChatRole.USER, content="本步 action_id 为 agent_step_001。"),
    ]
    if include_tool_feedback:
        messages.append(
            ChatMessage(role=ChatRole.TOOL, content="上一步工具执行成功。")
        )
    return LLMRequest(
        messages=tuple(messages),
        response_schema=AgentAction.model_json_schema(),
    )


def action_content() -> str:
    return json.dumps(
        {
            "action_id": "agent_step_001",
            "action_type": "respond",
            "dialogue": "先观察公开线索。",
            "tool_call": None,
            "confidence": 0.8,
        },
        ensure_ascii=False,
    )


def completion_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "request_001",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": action_content(),
                    "reasoning_content": "must never be copied",
                    "role": "assistant",
                },
            }
        ],
        "model": "DeepSeek-V4-Flash-0731",
        "system_fingerprint": "fp_deepseek_test",
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "prompt_cache_hit_tokens": 200,
            "prompt_cache_miss_tokens": 800,
            "completion_tokens_details": {"reasoning_tokens": 10},
        },
    }
    payload.update(updates)
    return payload


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_missing_api_key_is_rejected_before_client_creation() -> None:
    with pytest.raises(DeepSeekMissingAPIKeyError):
        DeepSeekAdapterConfig.from_env({})


def test_environment_configuration_uses_safe_pilot_defaults() -> None:
    config = DeepSeekAdapterConfig.from_env(
        {"DEEPSEEK_API_KEY": PLACEHOLDER_CREDENTIAL}
    )

    assert config.base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-v4-flash"
    assert config.timeout_seconds == 60.0
    assert config.max_output_tokens == 512
    assert config.pilot_max_cost_cny == Decimal("1.00")


@pytest.mark.parametrize("model", ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"])
def test_configuration_rejects_non_flash_models(model: str) -> None:
    with pytest.raises(ValidationError):
        adapter_config(model=model)


def test_configuration_rejects_beta_base_url() -> None:
    with pytest.raises(ValidationError, match="beta API base URL"):
        adapter_config(base_url="https://api.deepseek.com/beta")


def test_model_discovery_reports_exact_available_models_without_switching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/models"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek"},
                    {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"},
                ],
            },
        )

    adapter = DeepSeekChatAdapter(adapter_config(), client=mock_client(handler))

    discovery = adapter.discover_models()

    assert discovery.configured_model_available is True
    assert discovery.available_models == (
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    )
    assert discovery.configured_model == "deepseek-v4-flash"


def test_model_discovery_stops_when_flash_is_unavailable() -> None:
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(
            lambda request: httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"}
                    ],
                },
            )
        ),
    )

    with pytest.raises(DeepSeekModelUnavailableError) as captured:
        adapter.require_configured_model()

    assert captured.value.model == "deepseek-v4-flash"
    assert captured.value.available_models == ("deepseek-v4-pro",)


def test_chat_request_and_usage_follow_deepseek_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == (
            f"Bearer {PLACEHOLDER_CREDENTIAL}"
        )
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash"
        assert body["stream"] is False
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert body["temperature"] == 0
        assert body["max_tokens"] == 512
        assert "tools" not in body
        assert "JSON Schema" in body["messages"][0]["content"]
        assert "AgentAction JSON" in body["messages"][0]["content"]
        assert all(message["role"] != "tool" for message in body["messages"])
        serialized = json.dumps(body, ensure_ascii=False)
        for hidden in (
            "root_cause",
            "valid_diagnosis_ids",
            "diagnosis_correct",
            "unsafe_treatment_penalty",
        ):
            assert hidden not in serialized
        return httpx.Response(200, json=completion_payload())

    times = iter((10.0, 10.25))
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(handler),
        monotonic=lambda: next(times),
    )

    response = adapter.complete(llm_request(include_tool_feedback=True))

    assert response.content == action_content()
    assert "must never be copied" not in response.content
    assert response.usage is not None
    assert response.usage.provider_model == "DeepSeek-V4-Flash-0731"
    assert response.usage.provider_request_id == "request_001"
    assert response.usage.system_fingerprint == "fp_deepseek_test"
    assert response.usage.input_tokens == 1000
    assert response.usage.output_tokens == 100
    assert response.usage.cache_hit_input_tokens == 200
    assert response.usage.cache_miss_input_tokens == 800
    assert response.usage.reasoning_tokens == 10
    assert response.usage.latency_ms == 250.0
    assert response.usage.estimated_cost == Decimal("0.001004")
    assert response.usage.cost_currency == "CNY"


def test_missing_optional_cache_and_reasoning_details_use_conservative_defaults() -> None:
    payload = completion_payload()
    payload["usage"] = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
    }
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(lambda request: httpx.Response(200, json=payload)),
        monotonic=iter((1.0, 1.1)).__next__,
    )

    usage = adapter.complete(llm_request()).usage

    assert usage is not None
    assert usage.cache_hit_input_tokens == 0
    assert usage.cache_miss_input_tokens == 1000
    assert usage.reasoning_tokens == 0
    assert usage.estimated_cost == Decimal("0.0012")


@pytest.mark.parametrize("status_code", [401, 403])
def test_authentication_and_permission_failures_are_classified(
    status_code: int,
) -> None:
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(
            lambda request: httpx.Response(
                status_code,
                json={"error": "credential rejected"},
            )
        ),
    )

    with pytest.raises(DeepSeekAuthenticationError):
        adapter.complete(llm_request())


def test_rate_limit_is_classified_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"error": "rate limit"})

    adapter = DeepSeekChatAdapter(adapter_config(), client=mock_client(handler))

    with pytest.raises(DeepSeekRateLimitError):
        adapter.complete(llm_request())

    assert calls == 1


def test_timeout_is_classified_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("offline timeout", request=request)

    adapter = DeepSeekChatAdapter(adapter_config(), client=mock_client(handler))

    with pytest.raises(DeepSeekTimeoutError):
        adapter.complete(llm_request())

    assert calls == 1


def test_provider_5xx_is_classified_without_leaking_response_body() -> None:
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(
            lambda request: httpx.Response(
                503,
                text="sensitive-provider-debug-body",
            )
        ),
    )

    with pytest.raises(DeepSeekProviderError) as captured:
        adapter.complete(llm_request())

    assert "sensitive-provider-debug-body" not in str(captured.value)


def test_invalid_json_response_is_classified() -> None:
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(
            lambda request: httpx.Response(200, content=b"not-json")
        ),
    )

    with pytest.raises(DeepSeekInvalidJSONError):
        adapter.complete(llm_request())


def test_empty_final_content_is_classified() -> None:
    payload = completion_payload()
    payload["choices"] = [
        {"finish_reason": "stop", "message": {"content": "   "}}
    ]
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(lambda request: httpx.Response(200, json=payload)),
    )

    with pytest.raises(DeepSeekEmptyContentError) as captured:
        adapter.complete(llm_request())

    assert captured.value.usage is not None
    assert captured.value.usage.estimated_cost == Decimal("0.001004")


def test_length_finish_reason_is_classified_as_truncation() -> None:
    payload = completion_payload()
    payload["choices"] = [
        {"finish_reason": "length", "message": {"content": "{\"partial\":"}}
    ]
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(lambda request: httpx.Response(200, json=payload)),
    )

    with pytest.raises(DeepSeekTruncatedOutputError) as captured:
        adapter.complete(llm_request())

    assert captured.value.usage is not None
    assert captured.value.usage.output_tokens == 100


def test_missing_required_response_fields_are_classified() -> None:
    adapter = DeepSeekChatAdapter(
        adapter_config(),
        client=mock_client(
            lambda request: httpx.Response(
                200,
                json={"id": "request_without_choices", "model": "model"},
            )
        ),
    )

    with pytest.raises(DeepSeekResponseFieldError):
        adapter.complete(llm_request())
