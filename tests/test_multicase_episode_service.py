from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.application import (
    CaseCatalog,
    CaseCatalogError,
    CreatePlayerInput,
    FinishEpisodeInput,
    ListCasesInput,
    ListPlayersInput,
    MultiCaseEpisodeService,
    MultiCaseServiceResult,
    QuitInput,
    ResumeEpisodeInput,
    StartEpisodeInput,
    SubmitActionInput,
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.storage import JsonStateStore, StorageError


REPO_ROOT = Path(__file__).parents[1]
SOURCE_CASE = (
    REPO_ROOT
    / "src"
    / "xuanyi_npc"
    / "resources"
    / "cases"
    / "old_paper_umbrella.json"
)


class SequencePlayerIds:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)

    def new_player_id(self) -> str:
        return next(self.values)


class SequenceSessionIds:
    def __init__(self, *values: str) -> None:
        self.values = iter(values)

    def new_session_id(self) -> str:
        return next(self.values)


class TickingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self.current += timedelta(minutes=1)
        return self.current


def seed_case_dir(root: Path) -> Path:
    case_dir = root / "cases"
    case_dir.mkdir()
    shutil.copy2(SOURCE_CASE, case_dir / SOURCE_CASE.name)
    return case_dir


def build_service(
    root: Path,
    *,
    player_ids: tuple[str, ...] = ("player_one", "player_two"),
    session_ids: tuple[str, ...] = ("session_one", "session_two"),
    store: JsonStateStore | None = None,
) -> tuple[MultiCaseEpisodeService, JsonStateStore, CaseCatalog]:
    case_dir = seed_case_dir(root)
    state_store = store or JsonStateStore(root / "states")
    catalog = CaseCatalog(case_dir)
    service = MultiCaseEpisodeService(
        state_store=state_store,
        case_catalog=catalog,
        player_id_factory=SequencePlayerIds(*player_ids),
        session_id_factory=SequenceSessionIds(*session_ids),
        clock=TickingClock(),
    )
    return service, state_store, catalog


def action(tool_name: ToolName, **arguments: object) -> AgentAction:
    return AgentAction(
        action_id="service_test_action",
        action_type=AgentActionType.USE_TOOL,
        dialogue="执行测试中的公开行动。",
        tool_call=ToolCallRequest(name=tool_name, arguments=arguments),
        confidence=1.0,
    )


def create_and_start(
    service: MultiCaseEpisodeService,
    *,
    name: str = "学徒甲",
) -> tuple[str, str]:
    created = service.create_player(CreatePlayerInput(display_name=name))
    assert created.ok is True
    assert created.player_id is not None
    started = service.start_episode(
        StartEpisodeInput(
            player_id=created.player_id,
            case_id="old_paper_umbrella",
        )
    )
    assert started.ok is True
    assert started.session_id is not None
    return created.player_id, started.session_id


def submit(
    service: MultiCaseEpisodeService,
    player_id: str,
    session_id: str,
    tool_name: ToolName,
    **arguments: object,
) -> MultiCaseServiceResult:
    return service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
            action=action(tool_name, **arguments),
        )
    )


REFERENCE_INVESTIGATIONS = (
    (ToolName.OBSERVE_PATIENT, "observe_scholar"),
    (ToolName.QUESTION_PATIENT, "ask_about_memory"),
    (ToolName.INSPECT_OBJECT, "inspect_umbrella"),
    (ToolName.OBSERVE_QI, "observe_contract_trace"),
    (ToolName.INSPECT_OBJECT, "search_book_chest"),
    (ToolName.QUESTION_PATIENT, "ask_about_promise"),
)


def complete_reference(
    service: MultiCaseEpisodeService,
    player_id: str,
    session_id: str,
) -> tuple[MultiCaseServiceResult, list[int]]:
    sequences: list[int] = []
    for tool_name, investigation_id in REFERENCE_INVESTIGATIONS:
        result = submit(
            service,
            player_id,
            session_id,
            tool_name,
            investigation_id=investigation_id,
        )
        assert result.ok is True
        sequences.extend(result.event_sequences)
    diagnosis = submit(
        service,
        player_id,
        session_id,
        ToolName.SUBMIT_DIAGNOSIS,
        diagnosis_id="rain_vow_breach",
        evidence_clue_ids=[
            "fading_shadow",
            "forgotten_faces",
            "umbrella_night_water",
            "vow_knot_trace",
            "hidden_wooden_token",
            "broken_promise",
        ],
    )
    assert diagnosis.ok is True
    sequences.extend(diagnosis.event_sequences)
    treatment = submit(
        service,
        player_id,
        session_id,
        ToolName.EXECUTE_TREATMENT,
        treatment_id="return_token_and_fulfill_vow",
    )
    sequences.extend(treatment.event_sequences)
    return treatment, sequences


