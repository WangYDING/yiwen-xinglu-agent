from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekChatAdapter,
    GameNPCAgent,
    ScriptedFakeLLM,
    SimpleActionGameNPCAgent,
)
from xuanyi_npc.application.action_contract import (
    INVESTIGATION_TOOL_BY_ACTION,
    build_safe_action_feedback,
)
from xuanyi_npc.domain import ToolCallRequest
from xuanyi_npc.domain.cooperation import GameNPCDecision
from tests.context_baseline_support import action_input, planning_input
from tests.test_phase_a_production_wiring import (
    contribution,
    opened_clinic,
    proposal_for,
)


BASELINE = (
    Path(__file__).parent
    / "fixtures"
    / "context_engineering"
    / "ce1_pre_change_v1"
)


def _dump(request):
    # Keep the historical prompt/schema baseline; assert the intentional budget migration separately.
    assert request.max_output_tokens == (2048 if request.response_schema.get("title") == "GameNPCTurnProposal" else 512)
    result = request.model_dump(mode="json")
    if type(request).__name__ != "GameNPCPlanningRequest":
        result.pop("max_output_tokens", None)
    return result


def _direct_action_repair(agent: GameNPCAgent):
    value = action_input()
    prior = GameNPCDecision(
        decision_id="decision_context_baseline",
        turn_id=value.turn_id,
        proposal=agent._fallback_proposal(value),
        llm_attempts=1,
        used_fallback=False,
    )
    agent.repair_action_contract(
        value,
        prior,
        build_safe_action_feedback("baseline_violation", value.case_observation),
    )


def test_ce11_requests_and_provider_payloads_match_independent_prechange_snapshot() -> None:
    expected_requests = json.loads(
        (BASELINE / "requests.json").read_text(encoding="utf-8")
    )
    expected_payloads = json.loads(
        (BASELINE / "provider_payloads.json").read_text(encoding="utf-8")
    )

    a0_llm = ScriptedFakeLLM(["not-json-pre-change", "still-not-json-pre-change"])
    GameNPCAgent(a0_llm).decide(action_input())
    a1_llm = ScriptedFakeLLM(["not-json-pre-change", "still-not-json-pre-change"])
    GameNPCAgent(a1_llm).propose_turn(planning_input())
    repair_llm = ScriptedFakeLLM(["not-json-pre-change"])
    _direct_action_repair(GameNPCAgent(repair_llm))

    named_requests = {
        "a0_initial": a0_llm.requests[0],
        "a0_format_repair": a0_llm.requests[1],
        "a1_initial": a1_llm.requests[0],
        "a1_format_repair": a1_llm.requests[1],
        "a1_action_contract_repair_a0_shape": repair_llm.requests[0],
    }
    assert {name: _dump(request) for name, request in named_requests.items()} == (
        expected_requests
    )

    adapter = DeepSeekChatAdapter(
        DeepSeekAdapterConfig(api_key="offline-baseline-placeholder")
    )
    try:
        actual_payloads = {
            name: adapter._chat_payload(request)
            for name, request in named_requests.items()
        }
    finally:
        adapter.close()
    expected_payloads["a1_format_repair"]["max_tokens"] = 2048
    assert actual_payloads == expected_payloads


