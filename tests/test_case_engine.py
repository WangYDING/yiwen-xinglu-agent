from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain import (
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
    TreatmentOutcome,
)
from xuanyi_npc.engine import (
    ActionMismatchError,
    CaseEngine,
    ContextMismatchError,
    DiagnosisRequiredError,
    EvidenceNotDiscoveredError,
    InsufficientSkillError,
    MissingCluePrerequisiteError,
    SessionClosedError,
    SkillLockedError,
    TreatmentPrerequisiteError,
    UnknownInvestigationError,
    UnknownTreatmentError,
)


BASE_TIME = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


def make_session(case: CaseDefinition, player: PlayerState) -> CaseSessionState:
    return CaseSessionState(
        session_id="session_engine_test",
        case_id=case.case_id,
        player_id=player.player_id,
    )


def investigation_command(
    case: CaseDefinition,
    investigation_id: str,
    minute: int,
) -> InvestigationCommand:
    investigation = next(
        item
        for item in case.investigations
        if item.investigation_id == investigation_id
    )
    return InvestigationCommand(
        investigation_id=investigation.investigation_id,
        action_type=investigation.action_type,
        target_id=investigation.target_id,
        occurred_at=BASE_TIME + timedelta(minutes=minute),
    )


def execute_investigations(
    engine: CaseEngine,
    case: CaseDefinition,
    player: PlayerState,
    session: CaseSessionState,
    investigation_ids: tuple[str, ...],
) -> CaseSessionState:
    current = session
    for minute, investigation_id in enumerate(investigation_ids, start=1):
        current = engine.execute(
            case,
            player,
            current,
            investigation_command(case, investigation_id, minute),
        ).session
    return current


def test_complete_correct_case_without_llm(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    initial_session = make_session(case_definition, qualified_player_state)
    session = execute_investigations(
        engine,
        case_definition,
        qualified_player_state,
        initial_session,
        (
            "observe_scholar",
            "ask_about_memory",
            "inspect_umbrella",
            "observe_contract_trace",
            "search_book_chest",
            "ask_about_promise",
        ),
    )

    diagnosis_result = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        SubmitDiagnosisCommand(
            diagnosis_id="unfulfilled_rain_vow_contract",
            evidence_clue_ids=session.discovered_clue_ids,
            occurred_at=BASE_TIME + timedelta(minutes=7),
        ),
    )
    treatment_result = engine.execute(
        case_definition,
        qualified_player_state,
        diagnosis_result.session,
        ExecuteTreatmentCommand(
            treatment_id="return_token_and_fulfill_vow",
            occurred_at=BASE_TIME + timedelta(minutes=8),
        ),
    )

    assert initial_session.revision == 0
    assert initial_session.discovered_clue_ids == frozenset()
    assert treatment_result.session.status is CaseSessionStatus.COMPLETED
    assert treatment_result.session.outcome is TreatmentOutcome.RESOLVED
    assert treatment_result.session.score == 100
    assert treatment_result.session.revision == 8
    assert len(treatment_result.session.action_history) == 8
    assert treatment_result.score_breakdown is not None
    assert treatment_result.score_breakdown.diagnosis_correct is True
    assert treatment_result.score_breakdown.clue_points == 40
    assert treatment_result.score_breakdown.diagnosis_points == 30
    assert treatment_result.score_breakdown.treatment_points == 30


