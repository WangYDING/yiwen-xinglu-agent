from xuanyi_npc.application import (
    CreateTeachingSessionInput,
    StartEpisodeInput,
    SubmitActionInput,
    TeachingRequest,
)
from xuanyi_npc.domain import ToolName
from xuanyi_npc.agents import (
    DeterministicFakeMentor,
    RelationshipExpressionTier,
    RelationshipExpressionView,
)
from xuanyi_npc.domain import MentorActionType, MentorInteractionPhase
from tests.r1_helpers import TOOLS, TRACES, action, create_player
from tests.r2_helpers import build_teaching


def complete_taught_case(
    service,
    teaching,
    store,
    player_id,
    case_id,
    *,
    diagnosis_id=None,
    treatment_id=None,
    skip_investigation_id=None,
    cite_evidence=True,
):
    started = service.start_episode(StartEpisodeInput(player_id=player_id, case_id=case_id))
    created = teaching.create(
        CreateTeachingSessionInput(player_id=player_id, case_session_id=started.session_id)
    )
    assert created.ok
    case = service.case_catalog.get(case_id)
    index = 0
    for investigation in case.investigations:
        if investigation.investigation_id == skip_investigation_id:
            continue
        index += 1
        assert service.submit_action(
            SubmitActionInput(
                player_id=player_id,
                case_id=case_id,
                session_id=started.session_id,
                action=action(
                    TOOLS[investigation.action_type],
                    {"investigation_id": investigation.investigation_id},
                    index,
                ),
            )
        ).ok
    session = store.load_case_session(started.session_id)
    diagnosis, treatment = TRACES[case_id]
    index += 1
    assert service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=started.session_id,
            action=action(
                ToolName.SUBMIT_DIAGNOSIS,
                {
                    "diagnosis_id": diagnosis_id or diagnosis,
                    "evidence_clue_ids": (
                        sorted(session.discovered_clue_ids) if cite_evidence else []
                    ),
                },
                index,
            ),
        )
    ).ok
    index += 1
    finished = service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=started.session_id,
            action=action(
                ToolName.EXECUTE_TREATMENT,
                {"treatment_id": treatment_id or treatment},
                index,
            ),
        )
    )
    assert finished.ok
    reviewed = teaching.observe_case_completion(
        TeachingRequest(
            player_id=player_id,
            teaching_session_id=created.state.teaching_session_id,
        )
    )
    assert reviewed.ok, reviewed
    return created, reviewed


