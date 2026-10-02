from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
import hashlib
import json

import pytest

from xuanyi_npc.agents import (
    DeterministicCooperativeNPC,
    GameNPCAgent,
    ScriptedFakeLLM,
    SimpleActionGameNPCAgent,
)
from xuanyi_npc.application.clinic import ClinicError
from xuanyi_npc.application.cooperative_context import (
    build_context_snapshot,
    project_pending_snapshot,
)
from xuanyi_npc.application.action_contract import build_safe_action_feedback
from xuanyi_npc.agents.llm import ChatMessage, ChatRole
from xuanyi_npc.domain.cooperative_context import (
    CooperativeContextSnapshot,
    HistoryOmissionView,
    PendingConfirmationContextView,
)
from xuanyi_npc.domain.cooperation import GameNPCDecision
from xuanyi_npc.domain import AgentAction, AgentActionType
from xuanyi_npc.domain.cooperation import (
    AuthorityMode,
    PendingActionConfirmation,
    PlayerContributionType,
)
from xuanyi_npc.storage import (
    CooperativeHistoryError,
    CooperativePayloadConflict,
    SQLiteCooperativeHistoryRepository,
)
from tests.test_context_engineering_ce11 import (
    _RuntimeA1ContractRepairAgent,
    _repair_proposal,
)
from tests.test_phase_a_production_wiring import (
    clinic_at,
    contribution,
    opened_clinic,
    proposal_for,
)
from tests.context_baseline_support import action_input, planning_input


def _enable(clinic, tmp_path: Path, *, context: bool = True):
    repository = SQLiteCooperativeHistoryRepository(tmp_path / "cooperative.sqlite3")
    clinic.cooperative_history_repository = repository
    clinic.cooperative_record_enabled = True
    clinic.cooperative_context_v2_enabled = context
    return repository


def _pending(opened, suffix: str, *, player_id: str = "player_0001", revision: int | None = None):
    return PendingActionConfirmation(
        confirmation_id=f"confirmation_{suffix}",
        decision_id=f"decision_{suffix}",
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        action=AgentAction(
            action_id=f"action_{suffix}",
            action_type=AgentActionType.RESPOND,
            dialogue="等待玩家确认。",
            confidence=0.5,
        ),
        authority_mode=AuthorityMode.CONFIRMATION_REQUIRED,
        public_rationale="这是当前公开待确认事项。",
        case_revision=opened.observation.session_revision if revision is None else revision,
    )


def test_v2_requires_recording(tmp_path: Path) -> None:
    clinic, _, _ = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    clinic.cooperative_record_enabled = False
    clinic.cooperative_context_v2_enabled = True
    # Constructor enforces this for real wiring; this assertion documents the
    # legal combinations without rebuilding the sizeable fixture.
    with pytest.raises(ValueError, match="requires cooperative recording"):
        clinic.__post_init__()


