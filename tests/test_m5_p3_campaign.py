from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.application import (
    CampaignPlayerInput,
    CampaignRuleConfigurationError,
    CampaignRuleSet,
    CaseCatalog,
    CreatePlayerInput,
    FinishEpisodeInput,
    ListCasesInput,
    MultiCaseEpisodeService,
    ReconcileCampaignInput,
    ResumeEpisodeInput,
    StartEpisodeInput,
    SubmitActionInput,
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CampaignEventReplayer,
    CampaignReplayError,
    CampaignState,
    CaseActionType,
    ToolCallRequest,
    ToolName,
    TreatmentOutcome,
)
from xuanyi_npc.storage import JsonStateStore, StorageError


ROOT = Path(__file__).parents[1]
RESOURCE_ROOT = ROOT / "src" / "xuanyi_npc" / "resources"
CASE_DIR = RESOURCE_ROOT / "cases"
RULES_PATH = RESOURCE_ROOT / "campaign" / "cross_episode_rules_v1.json"

CASE_TRACES = {
    "old_paper_umbrella": {
        "order": (
            "observe_scholar",
            "ask_about_memory",
            "inspect_umbrella",
            "observe_contract_trace",
            "search_book_chest",
            "ask_about_promise",
        ),
        "diagnosis": "rain_vow_breach",
        "wrong_diagnosis": "evil_spirit_attack",
        "treatment": "return_token_and_fulfill_vow",
    },
    "gray_hearth_inn": {
        "order": (
            "observe_cook",
            "question_innkeeper",
            "inspect_fuel_and_hearth",
            "inspect_hearth_contract",
            "observe_flue_qi",
            "investigate_smoke_passage",
        ),
        "diagnosis": "displaced_hearth_contract",
        "wrong_diagnosis": "ash_wraith_intrusion",
        "treatment": "restore_token_and_clear_flue",
    },
    "moon_well_echo": {
        "order": (
            "observe_courier",
            "question_route",
            "inspect_wooden_slip",
            "inspect_binding_cord",
            "observe_well_echo_qi",
            "question_lantern_witness",
        ),
        "diagnosis": "misbound_message_handoff",
        "wrong_diagnosis": "malicious_echo_entity",
        "treatment": "verify_recipient_and_deliver",
    },
}

TOOL_BY_ACTION = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


class Ids:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.count = 0

    def new_player_id(self) -> str:
        self.count += 1
        return f"player_{self.prefix}_{self.count}"

    def new_session_id(self) -> str:
        self.count += 1
        return f"session_{self.prefix}_{self.count}"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 10, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self.value += timedelta(minutes=1)
        return self.value


class FailingCampaignStore(JsonStateStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.fail_campaign = True
        self.campaign_writes = 0

    def save_campaign(self, state: CampaignState) -> Path:
        self.campaign_writes += 1
        if self.fail_campaign:
            raise StorageError("injected campaign save failure")
        return super().save_campaign(state)


class FailingSessionStore(JsonStateStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.fail_sessions = False
        self.campaign_writes = 0

    def save_case_session(self, state):
        if self.fail_sessions:
            raise StorageError("injected session save failure")
        return super().save_case_session(state)

    def save_campaign(self, state: CampaignState) -> Path:
        self.campaign_writes += 1
        return super().save_campaign(state)


def build_service(
    state_dir: Path,
    *,
    store: JsonStateStore | None = None,
    prefix: str = "p3",
) -> tuple[MultiCaseEpisodeService, JsonStateStore]:
    catalog = CaseCatalog(CASE_DIR)
    resolved_store = store or JsonStateStore(state_dir)
    service = MultiCaseEpisodeService(
        state_store=resolved_store,
        case_catalog=catalog,
        campaign_rules=CampaignRuleSet.load(RULES_PATH, catalog),
        player_id_factory=Ids(prefix),
        session_id_factory=Ids(prefix),
        clock=Clock(),
    )
    return service, resolved_store


def action(tool: ToolName, **arguments: object) -> AgentAction:
    return AgentAction(
        action_id="campaign_action",
        action_type=AgentActionType.USE_TOOL,
        dialogue="执行公开病例行动。",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=1.0,
    )


def start(service: MultiCaseEpisodeService, player_id: str, case_id: str) -> str:
    result = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id=case_id)
    )
    assert result.ok and result.session_id
    return result.session_id


