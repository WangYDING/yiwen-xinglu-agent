from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from xuanyi_npc.application import (
    AgentContextFilter,
    CaseCatalog,
    CreatePlayerInput,
    FixedV0DiagnosisReadinessPolicy,
    ListCasesInput,
    MultiCaseEpisodeService,
    StartEpisodeInput,
    SubmitActionInput,
)
from xuanyi_npc.application.v0_tools import V0ToolExecutor
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    CaseDefinition,
    CaseEvent,
    CaseSessionState,
    ExecuteTreatmentCommand,
    PlayerState,
    RelationshipState,
    SkillState,
    SubmitDiagnosisCommand,
    ToolCallRequest,
    ToolName,
    TreatmentOutcome,
)
from xuanyi_npc.engine import (
    CaseEngine,
    CaseEventReplayer,
    TreatmentPrerequisiteError,
)
from xuanyi_npc.storage import JsonStateStore


REPO_ROOT = Path(__file__).parents[1]
CASE_DIR = REPO_ROOT / "src" / "xuanyi_npc" / "resources" / "cases"
NEW_CASE_IDS = ("gray_hearth_inn", "moon_well_echo")
ALL_CASE_IDS = (*NEW_CASE_IDS, "old_paper_umbrella")
PROCESS_TIMEOUT_SECONDS = 30


CASE_SPECS = {
    "gray_hearth_inn": {
        "orders": (
            (
                "observe_cook",
                "question_innkeeper",
                "inspect_fuel_and_hearth",
                "inspect_hearth_contract",
                "observe_flue_qi",
                "investigate_smoke_passage",
            ),
            (
                "inspect_fuel_and_hearth",
                "observe_flue_qi",
                "inspect_hearth_contract",
                "investigate_smoke_passage",
                "question_innkeeper",
                "observe_cook",
            ),
        ),
        "correct_diagnosis": "displaced_hearth_contract",
        "wrong_diagnosis": "ash_wraith_intrusion",
        "resolved_treatment": "restore_token_and_clear_flue",
        "suppressed_treatment": "seal_hearth_mouth",
        "worsened_treatment": "expel_ash_keeper",
    },
    "moon_well_echo": {
        "orders": (
            (
                "observe_courier",
                "question_route",
                "inspect_wooden_slip",
                "inspect_binding_cord",
                "observe_well_echo_qi",
                "question_lantern_witness",
            ),
            (
                "inspect_wooden_slip",
                "observe_well_echo_qi",
                "inspect_binding_cord",
                "question_route",
                "question_lantern_witness",
                "observe_courier",
            ),
        ),
        "correct_diagnosis": "misbound_message_handoff",
        "wrong_diagnosis": "malicious_echo_entity",
        "resolved_treatment": "verify_recipient_and_deliver",
        "suppressed_treatment": "seal_moon_well",
        "worsened_treatment": "destroy_wooden_slip",
    },
}


TOOL_BY_ACTION = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


class FixedPlayerIds:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def new_player_id(self) -> str:
        return next(self._values)


class FixedSessionIds:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def new_session_id(self) -> str:
        return next(self._values)


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self._now += timedelta(minutes=1)
        return self._now


def load_case(case_id: str) -> CaseDefinition:
    path = CASE_DIR / f"{case_id}.json"
    return CaseDefinition.model_validate_json(path.read_text(encoding="utf-8"))


def qualified_player(player_id: str = "player_p2") -> PlayerState:
    return PlayerState(
        player_id=player_id,
        display_name="巡案学徒",
        skills={
            "observe_form": SkillState(
                skill_id="observe_form", proficiency=30, unlocked=True
            ),
            "ask_cause": SkillState(
                skill_id="ask_cause", proficiency=30, unlocked=True
            ),
            "inspect_object": SkillState(
                skill_id="inspect_object",
                proficiency=30,
                unlocked=True,
                prerequisite_ids={"observe_form"},
            ),
            "observe_qi": SkillState(
                skill_id="observe_qi",
                proficiency=25,
                unlocked=True,
                prerequisite_ids={"observe_form", "inspect_object"},
            ),
        },
        relationship=RelationshipState(),
    )