@pytest.mark.parametrize(
    "raw_name, expected",
    [
        ("  云   客  ", "云 客"),
        ("ＡＢＣ", "ABC"),
    ],
)
def test_display_name_is_normalized(raw_name: str, expected: str) -> None:
    assert CreatePlayerInput(display_name=raw_name).display_name == expected


@pytest.mark.parametrize("raw_name", ["", "   ", "名字\n换行", "x" * 41])
def test_display_name_rejects_empty_control_or_too_long(raw_name: str) -> None:
    with pytest.raises(ValidationError):
        CreatePlayerInput(display_name=raw_name)


def test_service_input_and_output_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CreatePlayerInput.model_validate({"display_name": "学徒", "extra": True})
    with pytest.raises(ValidationError):
        MultiCaseServiceResult.model_validate(
            {"ok": True, "message": "ok", "hidden_truth": "sentinel"}
        )


def test_catalog_is_stable_public_and_contains_no_case_truth(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, _ = create_and_start(service)

    listed = service.list_cases(ListCasesInput(player_id=player_id))

    assert listed.ok is True
    assert [entry.case_id for entry in listed.cases] == ["old_paper_umbrella"]
    payload = listed.model_dump_json()
    for forbidden in (
        "root_cause",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "correct_treatment",
        "scoring",
        "hidden_information",
    ):
        assert forbidden not in payload


def test_catalog_rejects_duplicate_case_id_and_corrupt_case(tmp_path: Path) -> None:
    case_dir = seed_case_dir(tmp_path)
    shutil.copy2(SOURCE_CASE, case_dir / "duplicate.json")
    with pytest.raises(CaseCatalogError, match="duplicate"):
        CaseCatalog(case_dir)

    (case_dir / "duplicate.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(CaseCatalogError, match="validation"):
        CaseCatalog(case_dir)


def test_duplicate_display_names_are_distinguished_by_player_id(tmp_path: Path) -> None:
    service, store, _ = build_service(tmp_path)

    first = service.create_player(CreatePlayerInput(display_name="同名学徒"))
    second = service.create_player(CreatePlayerInput(display_name="同名学徒"))
    listed = service.list_players(ListPlayersInput())

    assert first.player_id == "player_one"
    assert second.player_id == "player_two"
    assert [player.display_name for player in listed.players] == ["同名学徒", "同名学徒"]
    assert [player.player_id for player in listed.players] == ["player_one", "player_two"]
    assert store.load_player("player_one").revision == 0


def test_start_is_persisted_and_duplicate_active_start_is_zero_write(tmp_path: Path) -> None:
    service, store, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    session_path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = session_path.read_bytes()

    duplicate = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="old_paper_umbrella")
    )

    assert duplicate.ok is False
    assert duplicate.error_code == "active_episode_exists"
    assert duplicate.event_sequences == ()
    assert duplicate.session_revision == 0
    assert session_path.read_bytes() == before
    assert store.load_case_session(session_id).revision == 0


def test_resume_rejects_cross_player_and_case_mismatch(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    first_id, session_id = create_and_start(service, name="甲")
    second = service.create_player(CreatePlayerInput(display_name="乙"))
    assert second.player_id is not None

    cross_player = service.resume_episode(
        ResumeEpisodeInput(
            player_id=second.player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
        )
    )
    wrong_case = service.resume_episode(
        ResumeEpisodeInput(
            player_id=first_id,
            case_id="missing_case",
            session_id=session_id,
        )
    )

    assert cross_player.error_code == "session_player_mismatch"
    assert wrong_case.error_code == "session_case_mismatch"
    assert cross_player.event_sequences == wrong_case.event_sequences == ()


def test_missing_player_case_and_session_have_stable_safe_errors(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, _ = create_and_start(service)

    missing_player = service.list_cases(ListCasesInput(player_id="player_missing"))
    missing_case = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="case_missing")
    )
    missing_session = service.resume_episode(
        ResumeEpisodeInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id="session_missing",
        )
    )

    assert missing_player.error_code == "player_not_found"
    assert missing_case.error_code == "case_not_found"
    assert missing_session.error_code == "session_not_found"
    assert all(
        "Traceback" not in result.message
        for result in (missing_player, missing_case, missing_session)
    )