def complete(
    service: MultiCaseEpisodeService,
    player_id: str,
    case_id: str,
    session_id: str,
    *,
    diagnosis_id: str | None = None,
    treatment_id: str | None = None,
):
    definition = service.case_catalog.get(case_id)
    assert definition is not None
    spec = CASE_TRACES[case_id]
    investigations = {item.investigation_id: item for item in definition.investigations}
    for investigation_id in spec["order"]:
        investigation = investigations[investigation_id]
        result = service.submit_action(
            SubmitActionInput(
                player_id=player_id,
                case_id=case_id,
                session_id=session_id,
                action=action(
                    TOOL_BY_ACTION[investigation.action_type],
                    investigation_id=investigation_id,
                ),
            )
        )
        assert result.ok
    current = service.state_store.load_case_session(session_id)
    diagnosed = service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            action=action(
                ToolName.SUBMIT_DIAGNOSIS,
                diagnosis_id=diagnosis_id or spec["diagnosis"],
                evidence_clue_ids=sorted(current.discovered_clue_ids),
            ),
        )
    )
    assert diagnosed.ok
    return service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            action=action(
                ToolName.EXECUTE_TREATMENT,
                treatment_id=treatment_id or spec["treatment"],
            ),
        )
    )


def create_player(service: MultiCaseEpisodeService, name: str = "巡案学徒") -> str:
    result = service.create_player(CreatePlayerInput(display_name=name))
    assert result.ok and result.player_id
    for exercise in service.progression_policy.config.foundation_exercises:
        assert service.complete_foundation_exercise(result.player_id,exercise.exercise_id,exercise.required_action_id).ok
    return result.player_id


def snapshot_hash(model: CampaignState) -> str:
    return hashlib.sha256(
        model.model_dump_json().encode("utf-8")
    ).hexdigest()