def test_same_inputs_produce_identical_result(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = make_session(case_definition, qualified_player_state)
    command = investigation_command(case_definition, "observe_scholar", 1)

    first = engine.execute(case_definition, qualified_player_state, session, command)
    second = engine.execute(case_definition, qualified_player_state, session, command)

    assert first == second
    assert session.revision == 0


def test_locked_skill_rejects_advanced_investigation_without_mutation(
    case_definition: CaseDefinition,
    player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = execute_investigations(
        engine,
        case_definition,
        player_state,
        make_session(case_definition, player_state),
        ("inspect_umbrella",),
    )
    before = session.model_copy(deep=True)

    with pytest.raises(SkillLockedError):
        engine.execute(
            case_definition,
            player_state,
            session,
            investigation_command(case_definition, "observe_contract_trace", 2),
        )

    assert session == before


def test_insufficient_skill_is_distinct_from_locked_skill(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    data = qualified_player_state.model_dump(mode="python")
    data["skills"]["observe_qi"]["proficiency"] = 10
    underqualified_player = PlayerState.model_validate(data)
    engine = CaseEngine()
    session = execute_investigations(
        engine,
        case_definition,
        underqualified_player,
        make_session(case_definition, underqualified_player),
        ("inspect_umbrella",),
    )

    with pytest.raises(InsufficientSkillError):
        engine.execute(
            case_definition,
            underqualified_player,
            session,
            investigation_command(case_definition, "observe_contract_trace", 2),
        )


def test_missing_clue_prerequisite_rejects_investigation(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = make_session(case_definition, qualified_player_state)

    with pytest.raises(MissingCluePrerequisiteError):
        engine.execute(
            case_definition,
            qualified_player_state,
            session,
            investigation_command(case_definition, "observe_contract_trace", 1),
        )


def test_command_cannot_spoof_investigation_target(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = make_session(case_definition, qualified_player_state)

    with pytest.raises(ActionMismatchError):
        engine.execute(
            case_definition,
            qualified_player_state,
            session,
            InvestigationCommand(
                investigation_id="observe_scholar",
                action_type=CaseActionType.OBSERVE_PATIENT,
                target_id="old_paper_umbrella",
                occurred_at=BASE_TIME,
            ),
        )


def test_unknown_investigation_has_explicit_error(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    with pytest.raises(UnknownInvestigationError):
        CaseEngine().execute(
            case_definition,
            qualified_player_state,
            make_session(case_definition, qualified_player_state),
            InvestigationCommand(
                investigation_id="invented_investigation",
                action_type=CaseActionType.OBSERVE_PATIENT,
                target_id="scholar_lu",
                occurred_at=BASE_TIME,
            ),
        )


def test_diagnosis_cannot_cite_undiscovered_evidence(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    session = make_session(case_definition, qualified_player_state)

    with pytest.raises(EvidenceNotDiscoveredError):
        CaseEngine().execute(
            case_definition,
            qualified_player_state,
            session,
            SubmitDiagnosisCommand(
                diagnosis_id="unfulfilled_rain_vow_contract",
                evidence_clue_ids={"broken_promise"},
                occurred_at=BASE_TIME,
            ),
        )

    assert session.submitted_diagnosis_id is None


def test_treatment_requires_diagnosis(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    with pytest.raises(DiagnosisRequiredError):
        CaseEngine().execute(
            case_definition,
            qualified_player_state,
            make_session(case_definition, qualified_player_state),
            ExecuteTreatmentCommand(
                treatment_id="burn_old_umbrella",
                occurred_at=BASE_TIME,
            ),
        )


def test_unknown_treatment_has_explicit_error(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = engine.execute(
        case_definition,
        qualified_player_state,
        make_session(case_definition, qualified_player_state),
        SubmitDiagnosisCommand(
            diagnosis_id="evil_spirit_attack",
            occurred_at=BASE_TIME,
        ),
    ).session

    with pytest.raises(UnknownTreatmentError):
        engine.execute(
            case_definition,
            qualified_player_state,
            session,
            ExecuteTreatmentCommand(
                treatment_id="invented_treatment",
                occurred_at=BASE_TIME + timedelta(minutes=1),
            ),
        )


def test_session_cannot_claim_clues_without_action_history(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    with pytest.raises(ValidationError, match="exactly match"):
        CaseSessionState(
            session_id="session_forged_clue",
            case_id=case_definition.case_id,
            player_id=qualified_player_state.player_id,
            discovered_clue_ids={"broken_promise"},
        )


def test_resolving_treatment_requires_discovered_evidence(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = engine.execute(
        case_definition,
        qualified_player_state,
        make_session(case_definition, qualified_player_state),
        SubmitDiagnosisCommand(
            diagnosis_id="unfulfilled_rain_vow_contract",
            occurred_at=BASE_TIME,
        ),
    ).session

    with pytest.raises(TreatmentPrerequisiteError):
        engine.execute(
            case_definition,
            qualified_player_state,
            session,
            ExecuteTreatmentCommand(
                treatment_id="return_token_and_fulfill_vow",
                occurred_at=BASE_TIME + timedelta(minutes=1),
            ),
        )


@pytest.mark.parametrize(
    ("treatment_id", "expected_outcome"),
    [
        ("seal_old_umbrella", TreatmentOutcome.SUPPRESSED),
        ("burn_old_umbrella", TreatmentOutcome.WORSENED),
    ],
)
def test_error_treatments_have_deterministic_outcomes(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
    treatment_id: str,
    expected_outcome: TreatmentOutcome,
) -> None:
    engine = CaseEngine()
    session = make_session(case_definition, qualified_player_state)
    if treatment_id == "seal_old_umbrella":
        session = execute_investigations(
            engine,
            case_definition,
            qualified_player_state,
            session,
            ("inspect_umbrella",),
        )
    session = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        SubmitDiagnosisCommand(
            diagnosis_id="evil_spirit_attack",
            occurred_at=BASE_TIME + timedelta(minutes=5),
        ),
    ).session

    result = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        ExecuteTreatmentCommand(
            treatment_id=treatment_id,
            occurred_at=BASE_TIME + timedelta(minutes=6),
        ),
    )

    assert result.session.outcome is expected_outcome
    assert result.score_breakdown is not None
    assert result.score_breakdown.diagnosis_correct is False
    if expected_outcome is TreatmentOutcome.WORSENED:
        assert result.score_breakdown.unsafe_treatment_penalty == 20
        assert result.session.score == 0


def test_repeated_investigation_does_not_duplicate_clues(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = make_session(case_definition, qualified_player_state)
    first = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        investigation_command(case_definition, "observe_scholar", 1),
    )
    second = engine.execute(
        case_definition,
        qualified_player_state,
        first.session,
        investigation_command(case_definition, "observe_scholar", 2),
    )

    assert second.session.discovered_clue_ids == first.session.discovered_clue_ids
    assert second.events[0].newly_discovered_clue_ids == frozenset()
    assert len(second.session.action_history) == 2


def test_repeated_actions_do_not_duplicate_score(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = execute_investigations(
        engine,
        case_definition,
        qualified_player_state,
        make_session(case_definition, qualified_player_state),
        (
            "observe_scholar",
            "observe_scholar",
            "ask_about_memory",
            "inspect_umbrella",
            "observe_contract_trace",
            "search_book_chest",
            "ask_about_promise",
        ),
    )
    for minute in (8, 9):
        session = engine.execute(
            case_definition,
            qualified_player_state,
            session,
            SubmitDiagnosisCommand(
                diagnosis_id="unfulfilled_rain_vow_contract",
                evidence_clue_ids=session.discovered_clue_ids,
                occurred_at=BASE_TIME + timedelta(minutes=minute),
            ),
        ).session
    result = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        ExecuteTreatmentCommand(
            treatment_id="return_token_and_fulfill_vow",
            occurred_at=BASE_TIME + timedelta(minutes=10),
        ),
    )

    assert result.score_breakdown is not None
    assert result.score_breakdown.discovered_key_clues == 6
    assert result.score_breakdown.clue_points == 40
    assert result.score_breakdown.diagnosis_points == 30
    assert result.session.score == 100


def test_multiple_valid_diagnoses_share_the_same_scoring_contract(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    data = case_definition.model_dump(mode="json")
    data["valid_diagnosis_ids"].append("rain_vow_breach")
    multi_solution_case = CaseDefinition.model_validate(data)
    engine = CaseEngine()
    session = execute_investigations(
        engine,
        multi_solution_case,
        qualified_player_state,
        make_session(multi_solution_case, qualified_player_state),
        (
            "observe_scholar",
            "ask_about_memory",
            "inspect_umbrella",
            "observe_contract_trace",
            "search_book_chest",
            "ask_about_promise",
        ),
    )
    session = engine.execute(
        multi_solution_case,
        qualified_player_state,
        session,
        SubmitDiagnosisCommand(
            diagnosis_id="rain_vow_breach",
            evidence_clue_ids=session.discovered_clue_ids,
            occurred_at=BASE_TIME + timedelta(minutes=7),
        ),
    ).session
    result = engine.execute(
        multi_solution_case,
        qualified_player_state,
        session,
        ExecuteTreatmentCommand(
            treatment_id="return_token_and_fulfill_vow",
            occurred_at=BASE_TIME + timedelta(minutes=8),
        ),
    )

    assert result.score_breakdown is not None
    assert result.score_breakdown.diagnosis_correct is True
    assert result.score_breakdown.diagnosis_points == 30
    assert result.session.score == 100


def test_completed_session_rejects_more_commands(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = engine.execute(
        case_definition,
        qualified_player_state,
        make_session(case_definition, qualified_player_state),
        SubmitDiagnosisCommand(
            diagnosis_id="evil_spirit_attack",
            occurred_at=BASE_TIME,
        ),
    ).session
    completed = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        ExecuteTreatmentCommand(
            treatment_id="burn_old_umbrella",
            occurred_at=BASE_TIME + timedelta(minutes=1),
        ),
    ).session

    with pytest.raises(SessionClosedError):
        engine.execute(
            case_definition,
            qualified_player_state,
            completed,
            investigation_command(case_definition, "observe_scholar", 2),
        )


def test_mismatched_session_context_is_rejected(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    session = CaseSessionState(
        session_id="session_wrong_case",
        case_id="another_case",
        player_id=qualified_player_state.player_id,
    )

    with pytest.raises(ContextMismatchError):
        CaseEngine().execute(
            case_definition,
            qualified_player_state,
            session,
            investigation_command(case_definition, "observe_scholar", 1),
        )


def test_command_requires_timezone_aware_timestamp(
    case_definition: CaseDefinition,
) -> None:
    investigation = case_definition.investigations[0]

    with pytest.raises(ValidationError, match="timezone"):
        InvestigationCommand(
            investigation_id=investigation.investigation_id,
            action_type=investigation.action_type,
            target_id=investigation.target_id,
            occurred_at=datetime(2026, 8, 3, 8, 0),
        )
