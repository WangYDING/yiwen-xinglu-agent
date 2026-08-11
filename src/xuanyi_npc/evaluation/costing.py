"""Versioned pricing snapshots and provider-neutral cost estimation."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.resources.runtime import read_runtime_text

DEFAULT_DEEPSEEK_PRICING_RESOURCE = (
    "pilot/deepseek_v4_flash_pilot_policy_2026-08-07.json"
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
    allowed_probe_ids: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    runs_per_probe: Literal[1]
    max_steps_per_episode: Literal[8]
    max_format_repair_attempts_per_step: Literal[1]
    request_input_token_upper_bound_method: Literal[
        "utf8_bytes_plus_framing"
    ] = "utf8_bytes_plus_framing"
    request_framing_token_allowance: Annotated[StrictInt, Field(ge=256)] = 4096

    @model_validator(mode="before")
    @classmethod
    def migrate_scenario_policy_names(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if (
            "allowed_probe_ids" not in migrated
            and "allowed_scenario_ids" in migrated
        ):
            migrated["allowed_probe_ids"] = migrated.pop("allowed_scenario_ids")
        if (
            "runs_per_probe" not in migrated
            and "runs_per_scenario" in migrated
        ):
            migrated["runs_per_probe"] = migrated.pop("runs_per_scenario")
        return migrated

    @model_validator(mode="after")
    def validate_probes(self) -> "DeepSeekPilotPricing":
        if len(set(self.allowed_probe_ids)) != len(self.allowed_probe_ids):
            raise ValueError("allowed Pilot probe IDs must be unique")
        return self


def load_deepseek_pilot_pricing(
    path: Path | str | None = None,
) -> DeepSeekPilotPricing:
    payload = (
        read_runtime_text(DEFAULT_DEEPSEEK_PRICING_RESOURCE)
        if path is None
        else Path(path).read_text(encoding="utf-8")
    )
    return DeepSeekPilotPricing.model_validate_json(
        payload
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
