"""M3-P1 integration tests against a real MCP stdio child process."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import get_default_environment

from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState
from xuanyi_npc.mcp_server import FROZEN_MCP_TOOL_NAMES
from xuanyi_npc.storage import JsonStateStore


REPO_ROOT = Path(__file__).parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
SOURCE_CASE = (
    REPO_ROOT
    / "src"
    / "xuanyi_npc"
    / "resources"
    / "cases"
    / "old_paper_umbrella.json"
)
PLAYER_ID = "player_demo_apprentice"
SESSION_ID = "session_stdio_umbrella"
PROCESS_TIMEOUT_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 10


REFERENCE_REMAINDER: tuple[tuple[str, dict[str, Any]], ...] = (
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


def safe_child_environment() -> dict[str, str]:
    return {
        **get_default_environment(),
        "PYTHONPATH": str(SOURCE_ROOT),
        "PYTHONIOENCODING": "utf-8",
    }


def seed_stdio_workspace(root: Path) -> tuple[Path, Path, Path]:
    case_dir = root / "cases"
    state_dir = root / "states"
    case_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    case_path = case_dir / SOURCE_CASE.name
    shutil.copy2(SOURCE_CASE, case_path)

    case = CaseDefinition.model_validate_json(case_path.read_text(encoding="utf-8"))
    player = build_demo_player()
    session = CaseSessionState(
        session_id=SESSION_ID,
        case_id=case.case_id,
        player_id=player.player_id,
    )
    store = JsonStateStore(state_dir)
    store.save_player(player)
    session_path = store.save_case_session(session)
    return case_dir, state_dir, session_path


def server_parameters(case_dir: Path, state_dir: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "xuanyi_npc.mcp_server.stdio",
            "--case-dir",
            str(case_dir),
            "--state-dir",
            str(state_dir),
        ],
        env=safe_child_environment(),
        cwd=REPO_ROOT,
    )


def structured(result: Any) -> dict[str, Any]:
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_mcp_sdk_remains_pinned_to_2_0_0() -> None:
    assert version("mcp") == "2.0.0"


def test_importing_stdio_module_has_no_output_or_side_effects(tmp_path: Path) -> None:
    case_dir, state_dir, _ = seed_stdio_workspace(tmp_path)
    before = tree_snapshot(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-c", "import xuanyi_npc.mcp_server.stdio"],
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=REQUEST_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert tree_snapshot(tmp_path) == before
    assert case_dir.is_dir()
    assert state_dir.is_dir()


def test_real_stdio_subprocess_supports_restart_persistence_and_clean_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_dir, state_dir, session_path = seed_stdio_workspace(tmp_path)
    parameters = server_parameters(case_dir, state_dir)
    stdio_module = importlib.import_module("mcp.client.stdio")
    original_spawn: Callable[..., Any] = stdio_module._create_platform_compatible_process
    spawned: list[Any] = []

    async def capture_spawn(*args: Any, **kwargs: Any) -> Any:
        process = await original_spawn(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(
        stdio_module,
        "_create_platform_compatible_process",
        capture_spawn,
    )

    async def run_lifecycle() -> tuple[list[int], str, str]:
        event_sequences: list[int] = []
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as first_stderr:
            with anyio.fail_after(PROCESS_TIMEOUT_SECONDS):
                async with Client(
                    stdio_module.stdio_client(parameters, errlog=first_stderr),
                    read_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                ) as client:
                    tools = (await client.list_tools()).tools
                    assert tuple(tool.name for tool in tools) == FROZEN_MCP_TOOL_NAMES

                    read_result = structured(
                        await client.call_tool(
                            "get_case_observation",
                            {"player_id": PLAYER_ID, "session_id": SESSION_ID},
                        )
                    )
                    assert read_result["ok"] is True
                    assert read_result["session_revision"] == 0
                    assert read_result["case_observation"]["discovered_clues"] == []

                    before_rejection = session_path.read_bytes()
                    rejected = structured(
                        await client.call_tool(
                            "submit_diagnosis",
                            {
                                "player_id": PLAYER_ID,
                                "session_id": SESSION_ID,
                                "diagnosis_id": "rain_vow_breach",
                                "evidence_clue_ids": [],
                            },
                        )
                    )
                    assert rejected["ok"] is False
                    assert rejected["error_code"] == "diagnosis_not_ready"
                    assert rejected["event_sequences"] == []
                    assert rejected["session_revision"] == 0
                    assert rejected["case_observation"]["available_investigations"]
                    assert session_path.read_bytes() == before_rejection

                    first_action = structured(
                        await client.call_tool(
                            "observe_patient",
                            {
                                "player_id": PLAYER_ID,
                                "session_id": SESSION_ID,
                                "investigation_id": "observe_scholar",
                            },
                        )
                    )
                    assert first_action["ok"] is True
                    event_sequences.extend(first_action["event_sequences"])
            first_stderr.seek(0)
            first_log = first_stderr.read()

        assert len(spawned) == 1
        assert spawned[0].returncode == 0
        assert JsonStateStore(state_dir).load_case_session(SESSION_ID).revision == 1

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as second_stderr:
            with anyio.fail_after(PROCESS_TIMEOUT_SECONDS):
                async with Client(
                    stdio_module.stdio_client(parameters, errlog=second_stderr),
                    read_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                ) as client:
                    restored = structured(
                        await client.call_tool(
                            "get_case_observation",
                            {"player_id": PLAYER_ID, "session_id": SESSION_ID},
                        )
                    )
                    assert restored["session_revision"] == 1
                    assert "observe_scholar" not in {
                        option["investigation_id"]
                        for option in restored["case_observation"][
                            "available_investigations"
                        ]
                    }

                    for tool_name, arguments in REFERENCE_REMAINDER:
                        result = structured(
                            await client.call_tool(
                                tool_name,
                                {
                                    "player_id": PLAYER_ID,
                                    "session_id": SESSION_ID,
                                    **arguments,
                                },
                            )
                        )
                        assert result["ok"] is True
                        event_sequences.extend(result["event_sequences"])
            second_stderr.seek(0)
            second_log = second_stderr.read()

        return event_sequences, first_log, second_log

    event_sequences, first_log, second_log = anyio.run(run_lifecycle)
    final = JsonStateStore(state_dir).load_case_session(SESSION_ID)

    assert event_sequences == list(range(1, 9))
    assert final.revision == 8
    assert final.status.value == "completed"
    assert final.outcome.value == "resolved"
    assert final.score == 100
    assert len(spawned) == 2
    assert spawned[0].pid != spawned[1].pid
    assert all(process.returncode == 0 for process in spawned)
    assert first_log == ""
    assert second_log == ""


@pytest.mark.parametrize(
    "failure_mode",
    [
        "missing_arguments",
        "missing_case_directory",
        "invalid_state_directory",
        "invalid_case_data",
    ],
)
def test_bad_stdio_startup_is_nonzero_and_does_not_pollute_files(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    case_dir, state_dir, _ = seed_stdio_workspace(tmp_path)
    args = ["-m", "xuanyi_npc.mcp_server.stdio"]
    if failure_mode == "missing_case_directory":
        args.extend(
            [
                "--case-dir",
                str(tmp_path / "missing_cases"),
                "--state-dir",
                str(state_dir),
            ]
        )
    elif failure_mode == "invalid_state_directory":
        invalid_state = tmp_path / "state_file"
        invalid_state.write_text("not a directory", encoding="utf-8")
        args.extend(
            [
                "--case-dir",
                str(case_dir),
                "--state-dir",
                str(invalid_state),
            ]
        )
    elif failure_mode == "invalid_case_data":
        (case_dir / "invalid_case.json").write_text("{broken", encoding="utf-8")
        args.extend(
            [
                "--case-dir",
                str(case_dir),
                "--state-dir",
                str(state_dir),
            ]
        )

    before = tree_snapshot(tmp_path)
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=REQUEST_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert completed.stderr
    assert b"Traceback" not in completed.stderr
    assert tree_snapshot(tmp_path) == before
