"""Public Agent API for the 《异闻行录》 cooperative Game NPC."""

from .fake_llm import ScriptedFakeLLM
from .game_npc import (
    GAME_NPC_M1_SYSTEM_PROMPT,
    DeterministicCooperativeNPC,
    GameNPCAgent,
    GameNPCAgentConfig,
    GameNPCAgentInput,
    GameNPCAgentInterface,
)
from .deepseek import (
    DeepSeekAdapterConfig,
    DeepSeekAdapterError,
    DeepSeekAuthenticationError,
    DeepSeekBudgetExceededError,
    DeepSeekChatAdapter,
    DeepSeekConfigurationError,
    DeepSeekEmptyContentError,
    DeepSeekInvalidJSONError,
    DeepSeekMissingAPIKeyError,
    DeepSeekModelDiscovery,
    DeepSeekModelUnavailableError,
    DeepSeekProviderError,
    DeepSeekRateLimitError,
    DeepSeekRequestBudgetGuard,
    DeepSeekRequestReservation,
    DeepSeekResponseFieldError,
    DeepSeekTimeoutError,
    DeepSeekTransportError,
    DeepSeekTruncatedOutputError,
    DeepSeekUsageUnavailableError,
)
from .llm import ChatMessage, ChatRole, LLMAdapter, LLMAdapterError, LLMRequest, LLMResponse
from .model_usage import AgentRepairKind, ModelUsage

__all__ = [
    "ChatMessage", "ChatRole", "LLMAdapter", "LLMAdapterError", "LLMRequest", "LLMResponse",
    "ScriptedFakeLLM", "GAME_NPC_M1_SYSTEM_PROMPT", "GameNPCAgent", "GameNPCAgentConfig",
    "GameNPCAgentInput", "GameNPCAgentInterface", "DeterministicCooperativeNPC",
    "DeepSeekAdapterConfig", "DeepSeekAdapterError", "DeepSeekAuthenticationError",
    "DeepSeekBudgetExceededError", "DeepSeekChatAdapter", "DeepSeekConfigurationError",
    "DeepSeekEmptyContentError", "DeepSeekInvalidJSONError", "DeepSeekMissingAPIKeyError",
    "DeepSeekModelDiscovery", "DeepSeekModelUnavailableError", "DeepSeekProviderError",
    "DeepSeekRateLimitError", "DeepSeekRequestBudgetGuard", "DeepSeekRequestReservation",
    "DeepSeekResponseFieldError", "DeepSeekTimeoutError", "DeepSeekTransportError",
    "DeepSeekTruncatedOutputError", "DeepSeekUsageUnavailableError",
    "AgentRepairKind", "ModelUsage",
]