def test_ce11_frozen_source_snapshot_independently_rebuilds_requests() -> None:
    rebuilt = subprocess.run(
        [sys.executable, "rebuild_requests.py"],
        cwd=BASELINE / "snapshot",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    actual = json.loads(rebuilt.stdout)
    assert actual == {
        "requests": json.loads(
            (BASELINE / "requests.json").read_text(encoding="utf-8")
        ),
        "provider_payloads": json.loads(
            (BASELINE / "provider_payloads.json").read_text(encoding="utf-8")
        ),
    }


def test_ce11_signed_file_manifest_matches_frozen_bytes() -> None:
    signed = json.loads((BASELINE / "sha256s.json").read_text(encoding="utf-8"))
    manifest = json.loads((BASELINE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["signed_file_count"] == len(signed)
    for relative, identity in signed.items():
        content = (BASELINE / relative).read_bytes()
        assert len(content) == identity["bytes"]
        assert hashlib.sha256(content).hexdigest() == identity["sha256"]


def test_freezers_refuse_to_overwrite_existing_versioned_baselines() -> None:
    manifest_before = (BASELINE / "manifest.json").read_bytes()
    ce0_before = (
        BASELINE.parent / "ce0_requests.json"
    ).read_bytes()

    ce11 = subprocess.run(
        [
            sys.executable,
            "tools/freeze_ce1_context_baseline.py",
            "ce1_pre_change_v1",
        ],
        cwd=BASELINE.parents[3],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    legacy = subprocess.run(
        [sys.executable, "tools/freeze_context_baseline.py"],
        cwd=BASELINE.parents[3],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert ce11.returncode != 0
    assert legacy.returncode != 0
    assert "REFUSE_OVERWRITE" in ce11.stderr
    assert "REFUSE_OVERWRITE" in legacy.stderr
    assert (BASELINE / "manifest.json").read_bytes() == manifest_before
    assert (BASELINE.parent / "ce0_requests.json").read_bytes() == ce0_before


def test_formal_a0_entry_captures_initial_and_format_repair_at_adapter_boundary(
    tmp_path: Path,
) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    fake = ScriptedFakeLLM(["not json", "still not json"])
    agent = SimpleActionGameNPCAgent(fake)
    clinic.game_npc_agent = agent

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, "ce11_a0_format")
    )

    assert result.decision.used_fallback is True
    assert result.event_sequences == ()
    assert len(fake.requests) == 2
    assert [[message.role.value for message in request.messages] for request in fake.requests] == [
        ["system", "user"],
        ["system", "user", "assistant", "user"],
    ]
    records = agent.last_context_builds()
    assert [(record.origin_architecture, record.request_shape, record.request_stage) for record in records] == [
        ("A0", "a0_decision", "initial"),
        ("A0", "a0_decision", "format_repair"),
    ]


class _RuntimeA1ContractRepairAgent(GameNPCAgent):
    """Let Runtime, not the model parser, exercise the repair protocol boundary."""

    def __init__(self, adapter, *, planning_attempts: int = 1) -> None:
        super().__init__(adapter)
        self.planning_attempts = planning_attempts

    def propose_turn(self, value):
        self._planning_input.value = value
        self._context_builds.records = ()
        self._action_contract_execution.attempts = ()
        self._request_origin.architecture = "A1"
        proposal = proposal_for(
            value.case_observation, value.player_contribution.contribution_id
        )
        action = proposal.decision.action
        invalid_call = action.tool_call.model_copy(
            update={
                "arguments": {
                    "investigation_id": action.tool_call.arguments["investigation_id"],
                    "extra": "not-allowed",
                }
            }
        )
        proposal = proposal.model_copy(
            update={
                "decision": proposal.decision.model_copy(
                    update={"action": action.model_copy(update={"tool_call": invalid_call})}
                )
            }
        )
        self._planning_proposal.value = proposal
        self._planning_execution.result = (
            None
            if self.planning_attempts == 1
            else SimpleNamespace(
                attempts=self.planning_attempts,
                output=proposal,
                repair_kind=None,
                usages=(),
                attempt_telemetry=(),
            )
        )
        return proposal


def _repair_proposal(observation, operation_id: str, target_index: int):
    proposal = proposal_for(observation, operation_id).decision
    option = observation.available_investigations[target_index]
    call = ToolCallRequest(
        name=INVESTIGATION_TOOL_BY_ACTION[option.action_type],
        arguments={"investigation_id": option.investigation_id},
    )
    return proposal.model_copy(
        update={
            "action": proposal.action.model_copy(update={"tool_call": call})
        }
    )


def test_runtime_rejects_publicly_valid_repair_that_mismatches_applied_plan(
    tmp_path: Path,
) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    operation_id = "ce11_repair_mismatch"
    repaired = _repair_proposal(opened.observation, operation_id, 1)
    fake = ScriptedFakeLLM([repaired.model_dump_json()])
    agent = _RuntimeA1ContractRepairAgent(fake)
    clinic.game_npc_agent = agent
    before = clinic.store.load_case_session(opened.session_id)

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, operation_id)
    )
    after = clinic.store.load_case_session(opened.session_id)

    assert result.error_code == "action_outside_active_plan"
    assert result.event_sequences == ()
    assert result.decision.proposal.action.action_type.value == "respond"
    assert "未执行" in result.decision.proposal.action.dialogue
    assert after.revision == before.revision
    assert after.action_history == before.action_history
    assert len(fake.requests) == 1
    record = agent.last_context_builds()[-1]
    assert (
        record.origin_architecture,
        record.request_shape,
        record.request_stage,
    ) == ("A1", "a0_decision", "action_contract_repair")


def test_runtime_executes_publicly_valid_repair_that_still_matches_plan(
    tmp_path: Path,
) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    operation_id = "ce11_repair_match"
    repaired = _repair_proposal(opened.observation, operation_id, 0)
    fake = ScriptedFakeLLM([repaired.model_dump_json()])
    clinic.game_npc_agent = _RuntimeA1ContractRepairAgent(fake)
    before = clinic.store.load_case_session(opened.session_id)

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, operation_id)
    )
    after = clinic.store.load_case_session(opened.session_id)

    assert result.status.value == "action_executed"
    assert result.error_code is None
    assert after.revision == before.revision + 1
    assert len(after.action_history) == len(before.action_history) + 1
    assert len(fake.requests) == 1


