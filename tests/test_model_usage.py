from decimal import Decimal

import pytest
from pydantic import ValidationError

from xuanyi_npc.agents.model_usage import ModelUsage


def usage(**updates) -> ModelUsage:
    values = {
        "provider_model": "deepseek-v4-flash",
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_hit_input_tokens": 40,
        "cache_miss_input_tokens": 60,
        "reasoning_tokens": 0,
        "latency_ms": 25.0,
        "estimated_cost": Decimal("0.0001"),
        "cost_currency": "CNY",
        "provider_request_id": "request_test",
        "system_fingerprint": "fingerprint_test",
    }
    values.update(updates)
    return ModelUsage(**values)


@pytest.mark.parametrize(
    ("estimated_cost", "cost_currency"),
    [(Decimal("0.01"), None), (None, "CNY")],
)
def test_cost_and_currency_must_be_present_together(
    estimated_cost: Decimal | None,
    cost_currency: str | None,
) -> None:
    with pytest.raises(ValidationError, match="must both be present or absent"):
        usage(estimated_cost=estimated_cost, cost_currency=cost_currency)


def test_cache_breakdown_must_equal_input_tokens() -> None:
    with pytest.raises(ValidationError, match="must sum to input_tokens"):
        usage(cache_hit_input_tokens=40, cache_miss_input_tokens=59)


def test_serialization_round_trip_preserves_bounded_provider_metadata() -> None:
    measured = usage()

    assert ModelUsage.model_validate_json(measured.model_dump_json()) == measured
