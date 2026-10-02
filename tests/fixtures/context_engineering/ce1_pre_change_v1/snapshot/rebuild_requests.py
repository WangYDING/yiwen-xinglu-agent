from __future__ import annotations

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
for candidate in (ROOT / "src", ROOT):
    sys.path.insert(0, str(candidate))

from tests.context_baseline_support import action_input, planning_input
from xuanyi_npc.agents.fake_llm import ScriptedFakeLLM
from xuanyi_npc.agents.deepseek import DeepSeekAdapterConfig, DeepSeekChatAdapter
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.action_contract import build_safe_action_feedback
from xuanyi_npc.domain.cooperation import GameNPCDecision


def dump_request(request):
    return request.model_dump(mode="json")


def build():
    a0_llm = ScriptedFakeLLM(["not-json-pre-change", "still-not-json-pre-change"])
    GameNPCAgent(a0_llm).decide(action_input())

    a1_llm = ScriptedFakeLLM(["not-json-pre-change", "still-not-json-pre-change"])
    GameNPCAgent(a1_llm).propose_turn(planning_input())

    repair_llm = ScriptedFakeLLM(["not-json-pre-change"])
    repair_agent = GameNPCAgent(repair_llm)
    repair_input = action_input()
    prior = GameNPCDecision(
        decision_id="decision_context_baseline",
        turn_id=repair_input.turn_id,
        proposal=repair_agent._fallback_proposal(repair_input),
        llm_attempts=1,
        used_fallback=False,
    )
    repair_agent.repair_action_contract(
        repair_input,
        prior,
        build_safe_action_feedback("baseline_violation", repair_input.case_observation),
    )

    entries = [
        ("a0_initial", a0_llm.requests[0]),
        ("a0_format_repair", a0_llm.requests[1]),
        ("a1_initial", a1_llm.requests[0]),
        ("a1_format_repair", a1_llm.requests[1]),
        ("a1_action_contract_repair_a0_shape", repair_llm.requests[0]),
    ]
    requests = {name: dump_request(request) for name, request in entries}
    adapter = DeepSeekChatAdapter(DeepSeekAdapterConfig(api_key="offline-baseline-placeholder"))
    try:
        provider_payloads = {
            name: adapter._chat_payload(request) for name, request in entries
        }
    finally:
        adapter.close()
    return {"requests": requests, "provider_payloads": provider_payloads}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True))