def tool_action(tool: ToolName, **arguments: object) -> AgentAction:
    return AgentAction(
        action_id="m5_p2_action",
        action_type=AgentActionType.USE_TOOL,
        dialogue="执行冻结的病例轨迹。",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=1.0,
    )


def execute_trace(
    case: CaseDefinition,
    order: tuple[str, ...],
    *,
    diagnosis_id: str,
    treatment_id: str,
) -> tuple[CaseSessionState, tuple[CaseEvent, ...]]:
    player = qualified_player()
    initial = CaseSessionState(
        session_id=f"session_{case.case_id}",
        case_id=case.case_id,
        player_id=player.player_id,
    )
    session = initial
    events: list[CaseEvent] = []
    executor = V0ToolExecutor(
        diagnosis_readiness_policy=FixedV0DiagnosisReadinessPolicy()
    )
    clock = FixedClock()
    investigations = {
        investigation.investigation_id: investigation
        for investigation in case.investigations
    }
    for investigation_id in order:
        investigation = investigations[investigation_id]
        result = executor.execute(
            tool_action(
                TOOL_BY_ACTION[investigation.action_type],
                investigation_id=investigation_id,
            ),
            case,
            player,
            session,
            clock.now(),
        )
        session = result.session
        events.extend(result.events)
    diagnosis = executor.execute(
        tool_action(
            ToolName.SUBMIT_DIAGNOSIS,
            diagnosis_id=diagnosis_id,
            evidence_clue_ids=sorted(session.discovered_clue_ids),
        ),
        case,
        player,
        session,
        clock.now(),
    )
    session = diagnosis.session
    events.extend(diagnosis.events)
    treatment = executor.execute(
        tool_action(ToolName.EXECUTE_TREATMENT, treatment_id=treatment_id),
        case,
        player,
        session,
        clock.now(),
    )
    events.extend(treatment.events)
    return treatment.session, tuple(events)


def build_service(tmp_path: Path) -> tuple[MultiCaseEpisodeService, JsonStateStore]:
    store = JsonStateStore(tmp_path / "state")
    service = MultiCaseEpisodeService(
        state_store=store,
        case_catalog=CaseCatalog(CASE_DIR),
        player_id_factory=FixedPlayerIds("player_multi"),
        session_id_factory=FixedSessionIds(
            "session_gray", "session_moon", "session_old"
        ),
        clock=FixedClock(),
    )
    return service, store


def submit_service_action(
    service: MultiCaseEpisodeService,
    *,
    player_id: str,
    case_id: str,
    session_id: str,
    tool: ToolName,
    **arguments: object,
):
    return service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            action=tool_action(tool, **arguments),
        )
    )


def complete_service_case(
    service: MultiCaseEpisodeService,
    *,
    player_id: str,
    case_id: str,
    session_id: str,
) -> None:
    case = load_case(case_id)
    spec = CASE_SPECS[case_id]
    investigations = {
        investigation.investigation_id: investigation
        for investigation in case.investigations
    }
    discovered: set[str] = set()
    for investigation_id in spec["orders"][0]:
        investigation = investigations[investigation_id]
        result = submit_service_action(
            service,
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            tool=TOOL_BY_ACTION[investigation.action_type],
            investigation_id=investigation_id,
        )
        assert result.ok
        discovered.update(investigation.reveals_clue_ids)
    diagnosed = submit_service_action(
        service,
        player_id=player_id,
        case_id=case_id,
        session_id=session_id,
        tool=ToolName.SUBMIT_DIAGNOSIS,
        diagnosis_id=spec["correct_diagnosis"],
        evidence_clue_ids=sorted(discovered),
    )
    assert diagnosed.ok
    treated = submit_service_action(
        service,
        player_id=player_id,
        case_id=case_id,
        session_id=session_id,
        tool=ToolName.EXECUTE_TREATMENT,
        treatment_id=spec["resolved_treatment"],
    )
    assert treated.ok


