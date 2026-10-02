from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

import pytest

from xuanyi_npc.application.clinic import (
    ClinicActionInput,
    ClinicContributionInput,
    ClinicError,
    ClinicService,
)
from xuanyi_npc.application.cooperative_runtime import (
    CooperativePostCommitError,
    CooperativeRuntime,
    CooperativeTurnInput,
)
from xuanyi_npc.application.memory_coordination import V1MemoryCoordinator
from xuanyi_npc.application.multicase import (
    CaseCatalog,
    CreatePlayerInput,
    MultiCaseEpisodeService,
    StartEpisodeInput,
    SubmitActionInput,
)
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import PlayerContributionType
from xuanyi_npc.storage import JsonStateStore, StorageError
from tests.r1_helpers import FixedClock, FixedPlayerIds, FixedSessionIds
from tests.test_phase_a_production_wiring import proposal_for


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


class PlanningAgent:
    def propose_turn(self, value):
        return proposal_for(value.case_observation, value.turn_id)

    def repair_action_contract(self, value, prior, feedback):
        del value, prior, feedback
        raise AssertionError("valid proposal must not be repaired")

    def action_contract_fallback(self, prior):
        del prior
        raise AssertionError("valid proposal must not fall back")


def _service(root: Path, *, store=None, memory_coordinator=None) -> MultiCaseEpisodeService:
    actual_store = store or JsonStateStore(root)
    catalog = CaseCatalog(ROOT / "cases")
    from xuanyi_npc.application.multicase import CampaignRuleSet

    return MultiCaseEpisodeService(
        state_store=actual_store,
        case_catalog=catalog,
        campaign_rules=CampaignRuleSet.load(
            ROOT / "campaign" / "cross_episode_rules_v2.json", catalog
        ),
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        clock=FixedClock(),
        memory_coordinator=memory_coordinator,
    )


def _opened(service: MultiCaseEpisodeService):
    player = service.create_player(CreatePlayerInput(display_name="提交审计玩家"))
    opened = service.start_episode(
        StartEpisodeInput(player_id=player.player_id, case_id="old_paper_umbrella")
    )
    assert opened.ok and opened.observation is not None
    return player.player_id, opened


def _request(player_id: str, opened, operation_id: str, option_index: int = 0):
    option = opened.observation.available_investigations[option_index]
    tool = {
        "observe_patient": ToolName.OBSERVE_PATIENT,
        "question_patient": ToolName.QUESTION_PATIENT,
        "inspect_object": ToolName.INSPECT_OBJECT,
        "observe_qi": ToolName.OBSERVE_QI,
        "investigate_location": ToolName.INVESTIGATE_LOCATION,
    }[option.action_type.value]
    return SubmitActionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        action=AgentAction(
            action_id=operation_id,
            action_type=AgentActionType.USE_TOOL,
            dialogue="离线提交故障注入",
            tool_call=ToolCallRequest(
                name=tool, arguments={"investigation_id": option.investigation_id}
            ),
            confidence=1.0,
        ),
    )


class RuntimeFailingProjectionRepository:
    def write_projection(self, source, memory):
        del source, memory
        raise RuntimeError("injected projection failure")


def test_unexpected_memory_failure_is_reported_after_known_world_commit(tmp_path):
    store = JsonStateStore(tmp_path / "state")
    coordinator = V1MemoryCoordinator(
        state_store=store, memory_repository=RuntimeFailingProjectionRepository()
    )
    service = _service(tmp_path / "state", store=store, memory_coordinator=coordinator)
    player_id, opened = _opened(service)

    receipt = service.submit_action_with_receipt(
        _request(player_id, opened, "memory_failure")
    )

    committed = store.load_case_session(opened.session_id)
    assert receipt.result.ok is True
    assert receipt.world_commit_status == "committed"
    assert receipt.memory_commit_status == "projection_pending"
    assert committed.revision == 1
    assert len(committed.action_history) == 1


class SaveThenRaiseStore(JsonStateStore):
    fail_after_save = False
    action_save_calls = 0

    def save_case_session(self, state):
        path = super().save_case_session(state)
        if state.revision > 0:
            self.action_save_calls += 1
        if self.fail_after_save and state.revision > 0:
            self.fail_after_save = False
            raise StorageError("injected exception after atomic replace")
        return path


