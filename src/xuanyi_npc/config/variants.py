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


class MemoryRetrievalStrategy(str, Enum):
    NONE = "none"
    VECTOR_TOP_K = "vector_top_k"
    MULTI_FACTOR = "multi_factor"


class CurriculumStrategy(str, Enum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class ReflectionStrategy(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"


class AgentVariantConfig(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variant: AgentVariant
    agent_context_filter: StrictBool
    context_strategy: ContextStrategy
    memory_retrieval_strategy: MemoryRetrievalStrategy
    curriculum_strategy: CurriculumStrategy
    reflection_strategy: ReflectionStrategy
    structured_actions: StrictBool
    basic_tool_calls: StrictBool

    @model_validator(mode="after")
    def enforce_named_variant_boundary(self) -> "AgentVariantConfig":
        expected = {
            AgentVariant.V0: (
                ContextStrategy.SHORT_TERM,
                MemoryRetrievalStrategy.NONE,
                CurriculumStrategy.FIXED,
                ReflectionStrategy.DISABLED,
            ),
            AgentVariant.V1: (
                ContextStrategy.PERSISTENT_MEMORY,
                MemoryRetrievalStrategy.VECTOR_TOP_K,
                CurriculumStrategy.FIXED,
                ReflectionStrategy.DISABLED,
            ),
            AgentVariant.V2: (
                ContextStrategy.PERSISTENT_MEMORY,
                MemoryRetrievalStrategy.MULTI_FACTOR,
                CurriculumStrategy.ADAPTIVE,
                ReflectionStrategy.ENABLED,
            ),
        }[self.variant]
        actual = (
            self.context_strategy,
            self.memory_retrieval_strategy,
            self.curriculum_strategy,
            self.reflection_strategy,
        )
        if actual != expected:
            raise ValueError(f"capabilities do not match {self.variant.value} boundary")
        if not self.agent_context_filter:
            raise ValueError("all product variants require AgentContextFilter")
        if not self.structured_actions or not self.basic_tool_calls:
            raise ValueError("all product variants require structured actions and basic tools")
        return self

    @property
    def long_term_memory_enabled(self) -> bool:
        return self.memory_retrieval_strategy is not MemoryRetrievalStrategy.NONE

    @property
    def adaptive_teaching_enabled(self) -> bool:
        return self.curriculum_strategy is CurriculumStrategy.ADAPTIVE

    @property
    def reflection_enabled(self) -> bool:
        return self.reflection_strategy is ReflectionStrategy.ENABLED


V0_CONFIG = AgentVariantConfig(
    variant=AgentVariant.V0,
    agent_context_filter=True,
    context_strategy=ContextStrategy.SHORT_TERM,
    memory_retrieval_strategy=MemoryRetrievalStrategy.NONE,
    curriculum_strategy=CurriculumStrategy.FIXED,
    reflection_strategy=ReflectionStrategy.DISABLED,
    structured_actions=True,
    basic_tool_calls=True,
)

V1_CONFIG = AgentVariantConfig(
    variant=AgentVariant.V1,
    agent_context_filter=True,
    context_strategy=ContextStrategy.PERSISTENT_MEMORY,
    memory_retrieval_strategy=MemoryRetrievalStrategy.VECTOR_TOP_K,
    curriculum_strategy=CurriculumStrategy.FIXED,
    reflection_strategy=ReflectionStrategy.DISABLED,
    structured_actions=True,
    basic_tool_calls=True,
)

V2_CONFIG = AgentVariantConfig(
    variant=AgentVariant.V2,
    agent_context_filter=True,
    context_strategy=ContextStrategy.PERSISTENT_MEMORY,
    memory_retrieval_strategy=MemoryRetrievalStrategy.MULTI_FACTOR,
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
