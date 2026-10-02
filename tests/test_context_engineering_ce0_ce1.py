from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekChatAdapter,
    LLMResponse,
    ScriptedFakeLLM,
)
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.action_contract import build_safe_action_feedback
from xuanyi_npc.domain.cooperation import GameNPCDecision
from tests.context_baseline_support import action_input, planning_input
from tests.test_phase_a_production_wiring import contribution, opened_clinic


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "context_engineering"
    / "ce0_requests.json"
)


def _frozen_requests():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["requests"]


def _dump(request):
    # Keep the historical prompt/schema baseline; assert the intentional budget migration separately.
    assert request.max_output_tokens == (2048 if request.response_schema.get("title") == "GameNPCTurnProposal" else 512)
    result = request.model_dump(mode="json")
    if type(request).__name__ != "GameNPCPlanningRequest":
        result.pop("max_output_tokens", None)
    return result


def _action_contract_repair_request(agent, value):
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
        build_safe_action_feedback("invalid_tool_arguments", value.case_observation),
    )
    return agent.adapter.requests[0]


def test_refactored_builder_preserves_all_frozen_actual_requests() -> None:
    """Compare adapter-bound requests, not merely ContextAssembler internals."""

    expected = _frozen_requests()
    action = action_input()
    planning = planning_input()
    invalid = LLMResponse(content="not-json-baseline")
    error = ValueError("baseline validation error")

    direct = GameNPCAgent(ScriptedFakeLLM([]))
    action_request = direct._request(action)
    planning_request = direct._planning_request(planning)
    action_repair = direct._format_repair_request(action_request, invalid, error, action)
    planning_repair = direct._format_planning_repair_request(
        planning_request, invalid, error, planning
    )
    contract_agent = GameNPCAgent(ScriptedFakeLLM(["not-json-baseline"]))
    contract_repair = _action_contract_repair_request(contract_agent, action)

    actual = {
        "a0_initial": _dump(action_request),
        "a0_format_repair": _dump(action_repair),
        "a0_action_contract_repair": _dump(contract_repair),
        "a1_initial_full_state": _dump(planning_request),
        "a1_format_repair_full_state": _dump(planning_repair),
    }
    assert actual == expected


def test_a1_initial_and_format_repair_emit_separate_non_model_build_records() -> None:
    value = planning_input()
    fake = ScriptedFakeLLM(["not-json-baseline", "still-not-json-baseline"])
    agent = GameNPCAgent(fake)

    agent.propose_turn(value)

    assert len(fake.requests) == 2
    records = agent.last_context_builds()
    assert tuple(
        (item.origin_architecture, item.request_shape, item.request_stage)
        for item in records
    ) == (
        ("A1", "a1_turn", "initial"),
        ("A1", "a1_turn", "format_repair"),
    )
    assert records[0].requested_max_output_tokens == 2048
    # Existing behavior is intentionally frozen: the repair is a base
    # LLMRequest and therefore uses the adapter default output configuration.
    assert records[1].requested_max_output_tokens == 2048
    assert records[0].token_count_method == "not_measured"
    assert records[0].provider_payload_measurement == "not_measured"
    assert records[0].prompt_source_ref.endswith("GAME_NPC_M2_PLANNING_PROMPT")
    assert records[0].prompt_sha256 == hashlib.sha256(
        fake.requests[0].messages[0].content.encode("utf-8")
    ).hexdigest()
    assert records[0].exact_message_content_utf8_byte_count == len(
        "".join(message.content for message in fake.requests[0].messages).encode(
            "utf-8"
        )
    )
    assert all(
        item.exact_content_character_count >= 0 for item in records[0].blocks
    )
    assert all(item.source_revision.startswith("sha256:") for item in records[0].blocks)
    assert "ContextBuildTrace" not in "".join(
        message.content for request in fake.requests for message in request.messages
    )


def test_a0_action_contract_repair_record_keeps_a0_interface() -> None:
    value = action_input()
    fake = ScriptedFakeLLM(["not-json-baseline"])
    agent = GameNPCAgent(fake)

    _action_contract_repair_request(agent, value)

    record = agent.last_context_builds()[-1]
    assert record.origin_architecture == "A1"
    assert record.request_shape == "a0_decision"
    assert record.request_stage == "action_contract_repair"
    assert record.requested_max_output_tokens == 512
    assert [message.role.value for message in fake.requests[0].messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert record.exact_message_content_character_count == sum(
        len(message.content) for message in fake.requests[0].messages
    )


def test_ce0_fixture_records_content_identity_not_only_git_commit() -> None:
    identity = json.loads(FIXTURE.read_text(encoding="utf-8"))["baseline_identity"]

    assert len(identity["git_commit"]) == 40
    assert len(identity["workspace_status_sha256"]) == 64
    assert len(identity["files"]) >= 10
    assert all(len(digest) == 64 for digest in identity["files"].values())


def test_provider_payload_configuration_is_frozen_for_initial_and_repairs() -> None:
    value = action_input()
    planning = planning_input()
    invalid = LLMResponse(content="not-json-baseline")
    error = ValueError("baseline validation error")
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    requests = (
        agent._request(value),
        agent._planning_request(planning),
    )
    requests = (
        *requests,
        agent._format_repair_request(requests[0], invalid, error, value),
        agent._format_planning_repair_request(requests[1], invalid, error, planning),
    )
    adapter = DeepSeekChatAdapter(DeepSeekAdapterConfig(api_key="offline-test-key"))
    try:
        payloads = tuple(adapter._chat_payload(request) for request in requests)
    finally:
        adapter.close()

    assert tuple(payload["max_tokens"] for payload in payloads) == (512, 2048, 512, 2048)
    for payload in payloads:
        assert payload["stream"] is False
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["temperature"] == 0
        assert payload["model"] == "deepseek-v4-flash"


def test_formal_clinic_entry_reaches_actual_initial_and_repair_requests(tmp_path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    fake = ScriptedFakeLLM(["not json", "still not json"])
    agent = GameNPCAgent(fake)
    clinic.game_npc_agent = agent

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, "ce1_formal_entry")
    )

    assert result.decision.used_fallback is True
    assert len(fake.requests) == 2
    initial, repair = fake.requests
    assert [message.role.value for message in initial.messages] == ["system", "user"]
    assert [message.role.value for message in repair.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    initial_context = initial.messages[-1].content
    for required in (
        "AUTHORITATIVE_WORLD_case_observation",
        "AUTHORITATIVE_CONSTRAINTS_authority_view",
        "AGENT_INTENT_current_goal",
        "AUTHORITATIVE_PUBLIC_ACTION_SPACE_available_actions",
        "PLAYER_BELIEF_player_contribution",
        "ce1_formal_entry",
    ):
        assert required in initial_context
    assert initial.response_schema == repair.response_schema
    assert tuple(
        (item.origin_architecture, item.request_shape, item.request_stage)
        for item in agent.last_context_builds()
    ) == (
        ("A1", "a1_turn", "initial"),
        ("A1", "a1_turn", "format_repair"),
    )
