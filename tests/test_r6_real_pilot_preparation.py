from pathlib import Path

from xuanyi_npc.evaluation.real_mentor_pilot import main


def test_paid_pilot_requires_confirmation_budget_and_output(tmp_path, capsys):
    assert main([]) == 2
    assert main(["--budget-cny", "0.05", "--output", str(tmp_path)]) == 2
    assert "--confirm-paid-run" in capsys.readouterr().out


def test_paid_pilot_rejects_budget_drift_before_v2_dispatch(tmp_path: Path):
    base = ["--confirm-paid-run", "--output", str(tmp_path), "--budget-cny"]
    assert main([*base, "1.00"]) == 2
    assert main([*base, "0.04"]) == 2
    assert main([*base, "invalid"]) == 2
