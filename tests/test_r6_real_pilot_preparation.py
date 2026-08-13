from pathlib import Path

from xuanyi_npc.evaluation.real_mentor_pilot import main


def test_paid_pilot_requires_explicit_v3_confirmation_budget_and_output(tmp_path,capsys):
    assert main([])==2
    assert main(["--pilot-version","v3","--budget-cny","0.05","--output",str(tmp_path)])==2
    assert "--confirm-paid-run" in capsys.readouterr().out


def test_paid_pilot_rejects_budget_drift_before_dispatch(tmp_path:Path):
    base=["--pilot-version","v3","--confirm-paid-run","--output",str(tmp_path),"--budget-cny"]
    assert main([*base,"1.00"])==2
    assert main([*base,"0.04"])==2
    assert main([*base,"invalid"])==2


def test_dry_run_requires_explicit_v3_and_has_zero_transport(capsys):
    assert main(["--pilot-version","v3","--dry-run"])==0
    text=capsys.readouterr().out
    assert '"transport_calls": 0' in text and '"pilot_id": "r6_real_mentor_pilot_v3"' in text
