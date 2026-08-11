from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from xuanyi_npc.domain import (
    CaseDefinition,
    CaseEvent,
    CaseSessionState,
    DiagnosisSubmittedEvent,
    InvestigationCompletedEvent,
    TreatmentExecutedEvent,
)
from xuanyi_npc.engine import CaseEventReplayer
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
PROCESS_TIMEOUT_SECONDS = 20


def seed_cli_workspace(root: Path) -> tuple[Path, Path]:
    case_dir = root / "cases"
    state_dir = root / "states"
    case_dir.mkdir()
    state_dir.mkdir()
    shutil.copy2(SOURCE_CASE, case_dir / SOURCE_CASE.name)
    return case_dir, state_dir


def safe_child_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DEEPSEEK_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
    }
    environment.update(
        {
            "PYTHONPATH": str(SOURCE_ROOT),
            "PYTHONIOENCODING": "utf-8",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    return environment


def run_cli(
    case_dir: Path,
    state_dir: Path,
    script: str,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "xuanyi_npc.cli.play",
            "--case-dir",
            str(case_dir),
            "--state-dir",
            str(state_dir),
        ],
        input=script.encode("utf-8"),
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def only_player_and_session(store: JsonStateStore) -> tuple[str, CaseSessionState]:
    players = store.list_players()
    sessions = store.list_case_sessions()
    assert len(players) == 1
    assert len(sessions) == 1
    return players[0].player_id, sessions[0]


def replay_events(
    case: CaseDefinition,
    session: CaseSessionState,
) -> tuple[CaseEvent, ...]:
    events: list[CaseEvent] = []
    for record in session.action_history:
        if record.action_type.value in {
            "observe_patient",
            "question_patient",
            "inspect_object",
            "observe_qi",
            "investigate_location",
        }:
            events.append(
                InvestigationCompletedEvent(
                    sequence=record.sequence,
                    session_id=session.session_id,
                    occurred_at=record.occurred_at,
                    investigation_id=record.reference_id,
                    action_type=record.action_type,
                    target_id=record.target_id,
                    newly_discovered_clue_ids=record.revealed_clue_ids,
                )
            )
        elif record.action_type.value == "submit_diagnosis":
            events.append(
                DiagnosisSubmittedEvent(
                    sequence=record.sequence,
                    session_id=session.session_id,
                    occurred_at=record.occurred_at,
                    diagnosis_id=record.reference_id,
                    evidence_clue_ids=record.evidence_clue_ids,
                )
            )
        else:
            assert session.outcome is not None
            assert session.score is not None
            events.append(
                TreatmentExecutedEvent(
                    sequence=record.sequence,
                    session_id=session.session_id,
                    occurred_at=record.occurred_at,
                    treatment_id=record.reference_id,
                    outcome=session.outcome,
                    diagnosis_correct=(
                        session.submitted_diagnosis_id in case.valid_diagnosis_ids
                    ),
                    score=session.score,
                )
            )
    return tuple(events)


def test_importing_play_cli_has_no_output_file_or_network_side_effects(
    tmp_path: Path,
) -> None:
    case_dir, state_dir = seed_cli_workspace(tmp_path)
    before = snapshot(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-c", "import xuanyi_npc.cli.play"],
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert snapshot(tmp_path) == before
    assert case_dir.is_dir()
    assert state_dir.is_dir()


def test_bad_cli_startup_is_nonzero_without_traceback_or_file_changes(
    tmp_path: Path,
) -> None:
    case_dir, state_dir = seed_cli_workspace(tmp_path)
    before = snapshot(tmp_path)
    missing = tmp_path / "missing_states"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "xuanyi_npc.cli.play",
            "--case-dir",
            str(case_dir),
            "--state-dir",
            str(missing),
        ],
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert completed.stderr
    assert b"Traceback" not in completed.stderr
    assert str(missing).encode("utf-8") not in completed.stderr
    assert snapshot(tmp_path) == before
    assert state_dir.is_dir()


def test_two_real_cli_processes_resume_one_episode_with_contiguous_state(
    tmp_path: Path,
) -> None:
    case_dir, state_dir = seed_cli_workspace(tmp_path)
    environment = safe_child_environment()
    command = [
        sys.executable,
        "-m",
        "xuanyi_npc.cli.play",
        "--case-dir",
        str(case_dir),
        "--state-dir",
        str(state_dir),
    ]

    first = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    first_stdout, first_stderr = first.communicate(
        "1\n旅人甲\n1\n1\n1\n99\n".encode("utf-8"),
        timeout=PROCESS_TIMEOUT_SECONDS,
    )
    first_pid = first.pid
    store = JsonStateStore(state_dir)
    player_id, first_session = only_player_and_session(store)

    second = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    second_stdout, second_stderr = second.communicate(
        "2\n1\n1\n1\n1\n99\n".encode("utf-8"),
        timeout=PROCESS_TIMEOUT_SECONDS,
    )
    second_pid = second.pid
    _, second_session = only_player_and_session(store)

    assert first.returncode == second.returncode == 0
    assert first_pid != second_pid
    assert first.poll() == second.poll() == 0
    assert first_stderr == second_stderr == b""
    assert b"Traceback" not in first_stdout + second_stdout
    assert "已恢复未完成病例" in second_stdout.decode("utf-8")
    assert first_session.session_id == second_session.session_id
    assert first_session.revision == 1
    assert second_session.revision == 2
    assert [record.sequence for record in second_session.action_history] == [1, 2]
    assert store.list_players()[0].player_id == player_id
    assert len(store.list_case_sessions()) == 1


def test_complete_no_llm_cli_reference_is_resolved_100_and_replayable(
    tmp_path: Path,
) -> None:
    case_dir, state_dir = seed_cli_workspace(tmp_path)
    script = "1\n完整学徒\n1\n1\n1\n1\n1\n1\n1\n1\n3\n5\n99\n"

    completed = run_cli(case_dir, state_dir, script)

    assert completed.returncode == 0
    assert completed.stderr == b""
    output = completed.stdout.decode("utf-8")
    assert "病例公开结果" in output
    assert "结局：resolved" in output
    assert "得分：100" in output
    assert "Traceback" not in output

    store = JsonStateStore(state_dir)
    _, final = only_player_and_session(store)
    assert final.revision == 8
    assert final.outcome is not None and final.outcome.value == "resolved"
    assert final.score == 100
    assert [record.sequence for record in final.action_history] == list(range(1, 9))

    case = CaseDefinition.model_validate_json(SOURCE_CASE.read_text(encoding="utf-8"))
    initial = CaseSessionState(
        session_id=final.session_id,
        case_id=final.case_id,
        player_id=final.player_id,
    )
    replayed = CaseEventReplayer().replay(initial, replay_events(case, final))
    assert replayed == final


def test_eof_exits_cleanly_without_creating_state(tmp_path: Path) -> None:
    case_dir, state_dir = seed_cli_workspace(tmp_path)

    completed = run_cli(case_dir, state_dir, "")

    assert completed.returncode == 0
    assert completed.stderr == b""
    assert JsonStateStore(state_dir).list_players() == ()
    assert JsonStateStore(state_dir).list_case_sessions() == ()
