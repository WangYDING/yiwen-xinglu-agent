from tests.test_play_cli import run_cli, seed_cli_workspace


def test_cli_displays_deterministic_growth_after_completion(tmp_path) -> None:
    case_dir, state_dir = seed_cli_workspace(tmp_path)
    completed = run_cli(
        case_dir,
        state_dir,
        "1\n成长学徒\n1\n1\n1\n1\n1\n1\n1\n1\n3\n5\n99\n",
    )

    assert completed.returncode == 0
    assert completed.stderr == b""
    output = completed.stdout.decode("utf-8")
    assert "本次成长" in output
    assert "察形：20 → 21（+1）" in output
    assert "信任：10 → 11（+1）" in output
    assert "认可：10 → 12（+2）" in output
    assert "亲近：" not in output