def test_premature_diagnosis_rejection_preserves_file_and_refreshes_options(
    tmp_path: Path,
) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    session_path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = session_path.read_bytes()

    rejected = submit(
        service,
        player_id,
        session_id,
        ToolName.SUBMIT_DIAGNOSIS,
        diagnosis_id="rain_vow_breach",
        evidence_clue_ids=[],
    )

    assert rejected.ok is False
    assert rejected.error_code == "diagnosis_not_ready"
    assert rejected.event_sequences == ()
    assert rejected.session_revision == 0
    assert rejected.action_options is not None
    assert rejected.action_options.investigations
    assert rejected.action_options.diagnoses == ()
    assert session_path.read_bytes() == before


@pytest.mark.parametrize(
    "tool_name, arguments, expected_code",
    [
        (
            ToolName.OBSERVE_PATIENT,
            {"investigation_id": "unknown_investigation"},
            "unknown_investigation",
        ),
        (
            ToolName.SUBMIT_DIAGNOSIS,
            {"diagnosis_id": "unknown_diagnosis", "evidence_clue_ids": []},
            "unknown_diagnosis",
        ),
        (
            ToolName.EXECUTE_TREATMENT,
            {"treatment_id": "unknown_treatment"},
            "diagnosis_required",
        ),
    ],
)
def test_unknown_or_unavailable_actions_are_zero_write(
    tmp_path: Path,
    tool_name: ToolName,
    arguments: dict[str, object],
    expected_code: str,
) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    session_path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = session_path.read_bytes()

    rejected = submit(service, player_id, session_id, tool_name, **arguments)

    assert rejected.error_code == expected_code
    assert rejected.event_sequences == ()
    assert session_path.read_bytes() == before


def test_unknown_action_fields_are_rejected_without_writing(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = path.read_bytes()

    rejected = submit(
        service,
        player_id,
        session_id,
        ToolName.OBSERVE_PATIENT,
        investigation_id="observe_scholar",
        unexpected="not_allowed",
    )

    assert rejected.error_code == "invalid_tool_arguments"
    assert rejected.event_sequences == ()
    assert path.read_bytes() == before


def test_unknown_treatment_after_diagnosis_is_rejected_without_writing(
    tmp_path: Path,
) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    for tool_name, investigation_id in REFERENCE_INVESTIGATIONS:
        assert submit(
            service,
            player_id,
            session_id,
            tool_name,
            investigation_id=investigation_id,
        ).ok
    assert submit(
        service,
        player_id,
        session_id,
        ToolName.SUBMIT_DIAGNOSIS,
        diagnosis_id="rain_vow_breach",
        evidence_clue_ids=[],
    ).ok
    path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = path.read_bytes()

    rejected = submit(
        service,
        player_id,
        session_id,
        ToolName.EXECUTE_TREATMENT,
        treatment_id="unknown_treatment",
    )

    assert rejected.error_code == "unknown_treatment"
    assert rejected.event_sequences == ()
    assert path.read_bytes() == before


def test_full_reference_episode_finishes_resolved_100_and_finish_is_idempotent(
    tmp_path: Path,
) -> None:
    service, store, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)

    treatment, sequences = complete_reference(service, player_id, session_id)

    assert treatment.ok is True
    assert sequences == list(range(1, 9))
    assert treatment.session_revision == 8
    assert treatment.episode_result is not None
    assert treatment.episode_result.status.value == "completed"
    assert treatment.episode_result.outcome is not None
    assert treatment.episode_result.outcome.value == "resolved"
    assert treatment.episode_result.score == 100
    assert store.load_player(player_id).handled_case_ids == frozenset()

    resumed = service.resume_episode(
        ResumeEpisodeInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
        )
    )
    listed = service.list_cases(ListCasesInput(player_id=player_id))
    assert resumed.episode_result is not None
    assert resumed.episode_result.score == 100
    assert listed.cases[0].play_status.value == "completed"
    assert listed.cases[0].completed_session_id == session_id

    request = FinishEpisodeInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=session_id,
    )
    path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = path.read_bytes()
    first = service.finish_episode(request)
    second = service.finish_episode(request)
    assert first == second
    assert path.read_bytes() == before


def test_completed_session_rejects_further_actions_without_writing(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    complete_reference(service, player_id, session_id)
    path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = path.read_bytes()

    rejected = submit(
        service,
        player_id,
        session_id,
        ToolName.OBSERVE_PATIENT,
        investigation_id="observe_scholar",
    )

    assert rejected.error_code == "session_closed"
    assert rejected.event_sequences == ()
    assert path.read_bytes() == before


def test_quit_and_unfinished_finish_are_zero_write(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = path.read_bytes()

    unfinished = service.finish_episode(
        FinishEpisodeInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
        )
    )
    quit_result = service.quit(
        QuitInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
        )
    )

    assert unfinished.error_code == "episode_not_completed"
    assert quit_result.ok is True
    assert unfinished.event_sequences == quit_result.event_sequences == ()
    assert path.read_bytes() == before


