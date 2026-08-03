"""Explicit capability boundaries for evaluation variants V0, V1, and V2."""

from enum import Enum

from pydantic import ConfigDict, StrictBool, model_validator

from xuanyi_npc.domain.base import DomainModel


class AgentVariant(str, Enum):
    V0 = "v0"
    V1 = "v1"
    V2 = "v2"


class ContextStrategy(str, Enum):
    SHORT_TERM = "short_term"
    PERSISTENT_MEMORY = "persistent_memory"


class CurriculumStrategy(str, Enum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class ReflectionStrategy(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"


class AgentVariantConfig(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variant: AgentVariant
    context_strategy: ContextStrategy
    curriculum_strategy: CurriculumStrategy
    reflection_strategy: ReflectionStrategy
    structured_actions: StrictBool
    basic_tool_calls: StrictBool

    @model_validator(mode="after")
    def enforce_named_variant_boundary(self) -> "AgentVariantConfig":
        expected = {
            AgentVariant.V0: (
                ContextStrategy.SHORT_TERM,
                CurriculumStrategy.FIXED,
                ReflectionStrategy.DISABLED,
            ),
            AgentVariant.V1: (
                ContextStrategy.PERSISTENT_MEMORY,
                CurriculumStrategy.FIXED,
                ReflectionStrategy.DISABLED,
            ),
            AgentVariant.V2: (
                ContextStrategy.PERSISTENT_MEMORY,
                CurriculumStrategy.ADAPTIVE,
                ReflectionStrategy.ENABLED,
            ),
        }[self.variant]
        actual = (
            self.context_strategy,
            self.curriculum_strategy,
            self.reflection_strategy,
        )
        if actual != expected:
            raise ValueError(f"capabilities do not match {self.variant.value} boundary")
        if not self.structured_actions or not self.basic_tool_calls:
            raise ValueError("all named variants require structured actions and basic tools")
        return self

    @property
    def long_term_memory_enabled(self) -> bool:
        return self.context_strategy is ContextStrategy.PERSISTENT_MEMORY

    @property
    def adaptive_teaching_enabled(self) -> bool:
        return self.curriculum_strategy is CurriculumStrategy.ADAPTIVE

    @property
    def reflection_enabled(self) -> bool:
        return self.reflection_strategy is ReflectionStrategy.ENABLED


V0_CONFIG = AgentVariantConfig(
    variant=AgentVariant.V0,
    context_strategy=ContextStrategy.SHORT_TERM,
    curriculum_strategy=CurriculumStrategy.FIXED,
    reflection_strategy=ReflectionStrategy.DISABLED,
    structured_actions=True,
    basic_tool_calls=True,
)

V1_CONFIG = AgentVariantConfig(
    variant=AgentVariant.V1,
    context_strategy=ContextStrategy.PERSISTENT_MEMORY,
    curriculum_strategy=CurriculumStrategy.FIXED,
    reflection_strategy=ReflectionStrategy.DISABLED,
    structured_actions=True,
    basic_tool_calls=True,
)

V2_CONFIG = AgentVariantConfig(
    variant=AgentVariant.V2,
    context_strategy=ContextStrategy.PERSISTENT_MEMORY,
    curriculum_strategy=CurriculumStrategy.ADAPTIVE,
    reflection_strategy=ReflectionStrategy.ENABLED,
    structured_actions=True,
    basic_tool_calls=True,
)

VARIANT_CONFIGS = {
    AgentVariant.V0: V0_CONFIG,
    AgentVariant.V1: V1_CONFIG,
    AgentVariant.V2: V2_CONFIG,
}


def get_variant_config(variant: AgentVariant) -> AgentVariantConfig:
    return VARIANT_CONFIGS[variant]