def test_three_case_excellent_route_uses_history_and_finishes_foundation(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(service, "优秀学徒")

    _, umbrella = complete_taught_case(
        service, teaching, store, player_id, "old_paper_umbrella"
    )
    plan = store.load_teaching_plan(player_id)
    assert plan.current_recommendation.recommendation_id == "provenance_before_intent_v1"
    assert not plan.completed_remediations

    hearth_start, _ = complete_taught_case(
        service, teaching, store, player_id, "gray_hearth_inn"
    )
    assert "历史记录显示" in hearth_start.mentor_action.message
    plan = store.load_teaching_plan(player_id)
    assert plan.current_recommendation.recommendation_id == "corroborate_before_handoff_v1"

    well_start, _ = complete_taught_case(
        service, teaching, store, player_id, "moon_well_echo"
    )
    assert "历史记录显示" in well_start.mentor_action.message
    plan = store.load_teaching_plan(player_id)
    assert plan.completed_core_lessons == (
        "evidence_before_diagnosis_v1",
        "provenance_before_intent_v1",
        "corroborate_before_handoff_v1",
    )
    assert plan.current_recommendation.recommendation_id == "foundation_complete"
    assert plan.current_recommendation.reason_codes == ("foundation_three_lessons_complete",)


def test_wrong_diagnosis_assigns_remediation_without_growth_and_then_recovers(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(service, "辨证学徒")
    _, reviewed = complete_taught_case(
        service,
        teaching,
        store,
        player_id,
        "old_paper_umbrella",
        diagnosis_id="exam_exhaustion",
    )
    assert "reason_diagnosis" in {
        item.value for item in reviewed.state.assessment.improvement_abilities
    }
    plan = store.load_teaching_plan(player_id)
    assert plan.current_recommendation.recommendation_id == "remediate_diagnostic_reasoning_v1"
    proficiency = store.load_apprenticeship(player_id).abilities
    before = {key: value.proficiency for key, value in proficiency.items()}

    wrong_state, correct = teaching.plan_service.attempt_remediation(
        player_id=player_id,
        remediation_id="remediate_diagnostic_reasoning_v1",
        option_id="diagnostic_reasoning_a",
        request_id="wrong_attempt",
    )
    assert not correct
    assert "remediate_diagnostic_reasoning_v1" not in wrong_state.completed_remediations
    completed, correct = teaching.plan_service.attempt_remediation(
        player_id=player_id,
        remediation_id="remediate_diagnostic_reasoning_v1",
        option_id="diagnostic_reasoning_b",
        request_id="correct_attempt",
    )
    assert correct
    assert completed.current_recommendation.recommendation_id == "provenance_before_intent_v1"
    after = {
        key: value.proficiency
        for key, value in store.load_apprenticeship(player_id).abilities.items()
    }
    assert after == before


def test_unsafe_treatment_has_priority_over_diagnosis(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(service, "守则学徒")
    _, reviewed = complete_taught_case(
        service,
        teaching,
        store,
        player_id,
        "old_paper_umbrella",
        diagnosis_id="exam_exhaustion",
        treatment_id="seal_old_umbrella",
    )
    assert reviewed.state.assessment.outcome.value == "suppressed"
    plan = store.load_teaching_plan(player_id)
    assert plan.current_recommendation.recommendation_id == "remediate_treatment_alignment_v1"
    assert plan.recommendation_reason_codes == ("unresolved_ethics_risk",)
    assert "成功" not in reviewed.state.mentor_review.message


def test_missing_evidence_assigns_evidence_remediation_without_answer_leak(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(service, "验物学徒")
    _, reviewed = complete_taught_case(
        service,
        teaching,
        store,
        player_id,
        "old_paper_umbrella",
        cite_evidence=False,
    )
    assert "inspect_evidence" in {
        item.value for item in reviewed.state.assessment.improvement_abilities
    }
    plan = store.load_teaching_plan(player_id)
    assert plan.current_recommendation.recommendation_id == "remediate_evidence_completeness_v1"
    definition = teaching.curriculum.remediations[plan.current_recommendation.recommendation_id]
    serialized = definition.model_dump_json()
    assert "rain_vow_breach" not in serialized
    assert "return_token_and_fulfill_vow" not in serialized


def test_two_players_receive_different_plans_and_no_memory_cross_talk(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    excellent = create_player(service, "甲")
    learner = create_player(service, "乙")
    complete_taught_case(service, teaching, store, excellent, "old_paper_umbrella")
    complete_taught_case(
        service, teaching, store, learner, "old_paper_umbrella", diagnosis_id="exam_exhaustion"
    )
    assert store.load_teaching_plan(excellent).current_recommendation.recommendation_id == "provenance_before_intent_v1"
    assert store.load_teaching_plan(learner).current_recommendation.recommendation_id == "remediate_diagnostic_reasoning_v1"
    excellent_ids = {
        item.memory_id
        for item in teaching.memory_repository.list_memories(player_id=excellent)
    }
    learner_ids = {
        item.memory_id
        for item in teaching.memory_repository.list_memories(player_id=learner)
    }
    assert excellent_ids and learner_ids and excellent_ids.isdisjoint(learner_ids)


def test_relationship_tier_changes_expression_only(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(service, "关系学徒")
    lesson = teaching.curriculum.lessons["evidence_before_diagnosis_v1"]
    base = teaching._input(
        player=store.load_player(player_id),
        apprenticeship=store.load_apprenticeship(player_id),
        phase=MentorInteractionPhase.LESSON_START,
        allowed=(MentorActionType.SPEAK,),
        lesson=lesson,
        plan=teaching.plan_service.ensure(player_id),
        excluded_episode_id="episode_expression",
    )
    low = base.model_copy(
        update={
            "relationship_expression": RelationshipExpressionView(
                trust_tier=RelationshipExpressionTier.LOW,
                recognition_tier=RelationshipExpressionTier.LOW,
            )
        }
    )
    high = base.model_copy(
        update={
            "relationship_expression": RelationshipExpressionView(
                trust_tier=RelationshipExpressionTier.HIGH,
                recognition_tier=RelationshipExpressionTier.HIGH,
            )
        }
    )
    low_action = DeterministicFakeMentor().decide(low).action
    high_action = DeterministicFakeMentor().decide(high).action
    assert low_action.action_type == high_action.action_type == MentorActionType.SPEAK
    assert low_action.hint_id == high_action.hint_id is None
    assert low_action.referenced_ability_ids == high_action.referenced_ability_ids == ()
    assert low_action.message != high_action.message


def test_manual_case_deviation_is_recorded_without_changing_recommendation(tmp_path):
    service, teaching, store = build_teaching(tmp_path)
    player_id = create_player(service, "自主学徒")
    complete_taught_case(
        service,
        teaching,
        store,
        player_id,
        "old_paper_umbrella",
        diagnosis_id="exam_exhaustion",
    )
    before = store.load_teaching_plan(player_id).current_recommendation
    started = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="gray_hearth_inn")
    )
    created = teaching.create(
        CreateTeachingSessionInput(
            player_id=player_id,
            case_session_id=started.session_id,
        )
    )
    assert created.ok
    after = store.load_teaching_plan(player_id)
    assert after.current_recommendation == before
    assert started.session_id in after.recommendation_deviations
    assert "manual_case_deviation" in created.mentor_action.message
