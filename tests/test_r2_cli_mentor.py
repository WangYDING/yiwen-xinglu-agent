from xuanyi_npc.cli.play import build_parser
import subprocess
import sys
from tests.test_play_cli import REPO_ROOT, safe_child_environment, seed_cli_workspace
from xuanyi_npc.storage import JsonStateStore


def test_mentor_mode_defaults_off_and_exposes_only_fake(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["--state-dir", str(tmp_path)])
    assert args.mentor_mode == "off"
    args = parser.parse_args(["--state-dir", str(tmp_path), "--mentor-mode", "fake"])
    assert args.mentor_mode == "fake"


def test_fake_mentor_cli_completes_old_umbrella_with_review(tmp_path):
    case_dir, state_dir = seed_cli_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable, "-m", "xuanyi_npc.cli.play",
            "--case-dir", str(case_dir), "--state-dir", str(state_dir),
            "--mode", "manual", "--mentor-mode", "fake",
        ],
        input=(
            "1\n导师学徒\n1\n1\n"
            "1\n1\n1\n事实来自已发现线索，根因仍需核对。\n"
            "1\n1\n1\n3\n5\n99\n"
        ).encode("utf-8"),
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert completed.stderr == b""
    output = completed.stdout.decode("utf-8")
    assert "导师课程：证据齐备再定证" in output
    assert "结构化师评" in output
    assert "结局：resolved｜得分：100" in output
    assert "R1 能力变化" in output and "R1 关系变化" in output
    assert "下一步：下一步练习交叉核对契物来源。" in output
    sessions = JsonStateStore(state_dir).list_teaching_sessions()
    assert len(sessions) == 1 and sessions[0].phase.value == "completed"
