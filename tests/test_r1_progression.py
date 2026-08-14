from xuanyi_npc.domain import AbilityId, EvidencePolarity

from tests.r1_helpers import build_service, complete_case, create_player


def test_old_paper_umbrella_resolved_100_grows_abilities_and_relationship(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    before = store.load_apprenticeship(player_id)

    session_id, result = complete_case(service, player_id, "old_paper_umbrella")

    assert result.ok
    assert result.episode_result is not None
    assert result.episode_result.outcome.value == "resolved"
    assert result.episode_result.score == 100
    assert result.apprenticeship_status.value == "ready"
    after = store.load_apprenticeship(player_id)
    assert after.relationship.affinity == before.relationship.affinity == 10
    assert after.relationship.trust == 11
    assert after.relationship.recognition == 12
    assert any(item.proficiency > 20 for item in after.abilities.values())
    assert after.completed_source_sessions == (session_id,)
    assert all(item.source_session_id == session_id for item in after.evidence_history)
    assert all(item.source_revision == 8 for item in after.evidence_history)
    assert result.ability_changes
    assert {item.dimension.value for item in result.relationship_changes} == {
        "trust",
        "recognition",
    }


def test_wrong_diagnosis_records_improvement_without_diagnosis_reward(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    _, result = complete_case(
        service,
        player_id,
        "old_paper_umbrella",
        diagnosis_id="evil_spirit_attack",
    )

    state = store.load_apprenticeship(player_id)
    diagnosis = tuple(
        item for item in state.evidence_history
        if item.public_reason_code == "diagnosis_needs_improvement"
    )
    assert len(diagnosis) == 1
    assert diagnosis[0].polarity is EvidencePolarity.NEEDS_IMPROVEMENT
    # 观炁已是独立能力；错误正式辨证不得借观炁行动获得辨证成长。
    assert not any(item.ability_id is AbilityId.REASON_DIAGNOSIS for item in result.ability_changes)
    assert next(item for item in result.ability_changes if item.ability_id is AbilityId.OBSERVE_QI).delta == 1
    assert state.relationship.affinity == 10
    assert state.relationship.trust == 10
    assert state.relationship.recognition == 11
    serialized = state.model_dump_json()
    assert "rain_vow_breach" not in serialized
    assert "root_cause" not in serialized


def test_suppressed_and_worsened_create_no_treatment_growth(tmp_path) -> None:
    service, store = build_service(tmp_path)
    suppressed_player = create_player(service, "压制轨迹")
    _, suppressed = complete_case(
        service,
        suppressed_player,
        "old_paper_umbrella",
        treatment_id="seal_old_umbrella",
    )
    assert suppressed.episode_result.outcome.value == "suppressed"
    assert not {
        AbilityId.APPLY_TREATMENT,
        AbilityId.ETHICAL_PRACTICE,
    }.intersection(item.ability_id for item in suppressed.ability_changes)
    suppressed_state = store.load_apprenticeship(suppressed_player)
    assert suppressed_state.relationship.model_dump() == {
        "affinity": 10,
        "trust": 10,
        "recognition": 10,
    }

    worsened_player = create_player(service, "恶化轨迹")
    _, worsened = complete_case(
        service,
        worsened_player,
        "old_paper_umbrella",
        treatment_id="burn_old_umbrella",
    )
    worsened_state = store.load_apprenticeship(worsened_player)
    assert worsened.episode_result.outcome.value == "worsened"
    assert worsened_state.relationship.affinity == 10
    assert worsened_state.relationship.trust == 9
    assert worsened_state.relationship.recognition == 9
    assert all(item.proficiency >= 0 for item in worsened_state.abilities.values())
    assert {
        item.ability_id for item in worsened_state.evidence_history
        if item.polarity is EvidencePolarity.NEEDS_IMPROVEMENT
    }.issuperset({AbilityId.APPLY_TREATMENT, AbilityId.ETHICAL_PRACTICE})


def test_all_three_cases_use_the_same_progression_policy(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)

    for case_id in (
        "old_paper_umbrella",
        "gray_hearth_inn",
        "moon_well_echo",
    ):
        _, result = complete_case(service, player_id, case_id)
        assert result.ok and result.apprenticeship_status.value == "ready"

    state = store.load_apprenticeship(player_id)
    assert len(state.completed_source_sessions) == 3
    assert state.relationship.model_dump() == {
        "affinity": 10,
        "trust": 13,
        "recognition": 16,
    }
    assert set(item.source_case_id for item in state.evidence_history) == {
        "old_paper_umbrella",
        "gray_hearth_inn",
        "moon_well_echo",
    }