class FailingSessionStore(JsonStateStore):
    def save_case_session(self, state: object) -> Path:  # type: ignore[override]
        raise StorageError("simulated save failure")


def test_start_save_failure_does_not_report_started(tmp_path: Path) -> None:
    case_dir = seed_case_dir(tmp_path)
    store = FailingSessionStore(tmp_path / "states")
    service = MultiCaseEpisodeService(
        state_store=store,
        case_catalog=CaseCatalog(case_dir),
        player_id_factory=SequencePlayerIds("player_one"),
        session_id_factory=SequenceSessionIds("session_one"),
        clock=TickingClock(),
    )
    created = service.create_player(CreatePlayerInput(display_name="学徒"))
    assert created.player_id is not None

    result = service.start_episode(
        StartEpisodeInput(
            player_id=created.player_id,
            case_id="old_paper_umbrella",
        )
    )

    assert result.ok is False
    assert result.error_code == "state_unavailable"
    assert store.list_case_sessions() == ()


class ToggleFailSessionStore(JsonStateStore):
    fail_session_save = False

    def save_case_session(self, state: object) -> Path:  # type: ignore[override]
        if self.fail_session_save:
            raise StorageError("simulated save failure")
        return super().save_case_session(state)  # type: ignore[arg-type]


def test_action_save_failure_keeps_previous_file_and_returns_no_event(tmp_path: Path) -> None:
    case_dir = seed_case_dir(tmp_path)
    store = ToggleFailSessionStore(tmp_path / "states")
    service = MultiCaseEpisodeService(
        state_store=store,
        case_catalog=CaseCatalog(case_dir),
        player_id_factory=SequencePlayerIds("player_one"),
        session_id_factory=SequenceSessionIds("session_one"),
        clock=TickingClock(),
    )
    player_id, session_id = create_and_start(service)
    path = tmp_path / "states" / "case_sessions" / f"{session_id}.json"
    before = path.read_bytes()
    store.fail_session_save = True

    result = submit(
        service,
        player_id,
        session_id,
        ToolName.OBSERVE_PATIENT,
        investigation_id="observe_scholar",
    )

    assert result.error_code == "state_unavailable"
    assert result.event_sequences == ()
    assert result.session_revision == 0
    assert path.read_bytes() == before


def test_corrupt_player_or_session_returns_safe_error(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    states = tmp_path / "states"
    players = states / "players"
    players.mkdir(parents=True)
    (players / "player_broken.json").write_text("{broken", encoding="utf-8")

    players_result = service.list_players(ListPlayersInput())
    assert players_result.error_code == "state_corrupt"
    assert "Traceback" not in players_result.message

    (players / "player_broken.json").unlink()
    created = service.create_player(CreatePlayerInput(display_name="学徒"))
    assert created.player_id is not None
    sessions = states / "case_sessions"
    sessions.mkdir(parents=True)
    (sessions / "session_broken.json").write_text("{broken", encoding="utf-8")
    cases_result = service.list_cases(ListCasesInput(player_id=created.player_id))
    assert cases_result.error_code == "state_corrupt"


def test_invalid_id_factory_cannot_escape_state_root(tmp_path: Path) -> None:
    service, store, _ = build_service(
        tmp_path,
        player_ids=("../outside",),
    )

    result = service.create_player(CreatePlayerInput(display_name="学徒"))

    assert result.error_code == "id_conflict"
    assert store.list_players() == ()
    assert not (tmp_path / "outside.json").exists()


def test_catalog_and_result_public_payload_do_not_leak_hidden_sentinels(
    tmp_path: Path,
) -> None:
    service, _, _ = build_service(tmp_path)
    player_id, session_id = create_and_start(service)
    resumed = service.resume_episode(
        ResumeEpisodeInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
        )
    )
    payload = resumed.model_dump_json()

    case = CaseDefinition.model_validate_json(SOURCE_CASE.read_text(encoding="utf-8"))
    forbidden_values = (
        case.root_cause,
        *case.causal_chain,
        *case.patient.hidden_information,
    )
    assert all(value not in payload for value in forbidden_values)
    assert "valid_diagnosis_ids" not in payload
    assert "diagnosis_correct" not in payload
