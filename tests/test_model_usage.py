from decimal import Decimal

import pytest
from pydantic import ValidationError

from xuanyi_npc.agents import (
    ChatMessage,
    ChatRole,
    LLMRequest,
    ScriptedFakeLLM,
)
from xuanyi_npc.application.v0_runner import V0EpisodeRunner
from xuanyi_npc.evaluation import (
    ModelUsage,
    estimate_model_usage_cost,
    load_deepseek_pilot_pricing,
)


def measured_usage(
    *,
    request_id: str,
    cost: str,
    currency: str = "CNY",
    fingerprint: str = "fp_test",
) -> ModelUsage:
    return ModelUsage(
        provider_model="deepseek-v4-flash",
        input_tokens=100,
        output_tokens=20,
        cache_hit_input_tokens=40,
        cache_miss_input_tokens=60,
        reasoning_tokens=0,
        latency_ms=25.0,
        estimated_cost=Decimal(cost),
        cost_currency=currency,
        provider_request_id=request_id,
        system_fingerprint=fingerprint,
    )


@pytest.mark.parametrize(
    ("estimated_cost", "cost_currency"),
    [(Decimal("0.01"), None), (None, "CNY")],
)
def test_model_usage_requires_cost_and_currency_together(
    estimated_cost: Decimal | None,
    cost_currency: str | None,
) -> None:
    with pytest.raises(ValidationError, match="must both be present or absent"):
        ModelUsage(
            provider_model="provider-model",
            input_tokens=10,
            output_tokens=2,
            cache_hit_input_tokens=0,
            cache_miss_input_tokens=10,
            reasoning_tokens=0,
            latency_ms=1.0,
            estimated_cost=estimated_cost,
            cost_currency=cost_currency,
        )


def test_model_usage_rejects_inconsistent_cache_breakdown() -> None:
    with pytest.raises(ValidationError, match="must sum to input_tokens"):
        ModelUsage(
            provider_model="provider-model",
            input_tokens=10,
            output_tokens=2,
            cache_hit_input_tokens=4,
            cache_miss_input_tokens=5,
            reasoning_tokens=0,
            latency_ms=1.0,
        )


def test_model_usage_serialization_round_trip_preserves_provider_metadata() -> None:
    usage = measured_usage(request_id="request_001", cost="0.0001")

    restored = ModelUsage.model_validate_json(usage.model_dump_json())

    assert restored == usage
    assert "cost_usd" not in usage.model_dump()


def test_deepseek_pricing_snapshot_estimates_cache_components_separately() -> None:
    pricing = load_deepseek_pilot_pricing()

    cost = estimate_model_usage_cost(
        cache_hit_input_tokens=200,
        cache_miss_input_tokens=800,
        output_tokens=100,
        pricing=pricing,
    )

    assert pricing.effective_date.isoformat() == "2026-08-04"
    assert pricing.currency == "CNY"
    assert pricing.source_url == (
        "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
    )
    assert cost == Decimal("0.001004")


def test_episode_usage_aggregation_sums_tokens_cost_and_latency() -> None:
    first = measured_usage(request_id="request_001", cost="0.0001")
    second = measured_usage(request_id="request_002", cost="0.0002")

    aggregate = V0EpisodeRunner._aggregate_usage([first, second])

    assert aggregate is not None
    assert aggregate.input_tokens == 200
    assert aggregate.output_tokens == 40
    assert aggregate.cache_hit_input_tokens == 80
    assert aggregate.cache_miss_input_tokens == 120
    assert aggregate.reasoning_tokens == 0
    assert aggregate.latency_ms == 50.0
    assert aggregate.estimated_cost == Decimal("0.0003")
    assert aggregate.cost_currency == "CNY"
    assert aggregate.provider_request_id is None
    assert aggregate.system_fingerprint == "fp_test"


def test_episode_usage_aggregation_omits_incompatible_currency_estimate() -> None:
    cny = measured_usage(request_id="request_001", cost="0.0001")
    usd = measured_usage(
        request_id="request_002",
        cost="0.0002",
        currency="USD",
    )

    aggregate = V0EpisodeRunner._aggregate_usage([cny, usd])

    assert aggregate is not None
    assert aggregate.estimated_cost is None
    assert aggregate.cost_currency is None


def test_partial_episode_usage_keeps_known_cost_and_marks_incomplete() -> None:
    known = measured_usage(request_id="request_001", cost="0.0001")

    aggregate = V0EpisodeRunner._aggregate_usage(
        [known],
        measurement_complete=False,
    )

    assert aggregate is not None
    assert aggregate.estimated_cost == Decimal("0.0001")
    assert aggregate.measurement_complete is False


def test_scripted_fake_llm_keeps_usage_unmeasured() -> None:
    fake = ScriptedFakeLLM(['{"status":"offline"}'])

    response = fake.complete(
        LLMRequest(
            messages=(
                ChatMessage(role=ChatRole.SYSTEM, content="Return JSON."),
                ChatMessage(role=ChatRole.USER, content="Offline test."),
            ),
            response_schema={"type": "object"},
        )
    )

    assert response.usage is None
