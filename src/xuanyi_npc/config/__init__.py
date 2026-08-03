"""Runtime and evaluation configuration."""

from .variants import (
    AgentVariant,
    AgentVariantConfig,
    ContextStrategy,
    CurriculumStrategy,
    ReflectionStrategy,
    V0_CONFIG,
    V1_CONFIG,
    V2_CONFIG,
    get_variant_config,
)

__all__ = [
    "AgentVariant",
    "AgentVariantConfig",
    "ContextStrategy",
    "CurriculumStrategy",
    "ReflectionStrategy",
    "V0_CONFIG",
    "V1_CONFIG",
    "V2_CONFIG",
    "get_variant_config",
]
