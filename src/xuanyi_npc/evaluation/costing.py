"""Versioned pricing snapshots and provider-neutral cost estimation."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEEPSEEK_PRICING_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "pilot"
    / "deepseek_v4_flash_pricing_2026-08-04.json"
)


class DeepSeekPilotPricing(DomainModel):
    """Dated Pilot price and safety policy loaded from repository data."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    snapshot_id: Identifier
    provider: Literal["deepseek"]
    model: Literal["deepseek-v4-flash"]
    effective_date: date
    source_title: NonEmptyText
    source_url: NonEmptyText
    currency: Literal["CNY"]
    unit_tokens: Annotated[StrictInt, Field(gt=0)]
    cache_hit_input_price_per_unit: Annotated[Decimal, Field(ge=0)]
    cache_miss_input_price_per_unit: Annotated[Decimal, Field(ge=0)]
    output_price_per_unit: Annotated[Decimal, Field(ge=0)]
    allowed_scenario_ids: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    runs_per_scenario: Literal[1]
    max_steps_per_episode: Literal[8]
    max_format_repair_attempts_per_step: Literal[1]

    @model_validator(mode="after")
    def validate_scenarios(self) -> "DeepSeekPilotPricing":
        if len(set(self.allowed_scenario_ids)) != len(self.allowed_scenario_ids):
            raise ValueError("allowed Pilot scenario IDs must be unique")
        return self


def load_deepseek_pilot_pricing(
    path: Path | str = DEFAULT_DEEPSEEK_PRICING_PATH,
) -> DeepSeekPilotPricing:
    return DeepSeekPilotPricing.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def estimate_model_usage_cost(
    *,
    cache_hit_input_tokens: int,
    cache_miss_input_tokens: int,
    output_tokens: int,
    pricing: DeepSeekPilotPricing,
) -> Decimal:
    """Estimate cost without currency conversion or rate hard-coding."""

    if min(cache_hit_input_tokens, cache_miss_input_tokens, output_tokens) < 0:
        raise ValueError("token counts cannot be negative")
    unit = Decimal(pricing.unit_tokens)
    return (
        Decimal(cache_hit_input_tokens)
        * pricing.cache_hit_input_price_per_unit
        + Decimal(cache_miss_input_tokens)
        * pricing.cache_miss_input_price_per_unit
        + Decimal(output_tokens) * pricing.output_price_per_unit
    ) / unit
