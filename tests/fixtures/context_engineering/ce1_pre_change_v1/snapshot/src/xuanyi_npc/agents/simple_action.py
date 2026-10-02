"""Model-backed single-action agent used by the V2.1 A0 comparison."""

from typing import Callable

from xuanyi_npc.application.action_contract import SafeActionRecoveryFeedback
from xuanyi_npc.domain.cooperation import AgentRuntimeKind, GameNPCDecision

from .game_npc import GameNPCAgent, GameNPCAgentConfig, GameNPCAgentInput
from .llm import LLMAdapter


class SimpleActionGameNPCAgent:
    """Expose only current-action generation while retaining shared safety gates.

    Deliberately omitting ``propose_turn`` makes ``CooperativeRuntime`` select
    its existing non-planning branch.  The wrapped model still chooses every
    action; this class contains no diagnostic, treatment, or planning policy.
    """

    runtime_kind = AgentRuntimeKind.REAL_LLM
    architecture_id = "A0"

    def __init__(
        self,
        adapter: LLMAdapter,
        config: GameNPCAgentConfig | None = None,
        diagnostic_hook: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._delegate = GameNPCAgent(adapter, config, diagnostic_hook)
        self.adapter = adapter
        self.config = self._delegate.config

    def decide(self, agent_input: GameNPCAgentInput) -> GameNPCDecision:
        return self._delegate.decide(agent_input)

    def repair_action_contract(
        self,
        agent_input: GameNPCAgentInput,
        prior: GameNPCDecision,
        feedback: SafeActionRecoveryFeedback,
    ) -> GameNPCDecision:
        return self._delegate.repair_action_contract(agent_input, prior, feedback)

    def action_contract_fallback(self, prior: GameNPCDecision) -> GameNPCDecision:
        return self._delegate.action_contract_fallback(prior)

    def last_planning_execution(self):
        return self._delegate.last_planning_execution()

    def last_planning_proposal(self):
        return self._delegate.last_planning_proposal()

    def last_action_contract_attempts(self):
        return self._delegate.last_action_contract_attempts()

    def last_planning_input(self):
        return self._delegate.last_planning_input()

    def last_context_builds(self):
        return self._delegate.last_context_builds()
