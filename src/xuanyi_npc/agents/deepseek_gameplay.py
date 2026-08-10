"""Explicit paid-run authorization boundary for DeepSeek V0 gameplay."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Mapping

import httpx
from pydantic import ConfigDict, Field, StrictBool, field_validator

from xuanyi_npc.domain.base import DomainModel

from .deepseek import (
    DeepSeekAdapterConfig,
    DeepSeekChatAdapter,
    DeepSeekConfigurationError,
    DeepSeekModelDiscovery,
)
from .doctor import DoctorAgent


class DeepSeekGameplayAuthorization(DomainModel):
    """All non-secret gates required before model discovery or Chat."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_paid: StrictBool
    max_cost_cny: Annotated[Decimal, Field(gt=0)]
    timeout_seconds: Annotated[float, Field(gt=0, le=180)] = 180.0
    results_dir: Path
    model: Literal["deepseek-v4-flash"] = "deepseek-v4-flash"
    require_model_discovery: Literal[True] = True

    @field_validator("confirm_paid")
    @classmethod
    def require_paid_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("explicit paid confirmation is required")
        return value

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path) -> Path:
        try:
            resolved = value.resolve(strict=True)
        except OSError as exc:
            raise ValueError("results directory must already exist") from exc
        if not resolved.is_dir():
            raise ValueError("results directory must be a directory")
        lowered = {part.casefold() for part in resolved.parts}
        if not ({"results", "runtime_data"} & lowered):
            raise ValueError("results directory must be under results or runtime_data")
        if ".git" in lowered:
            raise ValueError("results directory cannot be inside .git")
        return resolved


def build_authorized_deepseek_v0_agent(
    authorization: DeepSeekGameplayAuthorization,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> tuple[DoctorAgent, DeepSeekChatAdapter, DeepSeekModelDiscovery]:
    """Build V0 only after all gates pass, then perform one explicit discovery."""

    base = DeepSeekAdapterConfig.from_env(environ)
    try:
        config = DeepSeekAdapterConfig.model_validate(
            {
                **base.model_dump(),
                "model": authorization.model,
                "timeout_seconds": authorization.timeout_seconds,
                "pilot_max_cost_cny": authorization.max_cost_cny,
            }
        )
    except Exception as exc:
        raise DeepSeekConfigurationError(
            "authorized DeepSeek gameplay configuration is invalid"
        ) from exc
    adapter = DeepSeekChatAdapter(config, client=client)
    try:
        discovery = adapter.require_configured_model()
    except Exception:
        adapter.close()
        raise
    return DoctorAgent(adapter), adapter, discovery