def test_a0_initial_and_format_repair_share_one_history_pending_snapshot(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    _enable(clinic, tmp_path)
    clinic.submit_player_contribution(contribution(player_id, opened, "history_a0"))
    pending = _pending(
        opened,
        "a0",
        player_id=player_id,
        revision=clinic.store.load_case_session(opened.session_id).revision,
    )
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    fake = ScriptedFakeLLM(["not-json", "still-not-json"])
    clinic.game_npc_agent = SimpleActionGameNPCAgent(fake)

    current = contribution(player_id, opened, "current_a0").model_copy(update={
        "contribution_type": PlayerContributionType.APPROVAL,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })
    clinic.submit_player_contribution(current)

    assert len(fake.requests) == 2
    initial = fake.requests[0]
    repaired = fake.requests[1]
    assert [item.role.value for item in initial.messages] == [
        "system", "user", "assistant", "user"
    ]
    assert "history_a0" in initial.messages[1].content
    assert pending.confirmation_id in initial.messages[-1].content
    assert '"responds_to_current_contribution": true' in initial.messages[-1].content
    assert tuple(repaired.messages[: len(initial.messages)]) == initial.messages


def test_a1_initial_format_and_action_repair_receive_the_same_v2_snapshot(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    _enable(clinic, tmp_path)
    clinic.submit_player_contribution(contribution(player_id, opened, "history_a1"))

    format_fake = ScriptedFakeLLM(["not-json", "still-not-json"])
    clinic.game_npc_agent = GameNPCAgent(format_fake)
    clinic.submit_player_contribution(contribution(player_id, opened, "current_a1_format"))
    assert len(format_fake.requests) == 2
    assert "history_a1" in format_fake.requests[0].messages[1].content
    assert tuple(format_fake.requests[1].messages[: len(format_fake.requests[0].messages)]) == format_fake.requests[0].messages

    repair_clinic, repair_player_id, repair_opened = opened_clinic(
        tmp_path / "repair", DeterministicCooperativeNPC()
    )
    _enable(repair_clinic, tmp_path / "repair")
    repair_clinic.submit_player_contribution(
        contribution(repair_player_id, repair_opened, "history_a1_repair")
    )
    operation_id = "current_a1_action_repair"
    repaired = _repair_proposal(
        repair_clinic.resume_case(
            repair_player_id, repair_opened.case_id, repair_opened.session_id
        ).observation,
        operation_id,
        0,
    )
    repair_fake = ScriptedFakeLLM([repaired.model_dump_json()])
    repair_clinic.game_npc_agent = _RuntimeA1ContractRepairAgent(repair_fake)
    repair_clinic.submit_player_contribution(
        contribution(repair_player_id, repair_opened, operation_id)
    )
    assert len(repair_fake.requests) == 1
    assert "history_a1_repair" in repair_fake.requests[0].messages[1].content


def test_followup_changed_mind_and_rejection_are_complete_non_authoritative_turns(tmp_path: Path) -> None:
    history_fake = ScriptedFakeLLM(["bad", "bad", "bad", "bad"])
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(history_fake)
    )
    _enable(clinic, tmp_path)
    first = contribution(player_id, opened, "first_op").model_copy(update={
        "text": "我先认为应检查第一条线索。",
        "contribution_type": PlayerContributionType.HYPOTHESIS,
    })
    changed = contribution(player_id, opened, "changed_op").model_copy(update={
        "text": "我改口，并拒绝沿用刚才的建议。",
        "contribution_type": PlayerContributionType.REJECTION,
    })
    clinic.submit_player_contribution(first)
    clinic.submit_player_contribution(changed)
    fake = ScriptedFakeLLM(["bad", "bad"])
    clinic.game_npc_agent = SimpleActionGameNPCAgent(fake)
    current = contribution(player_id, opened, "followup_op").model_copy(
        update={"text": "请基于当前公开状态继续讨论。"}
    )
    clinic.submit_player_contribution(current)

    initial = fake.requests[0]
    assert [message.role.value for message in initial.messages[:-1]] == [
        "system", "user", "assistant", "user", "assistant"
    ]
    assert "hypothesis" in initial.messages[1].content
    assert "我先认为" in initial.messages[1].content
    assert "rejection" in initial.messages[3].content
    assert "我改口" in initial.messages[3].content
    assert "followup_op" not in "".join(message.content for message in initial.messages[:-1])


def test_history_does_not_cross_player_or_session_scope(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    _enable(clinic, tmp_path)
    clinic.submit_player_contribution(contribution(player_id, opened, "private_history"))
    other_player = clinic.create_player("另一玩家").player_summary.player_id
    other_opened = clinic.start_case(other_player, opened.case_id, cooperative=True)
    fake = ScriptedFakeLLM(["bad", "bad"])
    clinic.game_npc_agent = SimpleActionGameNPCAgent(fake)
    clinic.submit_player_contribution(
        contribution(other_player, other_opened, "other_scope")
    )
    assert "private_history" not in "".join(
        message.content for message in fake.requests[0].messages
    )


def test_completed_operation_replays_without_model_or_history_append(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    repository = _enable(clinic, tmp_path)
    request = contribution(player_id, opened, "completed_replay")
    first = clinic.submit_player_contribution(request)
    agent = clinic.game_npc_agent

    replay = clinic.submit_player_contribution(request)

    assert replay.model_dump() == first.model_copy(update={"pending_action": None}).model_dump()
    record = repository.get(player_id, opened.case_id, opened.session_id, request.operation_id)
    assert record is not None and record.lifecycle == "completed"
    assert isinstance(agent, DeterministicCooperativeNPC)


@pytest.mark.parametrize(
    "contribution_type",
    (PlayerContributionType.APPROVAL, PlayerContributionType.REJECTION),
)
def test_completed_pending_response_replays_after_original_pending_is_removed(
    tmp_path: Path, contribution_type: PlayerContributionType
) -> None:
    fake = ScriptedFakeLLM(["bad", "bad"])
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(fake)
    )
    repository = _enable(clinic, tmp_path)
    pending = _pending(
        opened,
        contribution_type.value,
        player_id=player_id,
        revision=clinic.store.load_case_session(opened.session_id).revision,
    )
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    request = contribution(player_id, opened, f"completed_{contribution_type.value}").model_copy(
        update={
            "text": f"完成{contribution_type.value}响应。",
            "contribution_type": contribution_type,
            "responds_to_decision_id": pending.decision_id,
            "pending_confirmation_id": pending.confirmation_id,
        }
    )
    first = clinic.submit_player_contribution(request)
    assert pending.confirmation_id not in clinic.cooperative_pending
    world_before_replay = clinic.store.load_case_session(opened.session_id)

    replay = clinic.submit_player_contribution(request)

    assert replay == first.model_copy(update={"pending_action": None})
    assert len(fake.requests) == 2
    assert clinic.store.load_case_session(opened.session_id) == world_before_replay
    record = repository.get(player_id, opened.case_id, opened.session_id, request.operation_id)
    assert record is not None and record.lifecycle == "completed"
    assert pending.confirmation_id not in clinic.cooperative_pending


def test_completed_approval_with_tool_replays_without_second_model_or_tool_call(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    _enable(clinic, tmp_path)
    operation_id = "approved_tool_replay"
    proposal = proposal_for(opened.observation, operation_id).decision
    fake = ScriptedFakeLLM([proposal.model_dump_json()])
    clinic.game_npc_agent = SimpleActionGameNPCAgent(fake)
    pending = PendingActionConfirmation(
        confirmation_id="confirmation_approved_tool_replay",
        decision_id="decision_approved_tool_replay",
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        action=proposal.action,
        authority_mode=AuthorityMode.CONFIRMATION_REQUIRED,
        public_rationale="固定公开行动等待确认。",
        case_revision=opened.observation.session_revision,
    )
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    request = contribution(player_id, opened, operation_id).model_copy(update={
        "contribution_type": PlayerContributionType.APPROVAL,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })
    before = clinic.store.load_case_session(opened.session_id)
    first = clinic.submit_player_contribution(request)
    after_first = clinic.store.load_case_session(opened.session_id)
    assert first.status.value == "action_executed"
    assert len(after_first.action_history) == len(before.action_history) + 1
    assert pending.confirmation_id not in clinic.cooperative_pending

    replay = clinic.submit_player_contribution(request)

    assert replay == first.model_copy(update={"pending_action": None})
    assert len(fake.requests) == 1
    assert clinic.store.load_case_session(opened.session_id) == after_first


def test_restart_replays_completed_pending_response_without_restoring_authority(tmp_path: Path) -> None:
    fake = ScriptedFakeLLM(["bad", "bad"])
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(fake)
    )
    repository = _enable(clinic, tmp_path)
    pending = _pending(
        opened, "restart_replay", player_id=player_id,
        revision=clinic.store.load_case_session(opened.session_id).revision,
    )
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    request = contribution(player_id, opened, "restart_completed_replay").model_copy(update={
        "contribution_type": PlayerContributionType.APPROVAL,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })
    first = clinic.submit_player_contribution(request)

    restarted = clinic_at(tmp_path, SimpleActionGameNPCAgent(ScriptedFakeLLM([])))
    restarted.cooperative_history_repository = repository
    restarted.cooperative_record_enabled = True
    restarted.cooperative_context_v2_enabled = True
    replay = restarted.submit_player_contribution(request)

    assert replay == first.model_copy(update={"pending_action": None})
    assert restarted.cooperative_pending == {}


@pytest.mark.parametrize(
    "change",
    (
        {"text": "修改后的文本"},
        {"contribution_type": PlayerContributionType.CHALLENGE},
        {"responds_to_decision_id": "decision_changed"},
        {"pending_confirmation_id": "confirmation_changed"},
    ),
)
def test_completed_pending_response_payload_changes_are_conflicts(
    tmp_path: Path, change: dict[str, object]
) -> None:
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(ScriptedFakeLLM(["bad", "bad"]))
    )
    _enable(clinic, tmp_path)
    pending = _pending(opened, "conflict", player_id=player_id)
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    request = contribution(player_id, opened, "completed_conflict").model_copy(update={
        "contribution_type": PlayerContributionType.REJECTION,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })
    clinic.submit_player_contribution(request)

    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(request.model_copy(update=change))
    assert caught.value.code == "operation_payload_conflict"


def test_new_operation_cannot_use_consumed_pending_and_failed_record_is_terminal(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(ScriptedFakeLLM(["bad", "bad"]))
    )
    repository = _enable(clinic, tmp_path)
    pending = _pending(opened, "consumed", player_id=player_id)
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    original = contribution(player_id, opened, "consume_original").model_copy(update={
        "contribution_type": PlayerContributionType.REJECTION,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })
    clinic.submit_player_contribution(original)
    new_request = original.model_copy(update={"operation_id": "consume_new_operation"})

    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(new_request)
    assert caught.value.code == "confirmation_unavailable"
    record = repository.get(
        player_id, opened.case_id, opened.session_id, new_request.operation_id
    )
    assert record is not None and record.lifecycle == "failed_before_reply"


def test_new_operation_cannot_use_revision_expired_pending(tmp_path: Path) -> None:
    fake = ScriptedFakeLLM([])
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(fake)
    )
    repository = _enable(clinic, tmp_path)
    pending = _pending(
        opened,
        "expired",
        player_id=player_id,
        revision=clinic.store.load_case_session(opened.session_id).revision + 1,
    )
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    request = contribution(player_id, opened, "expired_new_operation").model_copy(update={
        "contribution_type": PlayerContributionType.APPROVAL,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })

    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(request)
    assert caught.value.code == "confirmation_unavailable"
    assert fake.requests == []
    record = repository.get(
        player_id, opened.case_id, opened.session_id, request.operation_id
    )
    assert record is not None and record.lifecycle == "failed_before_reply"


