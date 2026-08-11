from xuanyi_npc.application import (
    CreateTeachingSessionInput,
    SubmitActionInput,
    TeachingRequest,
)
from xuanyi_npc.domain import AgentActionType, ToolCallRequest, ToolName
from tests.r1_helpers import action, complete_case, create_player
from tests.r2_helpers import build_teaching, start_teaching
from tests.r2_helpers import investigate_all
from xuanyi_npc.application import SubmitReflectionInput


def test_correct_loop_is_idempotent_and_assessment_explains_r1(tmp_path):
    case_service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(case_service)
    started, teaching_state = start_teaching(case_service, teaching, player_id)
    duplicate = teaching.create(
        CreateTeachingSessionInput(player_id=player_id, case_session_id=started.session_id)
    )
    assert duplicate.state.teaching_session_id == teaching_state.teaching_session_id

    # Complete the already-bound session through the formal case service.
    case = case_service.case_catalog.get("old_paper_umbrella")
    index = 0
    for investigation in case.investigations:
        index += 1
        assert case_service.submit_action(
            SubmitActionInput(
                player_id=player_id,
                case_id=case.case_id,
                session_id=started.session_id,
                action=action(
                    {
                        "observe_patient": ToolName.OBSERVE_PATIENT,
                        "question_patient": ToolName.QUESTION_PATIENT,
                        "inspect_object": ToolName.INSPECT_OBJECT,
                        "observe_qi": ToolName.OBSERVE_QI,
                    }[investigation.action_type.value],
                    {"investigation_id": investigation.investigation_id},
                    index,
                ),
            )
        ).ok
    session = store.load_case_session(started.session_id)
    index += 1
    assert case_service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case.case_id,
            session_id=started.session_id,
            action=action(
                ToolName.SUBMIT_DIAGNOSIS,
                {"diagnosis_id": "rain_vow_breach", "evidence_clue_ids": sorted(session.discovered_clue_ids)},
                index,
            ),
        )
    ).ok
    index += 1
    completed = case_service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case.case_id,
            session_id=started.session_id,
            action=action(ToolName.EXECUTE_TREATMENT, {"treatment_id": "return_token_and_fulfill_vow"}, index),
        )
    )
    assert completed.ok and completed.episode_result.score == 100
    request = TeachingRequest(player_id=player_id, teaching_session_id=teaching_state.teaching_session_id)
    reviewed = teaching.observe_case_completion(request)
    assert reviewed.ok and reviewed.state.phase.value == "completed"
    report = reviewed.state.assessment
    assert report.final_score == 100 and report.outcome.value == "resolved"
    assert report.ability_changes and report.relationship_changes
    assert report.hints_used == ()
    before = (tmp_path / "teaching_sessions" / f"{teaching_state.teaching_session_id}.json").read_bytes()
    again = teaching.observe_case_completion(request)
    assert again.ok and again.state.revision == reviewed.state.revision
    assert before == (tmp_path / "teaching_sessions" / f"{teaching_state.teaching_session_id}.json").read_bytes()


def test_two_hints_persist_and_third_is_zero_write(tmp_path):
    case_service, teaching, _ = build_teaching(tmp_path)
    player_id = create_player(case_service)
    _, state = start_teaching(case_service, teaching, player_id)
    request = TeachingRequest(player_id=player_id, teaching_session_id=state.teaching_session_id)
    first = teaching.request_hint(request)
    second = teaching.request_hint(request)
    path = tmp_path / "teaching_sessions" / f"{state.teaching_session_id}.json"
    before = path.read_bytes()
    third = teaching.request_hint(request)
    assert first.ok and second.ok
    assert second.state.used_hint_ids == ("hint_1", "hint_2")
    assert not third.ok and third.error_code == "hint_limit_reached"
    assert before == path.read_bytes()


def test_cross_player_access_is_zero_write(tmp_path):
    case_service, teaching, _ = build_teaching(tmp_path)
    owner = create_player(case_service, "甲")
    intruder = create_player(case_service, "乙")
    _, state = start_teaching(case_service, teaching, owner)
    path = tmp_path / "teaching_sessions" / f"{state.teaching_session_id}.json"
    before = path.read_bytes()
    denied = teaching.resume(
        TeachingRequest(player_id=intruder, teaching_session_id=state.teaching_session_id)
    )
    assert not denied.ok and denied.error_code == "teaching_access_denied"
    assert before == path.read_bytes()


def test_reflection_occurs_once_and_does_not_change_case_or_r1(tmp_path):
    case_service, teaching, _ = build_teaching(tmp_path)
    player_id = create_player(case_service)
    started, state = start_teaching(case_service, teaching, player_id)
    investigate_all(case_service, player_id, started.session_id)
    request = TeachingRequest(player_id=player_id, teaching_session_id=state.teaching_session_id)
    case_path = tmp_path / "case_sessions" / f"{started.session_id}.json"
    growth_path = tmp_path / "apprenticeships" / f"{player_id}.json"
    before = (case_path.read_bytes(), growth_path.read_bytes())
    asked = teaching.request_reflection(request)
    answered = teaching.submit_reflection(
        SubmitReflectionInput(
            player_id=player_id,
            teaching_session_id=state.teaching_session_id,
            reflection_text="事实是已发现的线索；对根因的判断仍是推断。",
        )
    )
    repeated = teaching.request_reflection(request)
    assert asked.ok and answered.ok
    assert not repeated.ok and repeated.error_code == "reflection_already_requested"
    assert before == (case_path.read_bytes(), growth_path.read_bytes())
