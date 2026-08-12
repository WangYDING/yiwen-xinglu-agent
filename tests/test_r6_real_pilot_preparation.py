from xuanyi_npc.evaluation.real_mentor_pilot import main


def test_paid_pilot_requires_explicit_confirmation_and_never_runs_offline(capsys):
    assert main([]) == 2
    assert "--confirm-paid-run" in capsys.readouterr().out
    assert main(["--confirm-paid-run"]) == 3
    assert "未启用任何供应商请求" in capsys.readouterr().out


def test_paid_pilot_rejects_model_or_budget_drift():
    assert main(["--confirm-paid-run", "--model", "other-model"]) == 2
    assert main(["--confirm-paid-run", "--budget-cny", "0.06"]) == 2
