import pytest

from xuanyi_npc.application import SubmitActionInput, TeachingRequest
from xuanyi_npc.domain import ToolName
from tests.r1_helpers import action, create_player
from tests.r2_helpers import build_teaching, start_teaching


def finish_bound(case_service, store, player_id, session_id, diagnosis, treatment):
    case = case_service.case_catalog.get("old_paper_umbrella")
    tools = {
        "observe_patient": ToolName.OBSERVE_PATIENT,
        "question_patient": ToolName.QUESTION_PATIENT,
        "inspect_object": ToolName.INSPECT_OBJECT,
        "observe_qi": ToolName.OBSERVE_QI,
    }
    index = 0
    for investigation in case.investigations:
        index += 1
        assert case_service.submit_action(
            SubmitActionInput(
                player_id=player_id, case_id=case.case_id, session_id=session_id,
                action=action(tools[investigation.action_type.value], {"investigation_id": investigation.investigation_id}, index),
            )
        ).ok
    session = store.load_case_session(session_id)
    index += 1
    assert case_service.submit_action(
        SubmitActionInput(
            player_id=player_id, case_id=case.case_id, session_id=session_id,
            action=action(ToolName.SUBMIT_DIAGNOSIS, {"diagnosis_id": diagnosis, "evidence_clue_ids": sorted(session.discovered_clue_ids)}, index),
        )
    ).ok
    index += 1
    return case_service.submit_action(
        SubmitActionInput(
            player_id=player_id, case_id=case.case_id, session_id=session_id,
            action=action(ToolName.EXECUTE_TREATMENT, {"treatment_id": treatment}, index),
        )
    )


@pytest.mark.parametrize(
    ("diagnosis", "treatment", "outcome"),
    (
        ("exam_exhaustion", "return_token_and_fulfill_vow", "resolved"),
        ("rain_vow_breach", "seal_old_umbrella", "suppressed"),
        ("evil_spirit_attack", "burn_old_umbrella", "worsened"),
    ),
)
def test_nonideal_reports_differ_without_hidden_truth(tmp_path, diagnosis, treatment, outcome):
    case_service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(case_service, outcome)
    started, state = start_teaching(case_service, teaching, player_id)
    finish_bound(case_service, store, player_id, started.session_id, diagnosis, treatment)
    result = teaching.observe_case_completion(
        TeachingRequest(player_id=player_id, teaching_session_id=state.teaching_session_id)
    )
    report = result.state.assessment
    assert result.ok and report.outcome.value == outcome
    serialized = report.model_dump_json()
    assert "root_cause" not in serialized and "valid_diagnosis" not in serialized
    if diagnosis != "rain_vow_breach":
        assert "reason_diagnosis" in [item.value for item in report.improvement_abilities]
        assert "align_treatment_with_judgment" in report.missed_objectives
    if outcome in {"suppressed", "worsened"}:
        assert "apply_treatment" in [item.value for item in report.improvement_abilities]
        assert "align_treatment_with_judgment" in report.missed_objectives
        assert "圆满" not in result.state.mentor_review.message