def safe_child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    environment["PIP_NO_INDEX"] = "1"
    environment.pop("DEEPSEEK_API_KEY", None)
    environment.pop("HF_TOKEN", None)
    return environment


def run_cli(state_dir: Path, script: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "xuanyi_npc.cli.play",
            "--case-dir",
            str(CASE_DIR),
            "--state-dir",
            str(state_dir),
        ],
        cwd=REPO_ROOT,
        env=safe_child_environment(),
        input=script.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def test_all_three_case_files_pass_strict_schema_and_have_unique_ids() -> None:
    cases = tuple(load_case(case_id) for case_id in ALL_CASE_IDS)
    assert {case.case_id for case in cases} == set(ALL_CASE_IDS)
    assert len({case.patient.patient_id for case in cases}) == 3
    all_investigation_ids = [
        item.investigation_id for case in cases for item in case.investigations
    ]
    all_clue_ids = [clue_id for case in cases for clue_id in case.clues]
    all_diagnosis_ids = [
        diagnosis_id for case in cases for diagnosis_id in case.diagnosis_candidates
    ]
    all_treatment_ids = [
        treatment_id for case in cases for treatment_id in case.treatments
    ]
    assert len(all_investigation_ids) == len(set(all_investigation_ids))
    assert len(all_clue_ids) == len(set(all_clue_ids))
    assert len(all_diagnosis_ids) == len(set(all_diagnosis_ids))
    assert len(all_treatment_ids) == len(set(all_treatment_ids))
    for case in cases:
        assert len(case.investigations) == len(
            {item.investigation_id for item in case.investigations}
        )
        assert set(case.clues) == {clue.clue_id for clue in case.clues.values()}
        assert set(case.diagnosis_candidates) == {
            diagnosis.diagnosis_id
            for diagnosis in case.diagnosis_candidates.values()
        }
        assert set(case.treatments) == {
            treatment.treatment_id for treatment in case.treatments.values()
        }


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_new_case_content_scale_outcomes_and_balanced_public_options(
    case_id: str,
) -> None:
    case = load_case(case_id)
    key_clues = {key for key, clue in case.clues.items() if clue.is_key}
    misleading = {key for key, clue in case.clues.items() if clue.is_misleading}
    outcomes = [treatment.outcome for treatment in case.treatments.values()]

    assert len(case.investigations) == 6
    assert len(case.clues) == 8
    assert len(key_clues) == 6
    assert len(misleading) == 2
    assert len(case.diagnosis_candidates) == 3
    assert len(case.treatments) == 3
    assert len(case.hints) == 3
    assert outcomes.count(TreatmentOutcome.RESOLVED) == 1
    assert outcomes.count(TreatmentOutcome.SUPPRESSED) == 1
    assert outcomes.count(TreatmentOutcome.WORSENED) == 1
    assert all("正确" not in item.public_description for item in case.diagnosis_candidates.values())
    assert all("正确" not in item.public_description for item in case.treatments.values())


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_investigation_graph_is_acyclic_reachable_and_has_multiple_choices(
    case_id: str,
) -> None:
    case = load_case(case_id)
    investigations = {
        item.investigation_id: item for item in case.investigations
    }
    clue_producers: dict[str, set[str]] = {clue_id: set() for clue_id in case.clues}
    for item in case.investigations:
        for clue_id in item.reveals_clue_ids:
            clue_producers[clue_id].add(item.investigation_id)
    graph = {
        item.investigation_id: {
            producer
            for clue_id in item.required_clue_ids
            for producer in clue_producers[clue_id]
        }
        for item in case.investigations
    }

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting, "investigation dependency graph contains a cycle"
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for investigation_id in investigations:
        visit(investigation_id)

    discovered: set[str] = set()
    pending = set(investigations)
    assert sum(not item.required_clue_ids for item in case.investigations) >= 3
    while pending:
        available = {
            investigation_id
            for investigation_id in pending
            if investigations[investigation_id].required_clue_ids.issubset(discovered)
        }
        assert available, "investigation graph contains a soft lock"
        for investigation_id in available:
            discovered.update(investigations[investigation_id].reveals_clue_ids)
        pending.difference_update(available)
    assert {
        clue_id for clue_id, clue in case.clues.items() if clue.is_key
    }.issubset(discovered)


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_new_player_skills_cover_every_required_investigation(case_id: str) -> None:
    case = load_case(case_id)
    player = qualified_player()
    for investigation in case.investigations:
        if investigation.required_skill_id is None:
            continue
        skill = player.skills[investigation.required_skill_id]
        assert skill.unlocked
        assert skill.proficiency >= investigation.minimum_skill_level


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
@pytest.mark.parametrize("order_index", [0, 1])
def test_two_distinct_legal_orders_resolve_with_eight_events_and_replay(
    case_id: str,
    order_index: int,
) -> None:
    case = load_case(case_id)
    spec = CASE_SPECS[case_id]
    order = spec["orders"][order_index]
    assert spec["orders"][0] != spec["orders"][1]

    final, events = execute_trace(
        case,
        order,
        diagnosis_id=spec["correct_diagnosis"],
        treatment_id=spec["resolved_treatment"],
    )

    assert final.status.value == "completed"
    assert final.outcome is TreatmentOutcome.RESOLVED
    assert final.score == 100
    assert final.revision == 8
    assert [event.sequence for event in events] == list(range(1, 9))
    initial = CaseSessionState(
        session_id=final.session_id,
        case_id=case.case_id,
        player_id=final.player_id,
    )
    assert CaseEventReplayer().replay(initial, events) == final


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
@pytest.mark.parametrize(
    "treatment_key, expected_outcome, expected_score",
    [
        ("suppressed_treatment", TreatmentOutcome.SUPPRESSED, 70),
        ("worsened_treatment", TreatmentOutcome.WORSENED, 50),
    ],
)
def test_correct_diagnosis_with_non_resolving_treatment_keeps_failure_truth(
    case_id: str,
    treatment_key: str,
    expected_outcome: TreatmentOutcome,
    expected_score: int,
) -> None:
    case = load_case(case_id)
    spec = CASE_SPECS[case_id]
    final, events = execute_trace(
        case,
        spec["orders"][0],
        diagnosis_id=spec["correct_diagnosis"],
        treatment_id=spec[treatment_key],
    )
    assert final.outcome is expected_outcome
    assert final.score == expected_score
    assert len(events) == 8


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_legal_wrong_diagnosis_is_accepted_but_scores_zero_diagnosis_points(
    case_id: str,
) -> None:
    case = load_case(case_id)
    spec = CASE_SPECS[case_id]
    final, events = execute_trace(
        case,
        spec["orders"][0],
        diagnosis_id=spec["wrong_diagnosis"],
        treatment_id=spec["resolved_treatment"],
    )
    treatment_event = events[-1]
    assert final.outcome is TreatmentOutcome.RESOLVED
    assert final.score == 70
    assert treatment_event.event_type == "treatment_executed"
    assert treatment_event.diagnosis_correct is False  # type: ignore[union-attr]


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_treatment_with_missing_public_prerequisites_is_rejected_without_mutation(
    case_id: str,
) -> None:
    case = load_case(case_id)
    spec = CASE_SPECS[case_id]
    player = qualified_player()
    initial = CaseSessionState(
        session_id=f"session_early_{case_id}",
        case_id=case_id,
        player_id=player.player_id,
    )
    diagnosed = CaseEngine().execute(
        case,
        player,
        initial,
        SubmitDiagnosisCommand(
            diagnosis_id=spec["correct_diagnosis"],
            evidence_clue_ids=frozenset(),
            occurred_at=FixedClock().now(),
        ),
    ).session
    before = diagnosed.model_dump_json()
    with pytest.raises(TreatmentPrerequisiteError):
        CaseEngine().execute(
            case,
            player,
            diagnosed,
            ExecuteTreatmentCommand(
                treatment_id=spec["resolved_treatment"],
                occurred_at=FixedClock().now(),
            ),
        )
    assert diagnosed.model_dump_json() == before
    assert diagnosed.revision == 1


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_unknown_and_repeated_actions_leave_session_file_byte_identical(
    tmp_path: Path,
    case_id: str,
) -> None:
    service, store = build_service(tmp_path)
    created = service.create_player(CreatePlayerInput(display_name="拒绝测试者"))
    assert created.ok and created.player_id
    started = service.start_episode(
        StartEpisodeInput(player_id=created.player_id, case_id=case_id)
    )
    assert started.ok and started.session_id
    path = tmp_path / "state" / "case_sessions" / f"{started.session_id}.json"
    before_unknown = path.read_bytes()

    unknown_investigation = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=ToolName.INSPECT_OBJECT,
        investigation_id="unknown_investigation",
    )
    unknown_diagnosis = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=ToolName.SUBMIT_DIAGNOSIS,
        diagnosis_id="unknown_diagnosis",
        evidence_clue_ids=[],
    )
    treatment_before_diagnosis = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=ToolName.EXECUTE_TREATMENT,
        treatment_id="unknown_treatment",
    )
    assert not unknown_investigation.ok
    assert not unknown_diagnosis.ok
    assert not treatment_before_diagnosis.ok
    assert path.read_bytes() == before_unknown

    first_investigation = CASE_SPECS[case_id]["orders"][0][0]
    definition = next(
        item
        for item in load_case(case_id).investigations
        if item.investigation_id == first_investigation
    )
    accepted = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=TOOL_BY_ACTION[definition.action_type],
        investigation_id=first_investigation,
    )
    assert accepted.ok
    before_repeat = path.read_bytes()
    repeated = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=TOOL_BY_ACTION[definition.action_type],
        investigation_id=first_investigation,
    )
    assert not repeated.ok
    assert repeated.error_code == "investigation_already_completed"
    assert repeated.event_sequences == ()
    assert path.read_bytes() == before_repeat

    case = load_case(case_id)
    investigations = {
        item.investigation_id: item for item in case.investigations
    }
    for investigation_id in CASE_SPECS[case_id]["orders"][0][1:]:
        investigation = investigations[investigation_id]
        accepted = submit_service_action(
            service,
            player_id=created.player_id,
            case_id=case_id,
            session_id=started.session_id,
            tool=TOOL_BY_ACTION[investigation.action_type],
            investigation_id=investigation_id,
        )
        assert accepted.ok
    session = store.load_case_session(started.session_id)
    diagnosed = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=ToolName.SUBMIT_DIAGNOSIS,
        diagnosis_id=CASE_SPECS[case_id]["correct_diagnosis"],
        evidence_clue_ids=sorted(session.discovered_clue_ids),
    )
    assert diagnosed.ok
    before_unknown_treatment = path.read_bytes()
    unknown_treatment = submit_service_action(
        service,
        player_id=created.player_id,
        case_id=case_id,
        session_id=started.session_id,
        tool=ToolName.EXECUTE_TREATMENT,
        treatment_id="unknown_treatment",
    )
    assert not unknown_treatment.ok
    assert unknown_treatment.error_code == "unknown_treatment"
    assert unknown_treatment.event_sequences == ()
    assert path.read_bytes() == before_unknown_treatment
    assert store.load_case_session(started.session_id).revision == 7