def test_save_exception_after_replace_is_unknown_and_same_operation_is_not_replayed(tmp_path):
    store = SaveThenRaiseStore(tmp_path / "state")
    service = _service(tmp_path / "state", store=store)
    player_id, opened = _opened(service)
    request = _request(player_id, opened, "unknown_save")
    store.fail_after_save = True

    first = service.submit_action_with_receipt(request)
    second = service.submit_action_with_receipt(request)

    assert first.world_commit_status == "unknown"
    assert first.result.error_code == "world_commit_uncertain"
    assert second.world_commit_status == "unknown"
    assert store.action_save_calls == 1
    committed = store.load_case_session(opened.session_id)
    assert committed.revision == 1
    assert len(committed.action_history) == 1


def test_successful_operation_replay_returns_receipt_without_second_world_write(tmp_path):
    store = SaveThenRaiseStore(tmp_path / "state")
    service = _service(tmp_path / "state", store=store)
    player_id, opened = _opened(service)
    request = _request(player_id, opened, "successful_replay")

    first = service.submit_action_with_receipt(request)
    second = service.submit_action_with_receipt(request)

    assert first == second
    assert first.world_commit_status == "committed"
    assert store.action_save_calls == 1
    assert store.load_case_session(opened.session_id).revision == 1


def test_ordinary_entry_replays_same_operation_and_rejects_payload_conflict(tmp_path):
    root = tmp_path / "state"
    clinic = _recorded_clinic(root, JsonStateStore(root))
    player_id = clinic.create_player("普通入口玩家").player_summary.player_id
    opened = clinic.start_case(player_id, "old_paper_umbrella")
    first_option, second_option = opened.observation.available_investigations[:2]
    request = ClinicActionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        operation_id="ordinary_replay",
        action_type="investigation",
        selection_id=first_option.investigation_id,
    )

    first = clinic.submit_case_action(request)
    replay = clinic.submit_case_action(request)

    assert replay == first
    assert clinic.store.load_case_session(opened.session_id).revision == 1
    with pytest.raises(ClinicError) as conflict:
        clinic.submit_case_action(request.model_copy(update={
            "selection_id": second_option.investigation_id
        }))
    assert conflict.value.code == "operation_payload_conflict"
    assert clinic.store.load_case_session(opened.session_id).revision == 1


class ControlledInterleavingStore(JsonStateStore):
    def __init__(self, root):
        super().__init__(root)
        self.first_save_entered = Event()
        self.allow_first_save = Event()
        self._calls_lock = Lock()
        self.action_save_entries = 0
        self.overlap_observed = False
        self.first_save_active = False

    def save_case_session(self, state):
        if state.revision > 0:
            with self._calls_lock:
                self.action_save_entries += 1
                entry = self.action_save_entries
                if entry == 1:
                    self.first_save_active = True
                if entry == 2 and self.first_save_active:
                    self.overlap_observed = True
                    self.allow_first_save.set()
            if entry == 1:
                self.first_save_entered.set()
                self.allow_first_save.wait(timeout=0.5)
        result = super().save_case_session(state)
        if state.revision > 0 and entry == 1:
            with self._calls_lock:
                self.first_save_active = False
        return result


def test_same_session_different_operations_are_serialized_without_lost_update(tmp_path):
    store = ControlledInterleavingStore(tmp_path / "state")
    service = _service(tmp_path / "state", store=store)
    player_id, opened = _opened(service)
    requests = (
        _request(player_id, opened, "parallel_one", 0),
        _request(player_id, opened, "parallel_two", 1),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.submit_action_with_receipt, item) for item in requests]
        receipts = [item.result(timeout=3) for item in futures]

    committed = store.load_case_session(opened.session_id)
    assert all(item.result.ok for item in receipts)
    assert store.overlap_observed is False
    assert committed.revision == 2
    assert len(committed.action_history) == 2


class FailPostCommitObservationStore(JsonStateStore):
    fail_next_post_commit_load = False

    def save_case_session(self, state):
        result = super().save_case_session(state)
        if state.revision > 0:
            self.fail_next_post_commit_load = True
        return result

    def load_case_session(self, session_id):
        if self.fail_next_post_commit_load:
            self.fail_next_post_commit_load = False
            raise StorageError("injected post-commit observation failure")
        return super().load_case_session(session_id)