def test_recording_disabled_keeps_original_pending_validation_path(tmp_path: Path) -> None:
    fake = ScriptedFakeLLM(["bad", "bad"])
    clinic, player_id, opened = opened_clinic(
        tmp_path, SimpleActionGameNPCAgent(fake)
    )
    pending = _pending(opened, "legacy", player_id=player_id)
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending
    original = contribution(player_id, opened, "legacy_original").model_copy(update={
        "contribution_type": PlayerContributionType.REJECTION,
        "responds_to_decision_id": pending.decision_id,
        "pending_confirmation_id": pending.confirmation_id,
    })
    clinic.submit_player_contribution(original)

    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(
            original.model_copy(update={"operation_id": "legacy_new_operation"})
        )
    assert caught.value.code == "confirmation_unavailable"
    assert len(fake.requests) == 2


def test_payload_conflict_rejected_and_server_timestamp_is_not_part_of_identity(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    _enable(clinic, tmp_path)
    request = contribution(player_id, opened, "stable_payload")
    clinic.submit_player_contribution(request)
    clinic.submit_player_contribution(request)  # Fixed/server timestamp may differ in production.
    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(request.model_copy(update={"text": "改变文本"}))
    assert caught.value.code == "operation_payload_conflict"


def test_live_duplicate_is_in_progress_and_does_not_mutate_original_lifecycle(tmp_path: Path) -> None:
    entered = Event()
    release = Event()

    class BlockingAgent:
        runtime_kind = DeterministicCooperativeNPC.runtime_kind
        architecture_id = "A0"

        def __init__(self):
            self.delegate = DeterministicCooperativeNPC()

        def decide(self, value):
            entered.set()
            assert release.wait(5)
            return self.delegate.decide(value)

    clinic, player_id, opened = opened_clinic(tmp_path, BlockingAgent())
    repository = _enable(clinic, tmp_path)
    request = contribution(player_id, opened, "live_duplicate")
    errors: list[BaseException] = []

    def run_original():
        try:
            clinic.submit_player_contribution(request)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    thread = Thread(target=run_original)
    thread.start()
    assert entered.wait(5)
    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(request)
    assert caught.value.code == "operation_in_progress"
    record = repository.get(player_id, opened.case_id, opened.session_id, request.operation_id)
    assert record is not None and record.lifecycle in ("started", "prepared")
    release.set()
    thread.join(5)
    assert not errors
    assert repository.get(player_id, opened.case_id, opened.session_id, request.operation_id).lifecycle == "completed"


def test_restart_stale_started_is_conservative_and_does_not_call_agent(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    repository = _enable(clinic, tmp_path)
    request = contribution(player_id, opened, "stale_started")
    stable = {
        "player_id": request.player_id,
        "case_id": request.case_id,
        "session_id": request.session_id,
        "operation_id": request.operation_id,
        "text": request.text,
        "contribution_type": request.contribution_type.value,
        "responds_to_decision_id": None,
        "pending_confirmation_id": None,
    }
    repository.begin(
        player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
        operation_id=request.operation_id, stable_request=stable,
        contribution_json="{}", owner_process_id="old-process",
    )
    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(request)
    assert caught.value.code == "operation_recovery_uncertain"
    assert repository.get(player_id, opened.case_id, opened.session_id, request.operation_id).lifecycle == "recovery_required"


def test_history_is_scope_isolated_and_restart_restores_history_not_pending(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    repository = _enable(clinic, tmp_path)
    clinic.submit_player_contribution(contribution(player_id, opened, "persisted_history"))
    pending = _pending(opened, "restart")
    with clinic._cooperative_pending_lock:
        clinic.cooperative_pending[pending.confirmation_id] = pending

    restarted, _, _ = opened_clinic(tmp_path / "other", DeterministicCooperativeNPC())
    # Reuse the original world store/repository to simulate process recreation.
    restarted.store = clinic.store
    restarted.base_service = clinic.base_service
    restarted.cooperative_history_repository = repository
    restarted.cooperative_record_enabled = True
    restarted.cooperative_context_v2_enabled = True
    assert restarted.cooperative_pending == {}
    fake = ScriptedFakeLLM(["bad", "bad"])
    restarted.game_npc_agent = SimpleActionGameNPCAgent(fake)
    restarted.submit_player_contribution(contribution(player_id, opened, "after_restart"))
    assert "persisted_history" in fake.requests[0].messages[1].content
    assert "confirmation_restart" not in fake.requests[0].messages[-1].content


def test_multiple_pending_are_preserved_and_wrong_scope_or_revision_filtered(tmp_path: Path) -> None:
    clinic, _, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    valid_a = _pending(opened, "a")
    valid_b = _pending(opened, "b")
    stale = _pending(opened, "stale", revision=opened.observation.session_revision + 1)
    other = valid_a.model_copy(update={"confirmation_id": "confirmation_other", "player_id": "other_player"})
    views = project_pending_snapshot(
        (valid_b, stale, other, valid_a),
        player_id=valid_a.player_id,
        case_id=valid_a.case_id,
        session_id=valid_a.session_id,
        case_revision=valid_a.case_revision,
        responds_to_confirmation_id=valid_b.confirmation_id,
        responds_to_decision_id=valid_b.decision_id,
    )
    assert [item.confirmation_id for item in views] == [valid_a.confirmation_id, valid_b.confirmation_id]
    assert [item.responds_to_current_contribution for item in views] == [False, True]


@pytest.mark.parametrize(
    ("confirmation_id", "decision_id", "expected"),
    (
        ("confirmation_b", "decision_b", True),
        ("confirmation_wrong", "decision_b", False),
        ("confirmation_b", "decision_wrong", False),
        (None, "decision_b", False),
        ("confirmation_b", None, False),
    ),
)
def test_pending_response_marker_requires_exact_confirmation_and_decision_pair(
    tmp_path: Path,
    confirmation_id: str | None,
    decision_id: str | None,
    expected: bool,
) -> None:
    _, _, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    pending = _pending(opened, "b")
    views = project_pending_snapshot(
        (pending,),
        player_id=pending.player_id,
        case_id=pending.case_id,
        session_id=pending.session_id,
        case_revision=pending.case_revision,
        responds_to_confirmation_id=confirmation_id,
        responds_to_decision_id=decision_id,
    )
    assert views[0].responds_to_current_contribution is expected


def test_latest_oversized_history_yields_zero_history_with_exact_omission(monkeypatch, tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    repository = _enable(clinic, tmp_path)
    clinic.submit_player_contribution(contribution(player_id, opened, "history_too_large"))
    current_request = contribution(player_id, opened, "current_budget")
    stable = {
        "player_id": current_request.player_id, "case_id": current_request.case_id,
        "session_id": current_request.session_id, "operation_id": current_request.operation_id,
        "text": current_request.text, "contribution_type": current_request.contribution_type.value,
        "responds_to_decision_id": None, "pending_confirmation_id": None,
    }
    current, _ = repository.begin(
        player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
        operation_id=current_request.operation_id, stable_request=stable,
        contribution_json="{}", owner_process_id="test",
    )
    import xuanyi_npc.application.cooperative_context as module
    monkeypatch.setattr(module, "HISTORY_CONTENT_CHARACTER_BUDGET", 1)
    messages, _, omission = module.select_completed_history(repository, current)
    assert messages == ()
    assert omission is not None
    assert omission.omitted_completed_turn_count == 1
    assert omission.reason == "character_budget"
    assert "重述" in omission.public_notice


class _FailCompleteRepository(SQLiteCooperativeHistoryRepository):
    def complete(self, record, result_json):
        raise CooperativeHistoryError("injected completion failure")


def test_tool_success_then_history_completion_failure_never_replays_tool(tmp_path: Path) -> None:
    clinic, player_id, opened = opened_clinic(tmp_path, object())
    repository = _FailCompleteRepository(tmp_path / "failure.sqlite3")
    clinic.cooperative_history_repository = repository
    clinic.cooperative_record_enabled = True
    clinic.cooperative_context_v2_enabled = False
    operation_id = "tool_then_write_failure"
    repaired = _repair_proposal(opened.observation, operation_id, 0)
    fake = ScriptedFakeLLM([repaired.model_dump_json()])
    clinic.game_npc_agent = _RuntimeA1ContractRepairAgent(fake)
    before = clinic.store.load_case_session(opened.session_id)

    with pytest.raises(ClinicError) as caught:
        clinic.submit_player_contribution(contribution(player_id, opened, operation_id))
    after = clinic.store.load_case_session(opened.session_id)
    assert caught.value.code == "operation_recovery_uncertain"
    assert len(after.action_history) == len(before.action_history) + 1
    with pytest.raises(ClinicError) as retry:
        clinic.submit_player_contribution(contribution(player_id, opened, operation_id))
    assert retry.value.code == "operation_recovery_uncertain"
    assert clinic.store.load_case_session(opened.session_id).action_history == after.action_history
    assert len(fake.requests) == 1


def test_versioned_ce2a_request_fixture_matches_all_request_boundaries() -> None:
    def enrich(value):
        return value.model_copy(update={
            "recent_messages": (
                ChatMessage(
                    role=ChatRole.USER,
                    content='{"operation_id":"fixture_history","source":"completed_historical_player_contribution"}',
                ),
                ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content='{"operation_id":"fixture_history","source":"completed_historical_npc_public_reply"}',
                ),
            ),
            "cooperative_context": CooperativeContextSnapshot(
                selected_history_operation_ids=("fixture_history",),
                history_omission=HistoryOmissionView(
                    omitted_completed_turn_count=2,
                    reason="turn_limit",
                    public_notice="有 2 个较早完整回合未注入；依赖其内容时请重述必要信息。",
                ),
            ),
        })

    def identity(request):
        raw = json.dumps(
            _legacy_budget_dump(request), ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        schema = json.dumps(
            request.response_schema, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "roles": [message.role.value for message in request.messages],
            "message_count": len(request.messages),
            "message_content_characters": sum(len(message.content) for message in request.messages),
            "response_schema_sha256": hashlib.sha256(schema).hexdigest(),
            "max_output_tokens": _legacy_budget_dump(request).get("max_output_tokens"),
        }

    a0 = ScriptedFakeLLM(["bad", "bad"])
    GameNPCAgent(a0).decide(enrich(action_input()))
    a1 = ScriptedFakeLLM(["bad", "bad"])
    GameNPCAgent(a1).propose_turn(enrich(planning_input()))
    value = enrich(action_input())
    repair = ScriptedFakeLLM(["bad"])
    agent = GameNPCAgent(repair)
    prior = GameNPCDecision(
        decision_id="decision_fixture",
        turn_id=value.turn_id,
        proposal=agent._fallback_proposal(value),
        llm_attempts=1,
        used_fallback=False,
    )
    agent.repair_action_contract(
        value, prior, build_safe_action_feedback("fixture", value.case_observation)
    )
    actual = {
        "a0_initial": identity(a0.requests[0]),
        "a0_format_repair": identity(a0.requests[1]),
        "a1_initial": identity(a1.requests[0]),
        "a1_format_repair": identity(a1.requests[1]),
        "a1_action_contract_repair_a0_shape": identity(repair.requests[0]),
    }
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_engineering" / "ce2a_requests_v1.json").read_text(encoding="utf-8")
    )
    assert actual == fixture["requests"]


def test_versioned_ce2a_v2_fixture_freezes_exact_pending_response_marker() -> None:
    value = action_input()
    pending = PendingConfirmationContextView(
        confirmation_id="confirmation_fixture",
        decision_id="decision_fixture",
        action=AgentAction(
            action_id="action_fixture",
            action_type=AgentActionType.RESPOND,
            dialogue="等待确认。",
            confidence=0.5,
        ),
        authority_mode=AuthorityMode.CONFIRMATION_REQUIRED,
        public_rationale="固定待确认事项。",
        case_revision=value.case_observation.session_revision,
        responds_to_current_contribution=True,
    )
    value = value.model_copy(update={
        "recent_messages": (
            ChatMessage(
                role=ChatRole.USER,
                content='{"operation_id":"fixture_history","source":"completed_historical_player_contribution"}',
            ),
            ChatMessage(
                role=ChatRole.ASSISTANT,
                content='{"operation_id":"fixture_history","source":"completed_historical_npc_public_reply"}',
            ),
        ),
        "cooperative_context": CooperativeContextSnapshot(
            selected_history_operation_ids=("fixture_history",),
            pending_confirmations=(pending,),
        ),
    })
    fake = ScriptedFakeLLM(["bad", "bad"])
    GameNPCAgent(fake).decide(value)

    def identity(request):
        raw = json.dumps(
            _legacy_budget_dump(request), ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        schema = json.dumps(
            request.response_schema, ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "roles": [message.role.value for message in request.messages],
            "message_count": len(request.messages),
            "message_content_characters": sum(len(message.content) for message in request.messages),
            "response_schema_sha256": hashlib.sha256(schema).hexdigest(),
            "max_output_tokens": _legacy_budget_dump(request).get("max_output_tokens"),
            "responds_to_current_contribution_occurrences": sum(
                message.content.count('"responds_to_current_contribution": true')
                for message in request.messages
            ),
        }

    actual = {
        "a0_initial": identity(fake.requests[0]),
        "a0_format_repair": identity(fake.requests[1]),
    }
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_engineering" / "ce2a_requests_v2.json").read_text(encoding="utf-8")
    )
    assert actual == fixture["requests"]


def _legacy_budget_dump(request):
    """Frozen CE2A data predates explicit repair budgets; only migrate that field."""
    assert request.max_output_tokens == (2048 if request.response_schema.get("title") == "GameNPCTurnProposal" else 512)
    result = request.model_dump(mode="json")
    if type(request).__name__ != "GameNPCPlanningRequest":
        result.pop("max_output_tokens", None)
    return result
