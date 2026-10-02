"""Provider-usage and bounded-repair contracts shared by current agents."""

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, StringConstraints, model_validator

from xuanyi_npc.domain.base import DomainModel, NonEmptyText


CurrencyCode = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$"),
]


class AgentRepairKind(str, Enum):
    FORMAT_REPAIR = "format_repair"
    ACTION_CONTRACT_REPAIR = "action_contract_repair"


class ModelUsage(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider_model: NonEmptyText
    input_tokens: Annotated[StrictInt, Field(ge=0)]
    output_tokens: Annotated[StrictInt, Field(ge=0)]
    cache_hit_input_tokens: Annotated[StrictInt, Field(ge=0)]
    cache_miss_input_tokens: Annotated[StrictInt, Field(ge=0)]
    reasoning_tokens: Annotated[StrictInt, Field(ge=0)]
    latency_ms: Annotated[StrictFloat, Field(ge=0)]
    estimated_cost: Annotated[Decimal, Field(ge=0)] | None = None
    cost_currency: CurrencyCode | None = None
    provider_request_id: NonEmptyText | None = None
    system_fingerprint: NonEmptyText | None = None
    measurement_complete: StrictBool = True

    @model_validator(mode="after")
    def validate_usage_consistency(self) -> "ModelUsage":
        if self.cache_hit_input_tokens + self.cache_miss_input_tokens != self.input_tokens:
            raise ValueError("cache hit and miss input tokens must sum to input_tokens")
        if (self.estimated_cost is None) != (self.cost_currency is None):
            raise ValueError("estimated_cost and cost_currency must both be present or absent")
        return self