def test_runtime_action_repair_failure_falls_back_without_tool_execution(
    tmp_path: Path,
) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    fake = ScriptedFakeLLM(["not-json-repair"])
    clinic.game_npc_agent = _RuntimeA1ContractRepairAgent(fake)
    before = clinic.store.load_case_session(opened.session_id)

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, "ce11_repair_failure")
    )
    after = clinic.store.load_case_session(opened.session_id)

    assert result.status.value == "responded"
    assert result.decision.used_fallback is True
    assert result.event_sequences == ()
    assert after == before
    assert len(fake.requests) == 1


def test_runtime_skips_action_repair_after_prior_format_repair_and_falls_back(
    tmp_path: Path,
) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    fake = ScriptedFakeLLM([])
    clinic.game_npc_agent = _RuntimeA1ContractRepairAgent(
        fake, planning_attempts=2
    )
    before = clinic.store.load_case_session(opened.session_id)

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, "ce11_skip_repair")
    )
    after = clinic.store.load_case_session(opened.session_id)

    assert result.status.value == "responded"
    assert result.decision.used_fallback is True
    assert result.event_sequences == ()
    assert after == before
    assert fake.requests == []


def test_a0_action_repair_remains_unplanned_and_executes_valid_action(
    tmp_path: Path,
) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    operation_id = "ce11_a0_repair"
    invalid = proposal_for(opened.observation, operation_id).decision
    invalid_call = invalid.action.tool_call.model_copy(
        update={
            "arguments": {
                "investigation_id": invalid.action.tool_call.arguments[
                    "investigation_id"
                ],
                "extra": "not-allowed",
            }
        }
    )
    invalid = invalid.model_copy(
        update={
            "action": invalid.action.model_copy(update={"tool_call": invalid_call})
        }
    )
    repaired = _repair_proposal(opened.observation, operation_id, 1)
    fake = ScriptedFakeLLM(
        [invalid.model_dump_json(), repaired.model_dump_json()]
    )
    agent = SimpleActionGameNPCAgent(fake)
    clinic.game_npc_agent = agent

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, operation_id)
    )

    assert result.status.value == "action_executed"
    assert result.error_code is None
    assert len(fake.requests) == 2
    assert [(item.origin_architecture, item.request_shape, item.request_stage) for item in agent.last_context_builds()] == [
        ("A0", "a0_decision", "initial"),
        ("A0", "a0_decision", "action_contract_repair"),
    ]