def _recorded_clinic(root: Path, store: JsonStateStore) -> ClinicService:
    return ClinicService(
        store=store,
        base_catalog=CaseCatalog(ROOT / "cases"),
        campaign_path=ROOT / "campaign" / "cross_episode_rules_v2.json",
        clock=FixedClock(),
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        game_npc_agent=PlanningAgent(),
        cooperative_record_enabled=True,
    )


def test_known_post_commit_failure_is_durable_and_restart_retry_is_blocked(tmp_path):
    root = tmp_path / "state"
    store = FailPostCommitObservationStore(root)
    clinic = _recorded_clinic(root, store)
    player_id = clinic.create_player("协作故障玩家").player_summary.player_id
    opened = clinic.start_case(player_id, "old_paper_umbrella", cooperative=True)
    request = ClinicContributionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        operation_id="post_commit_observation",
        text="请先执行一项公开调查。",
        contribution_type=PlayerContributionType.SUGGESTION,
    )

    with pytest.raises(ClinicError) as first:
        clinic.submit_player_contribution(request)
    assert first.value.code == "operation_committed_followup_incomplete"
    assert store.load_case_session(opened.session_id).revision == 1
    record = clinic.cooperative_history_repository.get(
        player_id, opened.case_id, opened.session_id, request.operation_id
    )
    assert record.lifecycle == "recovery_required"
    assert record.failure_code == "committed_observation_reload_failed"

    rebuilt = _recorded_clinic(root, JsonStateStore(root))
    with pytest.raises(ClinicError) as retry:
        rebuilt.submit_player_contribution(request)
    assert retry.value.code == "operation_committed_followup_incomplete"


def test_unknown_world_commit_is_durable_and_restart_retry_is_blocked(tmp_path):
    root = tmp_path / "state"
    store = SaveThenRaiseStore(root)
    clinic = _recorded_clinic(root, store)
    player_id = clinic.create_player("未知提交玩家").player_summary.player_id
    opened = clinic.start_case(player_id, "old_paper_umbrella", cooperative=True)
    request = ClinicContributionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        operation_id="unknown_world_commit",
        text="请先执行一项公开调查。",
        contribution_type=PlayerContributionType.SUGGESTION,
    )
    store.fail_after_save = True

    with pytest.raises(ClinicError) as first:
        clinic.submit_player_contribution(request)
    assert first.value.code == "operation_recovery_uncertain"
    assert store.load_case_session(opened.session_id).revision == 1
    record = clinic.cooperative_history_repository.get(
        player_id, opened.case_id, opened.session_id, request.operation_id
    )
    assert record.lifecycle == "recovery_required"
    assert record.failure_code == "runtime_result_uncertain"

    rebuilt = _recorded_clinic(root, JsonStateStore(root))
    with pytest.raises(ClinicError) as retry:
        rebuilt.submit_player_contribution(request)
    assert retry.value.code == "operation_recovery_uncertain"
    assert rebuilt.store.load_case_session(opened.session_id).revision == 1


class FailingPlanEvaluator:
    def condition_met(self, condition, observation):
        del condition, observation
        return False

    def evaluate(self, **kwargs):
        del kwargs
        raise RuntimeError("injected plan evaluator failure")


def test_plan_evaluator_failure_after_world_commit_is_typed(tmp_path):
    service = _service(tmp_path / "state")
    player_id, opened = _opened(service)
    contribution = ClinicContributionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        operation_id="plan_evaluator_failure",
        text="请先执行一项公开调查。",
        contribution_type=PlayerContributionType.SUGGESTION,
    )
    from xuanyi_npc.domain.cooperation import PlayerContribution

    runtime = CooperativeRuntime(
        service=service,
        agent=PlanningAgent(),
        plan_evaluator=FailingPlanEvaluator(),
    )
    turn = PlayerContribution(
        contribution_id=contribution.operation_id,
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        contribution_type=contribution.contribution_type,
        public_text=contribution.text,
        created_at=FixedClock().now(),
    )

    with pytest.raises(CooperativePostCommitError) as exc:
        runtime.handle(CooperativeTurnInput(contribution=turn))
    assert exc.value.stage == "plan_evaluator"
    assert service.state_store.load_case_session(opened.session_id).revision == 1