@pytest.mark.parametrize("case_id", NEW_CASE_IDS)
def test_public_case_view_contains_no_hidden_truth_or_future_clues(case_id: str) -> None:
    case = load_case(case_id)
    player = qualified_player()
    session = CaseSessionState(
        session_id=f"session_public_{case_id}",
        case_id=case_id,
        player_id=player.player_id,
    )
    observation = AgentContextFilter().case_observation(case, player, session)
    public_payload = observation.model_dump_json()

    forbidden_names = (
        "root_cause",
        "causal_chain",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "score",
        "hidden_information",
    )
    assert not any(name in public_payload for name in forbidden_names)
    assert case.root_cause not in public_payload
    assert not any(text in public_payload for text in case.causal_chain)
    assert not any(text in public_payload for text in case.patient.hidden_information)
    assert observation.discovered_clues == ()


def test_catalog_discovers_exactly_three_cases_in_stable_order(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    created = service.create_player(CreatePlayerInput(display_name="目录测试者"))
    assert created.ok and created.player_id
    listed = service.list_cases(ListCasesInput(player_id=created.player_id))
    assert listed.ok
    assert tuple(item.case_id for item in listed.cases) == tuple(sorted(ALL_CASE_IDS))
    serialized = listed.model_dump_json()
    assert "灰灶客栈与无火炊烟" in serialized
    assert "月井回声与错投木简" in serialized
    assert "旧纸伞与失约书生" in serialized
    assert "root_cause" not in serialized


def test_one_player_can_keep_independent_sessions_and_completion_is_isolated(
    tmp_path: Path,
) -> None:
    service, store = build_service(tmp_path)
    created = service.create_player(CreatePlayerInput(display_name="三案行者"))
    assert created.ok and created.player_id
    gray = service.start_episode(
        StartEpisodeInput(player_id=created.player_id, case_id="gray_hearth_inn")
    )
    moon = service.start_episode(
        StartEpisodeInput(player_id=created.player_id, case_id="moon_well_echo")
    )
    assert gray.ok and gray.session_id and moon.ok and moon.session_id
    assert gray.session_id != moon.session_id
    moon_path = tmp_path / "state" / "case_sessions" / f"{moon.session_id}.json"
    moon_before = moon_path.read_bytes()

    complete_service_case(
        service,
        player_id=created.player_id,
        case_id="gray_hearth_inn",
        session_id=gray.session_id,
    )

    gray_final = store.load_case_session(gray.session_id)
    moon_final = store.load_case_session(moon.session_id)
    player = store.load_player(created.player_id)
    assert gray_final.outcome is TreatmentOutcome.RESOLVED
    assert gray_final.score == 100
    assert moon_final.revision == 0
    assert moon_path.read_bytes() == moon_before
    assert player.handled_case_ids == frozenset()
    assert player.revision == 0


def test_cli_lists_all_three_cases_without_hidden_truth(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    completed = run_cli(state_dir, "1\n目录玩家\n1\n0\n99\n")
    output = completed.stdout.decode("utf-8")
    assert completed.returncode == 0
    assert completed.stderr == b""
    assert "灰灶客栈与无火炊烟" in output
    assert "月井回声与错投木简" in output
    assert "旧纸伞与失约书生" in output
    assert "root_cause" not in output
    assert "valid_diagnosis_ids" not in output


@pytest.mark.parametrize("case_menu", ["1", "2"])
def test_cli_can_restart_and_resume_each_new_case(
    tmp_path: Path,
    case_menu: str,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    first = run_cli(state_dir, f"1\n恢复玩家{case_menu}\n1\n{case_menu}\n1\n99\n")
    store = JsonStateStore(state_dir)
    sessions_after_first = store.list_case_sessions()
    assert first.returncode == 0
    assert first.stderr == b""
    assert len(sessions_after_first) == 1
    assert sessions_after_first[0].revision == 1

    second = run_cli(state_dir, f"2\n1\n1\n{case_menu}\n1\n99\n")
    sessions_after_second = store.list_case_sessions()
    assert second.returncode == 0
    assert second.stderr == b""
    assert "已恢复未完成病例" in second.stdout.decode("utf-8")
    assert len(sessions_after_second) == 1
    assert sessions_after_second[0].session_id == sessions_after_first[0].session_id
    assert sessions_after_second[0].revision == 2
    assert [record.sequence for record in sessions_after_second[0].action_history] == [1, 2]


def test_new_case_files_contain_only_fictional_non_medical_content() -> None:
    payload = "\n".join(
        (CASE_DIR / f"{case_id}.json").read_text(encoding="utf-8")
        for case_id in NEW_CASE_IDS
    )
    assert not any(term in payload for term in ("mg", "毫克", "处方药", "真实诊断"))
    parsed = json.loads((CASE_DIR / "gray_hearth_inn.json").read_text(encoding="utf-8"))
    assert parsed["case_id"] == "gray_hearth_inn"
