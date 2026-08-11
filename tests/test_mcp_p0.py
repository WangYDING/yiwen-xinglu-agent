"""M3-P0 tests use only the official in-process MCP client transport."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from xuanyi_npc.application import MCPApplicationService
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState, PlayerState, ToolName
from xuanyi_npc.mcp_server import FROZEN_MCP_TOOL_NAMES, create_mcp_server
from xuanyi_npc.storage import JsonStateStore, StorageError


CASE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "xuanyi_npc"
    / "resources"
    / "cases"
    / "old_paper_umbrella.json"
)
BASE_ARGUMENTS = {
    "player_id": "player_demo_apprentice",
    "session_id": "session_mcp_umbrella",
}


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class MCPHarness:
    store: JsonStateStore
    service: MCPApplicationService
    server: Any
    player: PlayerState
    initial_session: CaseSessionState
    session_path: Path


def build_harness(root: Path) -> MCPHarness:
    store = JsonStateStore(root)
    player = build_demo_player()
    case = CaseDefinition.model_validate_json(CASE_PATH.read_text(encoding="utf-8"))
    session = CaseSessionState(
        session_id=BASE_ARGUMENTS["session_id"],
        case_id=case.case_id,
        player_id=player.player_id,
    )
    store.save_player(player)
    session_path = store.save_case_session(session)
    service = MCPApplicationService(
        state_store=store,
        case_root=CASE_PATH.parent,
        clock=FixedClock(),
    )
    return MCPHarness(
        store=store,
        service=service,
        server=create_mcp_server(service),
        player=player,
        initial_session=session,
        session_path=session_path,
    )


def call_tool(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        async with Client(server) as client:
            result = await client.call_tool(name, arguments)
            assert result.is_error is False
            assert isinstance(result.structured_content, dict)
            return result.structured_content

    return asyncio.run(invoke())


def test_client_discovers_exact_frozen_tool_surface_and_strict_schemas(
    tmp_path: Path,
) -> None:
    harness = build_harness(tmp_path)

    async def inspect_tools() -> None:
        async with Client(harness.server) as client:
            tools = (await client.list_tools()).tools
            assert tuple(tool.name for tool in tools) == FROZEN_MCP_TOOL_NAMES
            for tool in tools:
                schema = tool.input_schema
                assert schema["type"] == "object"
                assert schema["additionalProperties"] is False
                assert {"player_id", "session_id"}.issubset(schema["required"])
            assert (await client.list_resources()).resources == []
            assert (await client.list_prompts()).prompts == []

    asyncio.run(inspect_tools())


@pytest.mark.parametrize("tool_name", ["get_player_view", "get_case_observation"])
def test_read_tools_do_not_change_persisted_state(
    tmp_path: Path,
    tool_name: str,
) -> None:
    harness = build_harness(tmp_path)
    before = harness.session_path.read_bytes()

    result = call_tool(harness.server, tool_name, dict(BASE_ARGUMENTS))

    assert result["ok"] is True
    assert result["session_revision"] == 0
    assert result["event_sequences"] == []
    assert harness.session_path.read_bytes() == before


def test_legal_investigation_emits_existing_event_and_persists_state(
    tmp_path: Path,
) -> None:
    harness = build_harness(tmp_path)

    result = call_tool(
        harness.server,
        "observe_patient",
        {**BASE_ARGUMENTS, "investigation_id": "observe_scholar"},
    )

    persisted = harness.store.load_case_session(BASE_ARGUMENTS["session_id"])
    assert result["ok"] is True
    assert result["event_sequences"] == [1]
    assert result["session_revision"] == 1
    assert persisted.revision == 1
    assert persisted.action_history[0].reference_id == "observe_scholar"
    assert result["case_observation"]["session_revision"] == 1
    assert "observe_scholar" not in {
        option["investigation_id"]
        for option in result["case_observation"]["available_investigations"]
    }


def test_diagnosis_policy_rejection_refreshes_options_without_writing(
    tmp_path: Path,
) -> None:
    harness = build_harness(tmp_path)
    before = harness.session_path.read_bytes()

    result = call_tool(
        harness.server,
        "submit_diagnosis",
        {
            **BASE_ARGUMENTS,
            "diagnosis_id": "rain_vow_breach",
            "evidence_clue_ids": [],
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "diagnosis_not_ready"
    assert result["event_sequences"] == []
    assert result["session_revision"] == 0
    assert result["case_observation"]["can_submit_diagnosis"] is False
    assert result["case_observation"]["available_investigations"]
    assert harness.session_path.read_bytes() == before


def test_unknown_investigation_is_rejected_without_writing(tmp_path: Path) -> None:
    harness = build_harness(tmp_path)
    before = harness.session_path.read_bytes()

    result = call_tool(
        harness.server,
        "observe_patient",
        {**BASE_ARGUMENTS, "investigation_id": "unknown_public_option"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "unknown_investigation"
    assert result["event_sequences"] == []
    assert harness.session_path.read_bytes() == before


def test_repeated_investigation_is_rejected_without_a_second_write(
    tmp_path: Path,
) -> None:
    harness = build_harness(tmp_path)
    first = call_tool(
        harness.server,
        "observe_patient",
        {**BASE_ARGUMENTS, "investigation_id": "observe_scholar"},
    )
    assert first["ok"] is True
    after_first = harness.session_path.read_bytes()

    repeated = call_tool(
        harness.server,
        "observe_patient",
        {**BASE_ARGUMENTS, "investigation_id": "observe_scholar"},
    )

    assert repeated["ok"] is False
    assert repeated["error_code"] == "investigation_already_completed"
    assert repeated["event_sequences"] == []
    assert repeated["session_revision"] == 1
    assert harness.session_path.read_bytes() == after_first


@pytest.mark.parametrize(
    "arguments",
    [
        BASE_ARGUMENTS,
        {**BASE_ARGUMENTS, "investigation_id": "observe_scholar", "extra": True},
        {
            **BASE_ARGUMENTS,
            "investigation_id": 123,
        },
    ],
)
def test_invalid_mcp_arguments_are_structured_and_do_not_write(
    tmp_path: Path,
    arguments: dict[str, Any],
) -> None:
    harness = build_harness(tmp_path)
    before = harness.session_path.read_bytes()

    result = call_tool(harness.server, "observe_patient", arguments)

    assert result["ok"] is False
    assert result["error_code"] == "invalid_tool_arguments"
    assert result["event_sequences"] == []
    assert result["session_revision"] == 0
    assert result["case_observation"]["available_investigations"]
    assert harness.session_path.read_bytes() == before


def test_mcp_cannot_bypass_fixed_v0_diagnosis_policy(tmp_path: Path) -> None:
    harness = build_harness(tmp_path)
    before = harness.session_path.read_bytes()

    forged = call_tool(
        harness.server,
        "submit_diagnosis",
        {
            **BASE_ARGUMENTS,
            "diagnosis_id": "rain_vow_breach",
            "evidence_clue_ids": [],
            "can_submit_diagnosis": True,
        },
    )
    ordinary = call_tool(
        harness.server,
        "submit_diagnosis",
        {
            **BASE_ARGUMENTS,
            "diagnosis_id": "rain_vow_breach",
            "evidence_clue_ids": [],
        },
    )

    assert forged["error_code"] == "invalid_tool_arguments"
    assert ordinary["error_code"] == "diagnosis_not_ready"
    assert harness.session_path.read_bytes() == before


REFERENCE_ACTIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("observe_patient", {"investigation_id": "observe_scholar"}),
    ("question_patient", {"investigation_id": "ask_about_memory"}),
    ("inspect_object", {"investigation_id": "inspect_umbrella"}),
    ("observe_qi", {"investigation_id": "observe_contract_trace"}),
    ("inspect_object", {"investigation_id": "search_book_chest"}),
    ("question_patient", {"investigation_id": "ask_about_promise"}),
    (
        "submit_diagnosis",
        {
            "diagnosis_id": "rain_vow_breach",
            "evidence_clue_ids": [
                "fading_shadow",
                "forgotten_faces",
                "umbrella_night_water",
                "vow_knot_trace",
                "hidden_wooden_token",
                "broken_promise",
            ],
        },
    ),
    (
        "execute_treatment",
        {"treatment_id": "return_token_and_fulfill_vow"},
    ),
)


def test_complete_mcp_reference_trace_matches_direct_application_service(
    tmp_path: Path,
) -> None:
    mcp_harness = build_harness(tmp_path / "mcp")
    direct_harness = build_harness(tmp_path / "direct")

    async def run_mcp_trace() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        async with Client(mcp_harness.server) as client:
            for name, tool_arguments in REFERENCE_ACTIONS:
                call = await client.call_tool(
                    name,
                    {**BASE_ARGUMENTS, **tool_arguments},
                )
                assert call.is_error is False
                assert isinstance(call.structured_content, dict)
                results.append(call.structured_content)
        return results

    mcp_results = asyncio.run(run_mcp_trace())
    direct_results = []
    for name, tool_arguments in REFERENCE_ACTIONS:
        direct_results.append(
            direct_harness.service.execute_tool(
                tool_name=ToolName(name),
                player_id=BASE_ARGUMENTS["player_id"],
                session_id=BASE_ARGUMENTS["session_id"],
                tool_arguments=tool_arguments,
            )
        )

    assert all(result["ok"] for result in mcp_results)
    assert [result["event_sequences"] for result in mcp_results] == [
        [index] for index in range(1, 9)
    ]
    assert all(result.ok for result in direct_results)
    mcp_final = mcp_harness.store.load_case_session(BASE_ARGUMENTS["session_id"])
    direct_final = direct_harness.store.load_case_session(BASE_ARGUMENTS["session_id"])
    assert mcp_final == direct_final
    assert mcp_final.revision == 8
    assert mcp_final.status.value == "completed"
    assert mcp_final.outcome.value == "resolved"
    assert mcp_final.score == 100


def test_returned_content_contains_only_safe_public_fields(tmp_path: Path) -> None:
    harness = build_harness(tmp_path)
    result = call_tool(harness.server, "get_case_observation", dict(BASE_ARGUMENTS))
    serialized = json.dumps(result, ensure_ascii=False).lower()

    forbidden = (
        "root_cause",
        "valid_diagnosis_ids",
        "unfulfilled_rain_vow_contract",
        "diagnosis_correct",
        "is_key",
        "required_clue_ids",
        "unsafe_treatment_penalty",
        "api_key",
        str(tmp_path).lower(),
    )
    assert not any(value in serialized for value in forbidden)


def test_unexpected_internal_failure_is_safely_redacted(tmp_path: Path) -> None:
    harness = build_harness(tmp_path)

    def explode(_: str) -> PlayerState:
        raise RuntimeError("secret path C:/private and API key should not escape")

    harness.store.load_player = explode  # type: ignore[method-assign]
    result = call_tool(harness.server, "get_player_view", dict(BASE_ARGUMENTS))
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["ok"] is False
    assert result["error_code"] == "internal_error"
    assert result["event_sequences"] == []
    assert "secret path" not in serialized
    assert "API key" not in serialized


def test_persistence_failure_returns_no_event_and_leaves_snapshot_unchanged(
    tmp_path: Path,
) -> None:
    harness = build_harness(tmp_path)
    before = harness.session_path.read_bytes()

    def reject_save(_: CaseSessionState) -> Path:
        raise StorageError("private persistence detail")

    harness.store.save_case_session = reject_save  # type: ignore[method-assign]
    result = call_tool(
        harness.server,
        "observe_patient",
        {**BASE_ARGUMENTS, "investigation_id": "observe_scholar"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "internal_error"
    assert result["event_sequences"] == []
    assert result["session_revision"] == 0
    assert harness.session_path.read_bytes() == before