def test_campaign_contracts_are_strict_replayable_and_contiguous(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    final = complete(service, player_id, "old_paper_umbrella", session_id)
    assert final.campaign_event_sequences == (1,)
    state = store.load_campaign(player_id)
    rebuilt = CampaignEventReplayer().replay(
        CampaignState(player_id=player_id), state.event_history
    )
    assert rebuilt == state
    with pytest.raises(CampaignReplayError):
        CampaignEventReplayer().replay(
            CampaignState(player_id=player_id),
            [state.event_history[0].model_copy(update={"sequence": 2})],
        )
    with pytest.raises(ValidationError):
        CampaignState.model_validate({"player_id": player_id, "unknown": True})


def test_rules_are_strict_and_validate_catalog_references(tmp_path: Path) -> None:
    catalog = CaseCatalog(CASE_DIR)
    rules = CampaignRuleSet.load(RULES_PATH, catalog)
    assert tuple(item.case_id for item in rules.config.recommended_case_order) == (
        "old_paper_umbrella",
        "gray_hearth_inn",
        "moon_well_echo",
    )
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    payload["rules"][0]["effect"]["recommended_investigation_id"] = "unknown"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CampaignRuleConfigurationError):
        CampaignRuleSet.load(invalid, catalog)

    duplicate = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    duplicate["rules"][1]["effect"]["knowledge_id"] = (
        duplicate["rules"][0]["effect"]["knowledge_id"]
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(CampaignRuleConfigurationError):
        CampaignRuleSet.load(duplicate_path, catalog)


def test_campaign_a_unlocks_two_knowledge_and_reacts_without_locking(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    expected_knowledge = (
        ("old_paper_umbrella", "contract_provenance_check"),
        ("gray_hearth_inn", "handoff_sequence_check"),
    )
    for index, case_id in enumerate(CASE_TRACES):
        session_id = start(service, player_id, case_id)
        resumed = service.resume_episode(
            ResumeEpisodeInput(
                player_id=player_id,
                case_id=case_id,
                session_id=session_id,
            )
        )
        if case_id == "gray_hearth_inn":
            assert "旧纸伞案" in (resumed.history_reaction or "")
            assert resumed.recommended_investigation_id == "inspect_hearth_contract"
        if case_id == "moon_well_echo":
            assert "灰灶案" in (resumed.history_reaction or "")
            assert resumed.recommended_investigation_id == "question_lantern_witness"
        final = complete(service, player_id, case_id, session_id)
        assert final.episode_result is not None
        assert final.episode_result.outcome is TreatmentOutcome.RESOLVED
        assert final.episode_result.score == 100
        assert final.event_sequences == (8,)
        session = store.load_case_session(session_id)
        assert tuple(record.sequence for record in session.action_history) == tuple(
            range(1, 9)
        )
        if index < 2:
            assert final.newly_unlocked_knowledge[0].knowledge_id == expected_knowledge[index][1]

    campaign = store.load_campaign(player_id)
    assert campaign.revision == 3
    assert tuple(event.sequence for event in campaign.event_history) == (1, 2, 3)
    assert campaign.unlocked_knowledge_ids == {
        "contract_provenance_check",
        "handoff_sequence_check",
    }
    assert CampaignEventReplayer().replay(
        CampaignState(player_id=player_id), campaign.event_history
    ) == campaign


def test_campaign_b_can_complete_moon_first_with_neutral_context(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    listed = service.list_cases(ListCasesInput(player_id=player_id))
    assert all(case.can_start for case in listed.cases)
    assert [case.case_id for case in listed.cases if case.is_recommended_next] == [
        "old_paper_umbrella"
    ]
    session_id = start(service, player_id, "moon_well_echo")
    resumed = service.resume_episode(
        ResumeEpisodeInput(
            player_id=player_id,
            case_id="moon_well_echo",
            session_id=session_id,
        )
    )
    assert "分别核对送信人的陈述" in (resumed.history_reaction or "")
    assert resumed.recommended_investigation_id is None
    final = complete(service, player_id, "moon_well_echo", session_id)
    assert final.episode_result is not None
    assert final.episode_result.outcome is TreatmentOutcome.RESOLVED
    assert final.episode_result.score == 100
    campaign = store.load_campaign(player_id)
    assert campaign.unlocked_knowledge_ids == frozenset()


def test_wrong_diagnosis_still_unlocks_from_public_outcome_and_treatment(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    final = complete(
        service,
        player_id,
        "old_paper_umbrella",
        session_id,
        diagnosis_id="evil_spirit_attack",
    )
    assert final.episode_result is not None
    assert final.episode_result.outcome is TreatmentOutcome.RESOLVED
    assert final.episode_result.score < 100
    assert store.load_campaign(player_id).unlocked_knowledge_ids == {
        "contract_provenance_check"
    }


@pytest.mark.parametrize(
    "treatment_id,outcome",
    [
        ("seal_old_umbrella", TreatmentOutcome.SUPPRESSED),
        ("burn_old_umbrella", TreatmentOutcome.WORSENED),
    ],
)
def test_non_resolved_outcomes_do_not_unlock(
    tmp_path: Path, treatment_id: str, outcome: TreatmentOutcome
) -> None:
    service, store = build_service(tmp_path / treatment_id)
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    final = complete(
        service,
        player_id,
        "old_paper_umbrella",
        session_id,
        treatment_id=treatment_id,
    )
    assert final.episode_result is not None and final.episode_result.outcome is outcome
    assert store.load_campaign(player_id).unlocked_knowledge_ids == frozenset()


def test_duplicate_finish_and_reconcile_are_idempotent(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    complete(service, player_id, "old_paper_umbrella", session_id)
    before = store.load_campaign(player_id)
    before_hash = snapshot_hash(before)
    finished = service.finish_episode(
        FinishEpisodeInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
        )
    )
    reconciled = service.reconcile_campaign(
        ReconcileCampaignInput(player_id=player_id)
    )
    assert finished.ok and finished.campaign_event_sequences == ()
    assert reconciled.ok and reconciled.campaign_event_sequences == ()
    assert snapshot_hash(store.load_campaign(player_id)) == before_hash


def test_campaign_failure_is_pending_and_reconcile_recovers(tmp_path: Path) -> None:
    store = FailingCampaignStore(tmp_path / "state")
    service, _ = build_service(tmp_path / "state", store=store)
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    final = complete(service, player_id, "old_paper_umbrella", session_id)
    assert final.ok
    assert final.campaign_status.value == "pending"
    assert final.campaign_error_code == "campaign_projection_pending"
    assert store.load_case_session(session_id).status.value == "completed"
    store.fail_campaign = False
    recovered = service.reconcile_campaign(
        ReconcileCampaignInput(player_id=player_id)
    )
    assert recovered.ok and recovered.campaign_event_sequences == (1,)
    repeated = service.reconcile_campaign(
        ReconcileCampaignInput(player_id=player_id)
    )
    assert repeated.ok and repeated.campaign_event_sequences == ()


def test_session_save_failure_writes_no_campaign(tmp_path: Path) -> None:
    store = FailingSessionStore(tmp_path / "state")
    service, _ = build_service(tmp_path / "state", store=store)
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    definition = service.case_catalog.get("old_paper_umbrella")
    assert definition is not None
    store.fail_sessions = True
    result = service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
            action=action(
                ToolName.OBSERVE_PATIENT,
                investigation_id="observe_scholar",
            ),
        )
    )
    assert not result.ok and result.event_sequences == ()
    assert store.campaign_writes == 0
    assert store.load_case_session(session_id).revision == 0


def test_rejected_action_and_quit_do_not_write_campaign(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    session_path = store.root / "case_sessions" / f"{session_id}.json"
    before = session_path.read_bytes()
    rejected = service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=session_id,
            action=action(
                ToolName.SUBMIT_DIAGNOSIS,
                diagnosis_id="rain_vow_breach",
                evidence_clue_ids=[],
            ),
        )
    )
    assert not rejected.ok and rejected.error_code == "diagnosis_not_ready"
    assert session_path.read_bytes() == before
    assert not (store.root / "campaigns" / f"{player_id}.json").exists()


def test_players_are_isolated_and_cross_player_resume_is_zero_write(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_a = create_player(service, "甲")
    player_b = create_player(service, "乙")
    session_a = start(service, player_a, "old_paper_umbrella")
    complete(service, player_a, "old_paper_umbrella", session_a)
    campaign_a_path = store.root / "campaigns" / f"{player_a}.json"
    before = campaign_a_path.read_bytes()
    forged = service.resume_episode(
        ResumeEpisodeInput(
            player_id=player_b,
            case_id="old_paper_umbrella",
            session_id=session_a,
        )
    )
    assert not forged.ok and forged.error_code == "session_player_mismatch"
    assert campaign_a_path.read_bytes() == before
    view_b = service.get_campaign_view(CampaignPlayerInput(player_id=player_b))
    assert view_b.ok and view_b.campaign_view is not None
    assert view_b.campaign_view.unlocked_knowledge == ()


def test_corrupt_campaign_fails_instead_of_becoming_empty(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    path = store.root / "campaigns" / f"{player_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    result = service.get_campaign_view(CampaignPlayerInput(player_id=player_id))
    assert not result.ok and result.error_code == "campaign_state_corrupt"


def test_deleted_source_cannot_silently_reconcile(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    complete(service, player_id, "old_paper_umbrella", session_id)
    campaign_path = store.root / "campaigns" / f"{player_id}.json"
    before = campaign_path.read_bytes()
    (store.root / "case_sessions" / f"{session_id}.json").unlink()
    result = service.reconcile_campaign(ReconcileCampaignInput(player_id=player_id))
    assert not result.ok and result.error_code == "campaign_source_missing"
    assert campaign_path.read_bytes() == before


def test_tampered_source_receipt_cannot_silently_reconcile(tmp_path: Path) -> None:
    service, store = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    complete(service, player_id, "old_paper_umbrella", session_id)
    campaign_path = store.root / "campaigns" / f"{player_id}.json"
    before = campaign_path.read_bytes()
    session_path = store.root / "case_sessions" / f"{session_id}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["action_history"][1]["sequence"] = 9
    session_path.write_text(json.dumps(payload), encoding="utf-8")
    result = service.reconcile_campaign(ReconcileCampaignInput(player_id=player_id))
    assert not result.ok and result.error_code == "campaign_source_conflict"
    assert campaign_path.read_bytes() == before


def test_campaign_public_view_omits_hidden_case_truth(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path / "state")
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    complete(service, player_id, "old_paper_umbrella", session_id)
    view = service.get_campaign_view(CampaignPlayerInput(player_id=player_id))
    payload = view.model_dump_json()
    for sentinel in (
        "root_cause",
        "causal_chain",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "hidden_wooden_token",
    ):
        assert sentinel not in payload


def test_cli_shows_history_knowledge_recommendation_and_case_reaction(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    service, _ = build_service(state_dir)
    player_id = create_player(service)
    session_id = start(service, player_id, "old_paper_umbrella")
    complete(service, player_id, "old_paper_umbrella", session_id)
    env = os.environ.copy()
    for key in ("DEEPSEEK_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(key, None)
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "xuanyi_npc.cli.play",
            "--case-dir",
            str(CASE_DIR),
            "--state-dir",
            str(state_dir),
        ],
        input="2\n1\n2\n1\n1\n1\n99\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert "玩家历程" in completed.stdout
    assert "契约类异常" in completed.stdout
    assert "推荐下一案：灰灶客栈与无火炊烟" in completed.stdout
    assert "旧纸伞案中核对过契物来源" in completed.stdout
    assert "Traceback" not in completed.stdout


def test_three_independent_processes_preserve_campaign_progress(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    script = r'''
import os
import sys
from pathlib import Path
from xuanyi_npc.application import CampaignRuleSet, CaseCatalog, MultiCaseEpisodeService, StartEpisodeInput, SubmitActionInput
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseActionType, ToolCallRequest, ToolName
from xuanyi_npc.storage import JsonStateStore
root = Path(sys.argv[1]); state = Path(sys.argv[2]); player = sys.argv[3]; case_id = sys.argv[4]; session_id = sys.argv[5]
resources = root / "src" / "xuanyi_npc" / "resources"
catalog = CaseCatalog(resources / "cases")
service = MultiCaseEpisodeService(state_store=JsonStateStore(state), case_catalog=catalog, campaign_rules=CampaignRuleSet.load(resources / "campaign" / "cross_episode_rules_v1.json", catalog))
case = catalog.get(case_id)
assert case is not None
started = service.start_episode(StartEpisodeInput(player_id=player, case_id=case_id))
assert started.ok and started.session_id == session_id
tools = {CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT, CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT, CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT, CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI, CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION}
orders = {
"old_paper_umbrella": ["observe_scholar","ask_about_memory","inspect_umbrella","observe_contract_trace","search_book_chest","ask_about_promise"],
"gray_hearth_inn": ["observe_cook","question_innkeeper","inspect_fuel_and_hearth","inspect_hearth_contract","observe_flue_qi","investigate_smoke_passage"],
"moon_well_echo": ["observe_courier","question_route","inspect_wooden_slip","inspect_binding_cord","observe_well_echo_qi","question_lantern_witness"]}
diagnoses = {"old_paper_umbrella":"rain_vow_breach","gray_hearth_inn":"displaced_hearth_contract","moon_well_echo":"misbound_message_handoff"}
treatments = {"old_paper_umbrella":"return_token_and_fulfill_vow","gray_hearth_inn":"restore_token_and_clear_flue","moon_well_echo":"verify_recipient_and_deliver"}
def act(tool, args):
  return AgentAction(action_id="proc_action", action_type=AgentActionType.USE_TOOL, dialogue="进程轨迹", tool_call=ToolCallRequest(name=tool, arguments=args), confidence=1.0)
for iid in orders[case_id]:
  inv = next(item for item in case.investigations if item.investigation_id == iid)
  assert service.submit_action(SubmitActionInput(player_id=player,case_id=case_id,session_id=session_id,action=act(tools[inv.action_type],{"investigation_id":iid}))).ok
session = service.state_store.load_case_session(session_id)
assert service.submit_action(SubmitActionInput(player_id=player,case_id=case_id,session_id=session_id,action=act(ToolName.SUBMIT_DIAGNOSIS,{"diagnosis_id":diagnoses[case_id],"evidence_clue_ids":sorted(session.discovered_clue_ids)}))).ok
result = service.submit_action(SubmitActionInput(player_id=player,case_id=case_id,session_id=session_id,action=act(ToolName.EXECUTE_TREATMENT,{"treatment_id":treatments[case_id]})))
assert result.ok and result.episode_result.score == 100
print(f"{os.getpid()}:{result.campaign_view.revision}")
'''
    service, store = build_service(state_dir)
    player_id = create_player(service)
    env = os.environ.copy()
    for key in ("DEEPSEEK_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(key, None)
    env["PYTHONPATH"] = str(ROOT / "src")
    pids: list[int] = []
    for index, case_id in enumerate(CASE_TRACES, start=1):
        session_id = f"session_process_{index}"
        # The subprocess service uses its production UUID factory, so pre-seed a
        # deterministic active session only through the public service boundary.
        class OneSession:
            def new_session_id(self) -> str:
                return session_id
        catalog = CaseCatalog(CASE_DIR)
        seeded = MultiCaseEpisodeService(
            state_store=store,
            case_catalog=catalog,
            campaign_rules=CampaignRuleSet.load(RULES_PATH, catalog),
            session_id_factory=OneSession(),
        )
        started = seeded.start_episode(
            StartEpisodeInput(player_id=player_id, case_id=case_id)
        )
        assert started.ok
        # Resume rather than start inside the process by removing the start lines.
        process_script = script.replace(
            "started = service.start_episode(StartEpisodeInput(player_id=player, case_id=case_id))\nassert started.ok and started.session_id == session_id\n",
            "",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                process_script,
                str(ROOT),
                str(state_dir),
                player_id,
                case_id,
                session_id,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        process_pid, revision = completed.stdout.strip().split(":")
        assert revision == str(index)
        assert completed.stderr == ""
        pids.append(int(process_pid))
    assert len(set(pids)) == 3
    campaign = store.load_campaign(player_id)
    assert campaign.revision == 3
    assert campaign.unlocked_knowledge_ids == {
        "contract_provenance_check",
        "handoff_sequence_check",
    }
