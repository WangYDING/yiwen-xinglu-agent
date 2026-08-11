from tests.r1_helpers import FixedClock, create_player
from tests.r2_helpers import build_teaching
from tests.test_r3_adaptive_teaching import complete_taught_case
from xuanyi_npc.application.exams import ExamService
from xuanyi_npc.application.inheritance import InheritanceService
from xuanyi_npc.application.permissions import PermissionCoordinator


def build_r4(path):
    case_service, teaching, store = build_teaching(path)
    clock = FixedClock()
    permissions = PermissionCoordinator(store, clock)
    exams = ExamService(store, permissions, clock)
    inheritance = InheritanceService(store, permissions, clock)
    return case_service, teaching, store, permissions, exams, inheritance


def complete_excellent_foundation(case_service, teaching, store, player_id):
    for case_id in ("old_paper_umbrella", "gray_hearth_inn", "moon_well_echo"):
        complete_taught_case(case_service, teaching, store, player_id, case_id)


def answer_exam(exams, state, *, fail_critical=False):
    for question in exams.definition.questions:
        selected = question.correct_option_ids
        if fail_critical and question.critical_safety:
            selected = (next(item.option_id for item in question.options if item.option_id not in question.correct_option_ids),)
            fail_critical = False
        state = exams.record_answer(
            player_id=state.player_id, exam_session_id=state.exam_session_id,
            question_id=question.question_id, selected_option_ids=selected,
        )
    return state

