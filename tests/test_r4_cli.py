from io import StringIO

from xuanyi_npc.cli.play import PlayCLI
from tests.r1_helpers import create_player
from tests.r4_helpers import build_r4, complete_excellent_foundation


def test_cli_shows_stage_runs_exam_and_grants_inheritance(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    output = StringIO()
    answers = iter(["1"] * 6)
    cli = PlayCLI(
        cases, input_fn=lambda _: next(answers), stdout=output,
        teaching_service=teaching, permission_coordinator=permissions,
        exam_service=exams, inheritance_service=inheritance,
    )
    cli._show_r4_status(player)
    cli._run_exam_menu(player)
    cli._run_inheritance_menu(player)
    text = output.getvalue()
    assert "候考弟子" in text
    assert "考试得分：100" in text and "结果：通过" in text
    assert "溯契还因" in text


def test_cli_refusal_shows_only_public_categories(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    output = StringIO()
    cli = PlayCLI(
        cases, input_fn=lambda _: "0", stdout=output,
        teaching_service=teaching, permission_coordinator=permissions,
        exam_service=exams, inheritance_service=inheritance,
    )
    cli._run_inheritance_menu(player)
    text = output.getvalue()
    assert "公开原因类别" in text
    assert "minimum_proficiency" not in text and "passing_score" not in text
