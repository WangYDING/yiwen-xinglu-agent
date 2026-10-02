"""Legacy CE-0 freezer; immutable versions are never overwritten."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from xuanyi_npc.agents import LLMResponse, ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.action_contract import build_safe_action_feedback
from xuanyi_npc.domain.cooperation import GameNPCDecision
from tests.context_baseline_support import action_input, planning_input


FIXTURE = ROOT / "tests" / "fixtures" / "context_engineering" / "ce0_requests.json"
IDENTITY_FILES = (
    "src/xuanyi_npc/agents/game_npc.py",
    "src/xuanyi_npc/agents/llm.py",
    "src/xuanyi_npc/agents/deepseek.py",
    "src/xuanyi_npc/agents/bounded_output.py",
    "src/xuanyi_npc/agents/simple_action.py",
    "src/xuanyi_npc/application/clinic.py",
    "src/xuanyi_npc/application/cooperative_runtime.py",
    "src/xuanyi_npc/application/views.py",
    "src/xuanyi_npc/application/action_contract.py",
    "src/xuanyi_npc/application/game_npc_memory.py",
    "src/xuanyi_npc/application/goal_plan_policy.py",
)


def _dump_request(request):
    return request.model_dump(mode="json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if FIXTURE.exists():
        raise SystemExit(f"REFUSE_OVERWRITE: frozen baseline already exists: {FIXTURE}")
    action = action_input()
    planning = planning_input()
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    action_request = agent._request(action)
    planning_request = agent._planning_request(planning)
    invalid = LLMResponse(content="not-json-baseline")
    error = ValueError("baseline validation error")
    action_repair = agent._format_repair_request(action_request, invalid, error, action)
    planning_repair = agent._format_planning_repair_request(
        planning_request, invalid, error, planning
    )

    prior = GameNPCDecision(
        decision_id="decision_context_baseline",
        turn_id=action.turn_id,
        proposal=agent._fallback_proposal(action),
        llm_attempts=1,
        used_fallback=False,
    )
    repair_adapter = ScriptedFakeLLM(["not-json-baseline"])
    repair_agent = GameNPCAgent(repair_adapter)
    repair_agent.repair_action_contract(
        action,
        prior,
        build_safe_action_feedback("invalid_tool_arguments", action.case_observation),
    )
    action_contract_repair = repair_adapter.requests[0]

    payload = {
        "fixture_version": "ce0_actual_requests_v1",
        "baseline_identity": {
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "workspace_status_sha256": hashlib.sha256(
                subprocess.check_output(
                    ["git", "status", "--short"], cwd=ROOT
                )
            ).hexdigest(),
            "files": {
                name: _sha256(ROOT / name)
                for name in IDENTITY_FILES
            },
        },
        "requests": {
            "a0_initial": _dump_request(action_request),
            "a0_format_repair": _dump_request(action_repair),
            "a0_action_contract_repair": _dump_request(action_contract_repair),
            "a1_initial_full_state": _dump_request(planning_request),
            "a1_format_repair_full_state": _dump_request(planning_repair),
        },
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
