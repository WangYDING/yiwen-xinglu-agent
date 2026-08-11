from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from xuanyi_npc.application import (
    ApprenticeshipPlayerInput,
    FinishEpisodeInput,
    SubmitActionInput,
    StartEpisodeInput,
)
from xuanyi_npc.domain import CampaignState
from xuanyi_npc.storage import JsonStateStore, StorageError

from tests.r1_helpers import (
    ROOT,
    action,
    build_service,
    complete_case,
    create_player,
)
from xuanyi_npc.domain import ToolName


class FailingCampaignStore(JsonStateStore):
    fail_campaign = False

    def save_campaign(self, state: CampaignState) -> Path:
        if self.fail_campaign:
            raise StorageError("injected campaign failure")
        return super().save_campaign(state)


class FailingApprenticeshipStore(JsonStateStore):
    fail_apprenticeship = False

    def save_apprenticeship(self, state):  # type: ignore[override]
        if self.fail_apprenticeship:
            raise StorageError("injected apprenticeship failure")
        return super().save_apprenticeship(state)


class FailingSessionStore(JsonStateStore):
    fail_session = False

    def save_case_session(self, state):  # type: ignore[override]
        if self.fail_session:
            raise StorageError("injected session failure")
        return super().save_case_session(state)


def apprenticeship_bytes(root: Path, player_id: str) -> bytes:
    return (root / "apprenticeships" / f"{player_id}.json").read_bytes()


def test_duplicate_finish_and_reconcile_are_byte_identical(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    session_id, _ = complete_case(service, player_id, "old_paper_umbrella")
    before = apprenticeship_bytes(tmp_path, player_id)
    revision = store.load_apprenticeship(player_id).revision

    finished = service.finish_episode(FinishEpisodeInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=session_id,
    ))
    reconciled = service.reconcile_apprenticeship(
        ApprenticeshipPlayerInput(player_id=player_id)
    )
    second = service.reconcile_apprenticeship(
        ApprenticeshipPlayerInput(player_id=player_id)
    )

    assert finished.ok and not finished.ability_changes
    assert reconciled.ok and second.ok
    assert store.load_apprenticeship(player_id).revision == revision
    assert apprenticeship_bytes(tmp_path, player_id) == before


def test_case_save_failure_writes_neither_campaign_nor_growth(tmp_path) -> None:
    store = FailingSessionStore(tmp_path)
    service, _ = build_service(tmp_path, store=store)
    player_id = create_player(service)
    opened = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="old_paper_umbrella")
    )
    assert opened.ok
    before = apprenticeship_bytes(tmp_path, player_id)
    store.fail_session = True
    rejected = service.submit_action(SubmitActionInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=opened.session_id,
        action=action(ToolName.OBSERVE_PATIENT, {"investigation_id": "observe_scholar"}, 1),
    ))

    assert not rejected.ok
    assert store.list_campaigns() == ()
    assert apprenticeship_bytes(tmp_path, player_id) == before


def test_rule_rejections_do_not_change_apprenticeship_bytes(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    opened = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="old_paper_umbrella")
    )
    assert opened.ok and opened.session_id is not None
    before = apprenticeship_bytes(tmp_path, player_id)
    revision = store.load_apprenticeship(player_id).revision

    unknown = service.submit_action(SubmitActionInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=opened.session_id,
        action=action(ToolName.OBSERVE_PATIENT, {"investigation_id": "unknown_probe"}, 1),
    ))
    early = service.submit_action(SubmitActionInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=opened.session_id,
        action=action(
            ToolName.SUBMIT_DIAGNOSIS,
            {"diagnosis_id": "rain_vow_breach", "evidence_clue_ids": []},
            2,
        ),
    ))
    accepted = service.submit_action(SubmitActionInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=opened.session_id,
        action=action(ToolName.OBSERVE_PATIENT, {"investigation_id": "observe_scholar"}, 3),
    ))
    after_accepted = apprenticeship_bytes(tmp_path, player_id)
    repeated = service.submit_action(SubmitActionInput(
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=opened.session_id,
        action=action(ToolName.OBSERVE_PATIENT, {"investigation_id": "observe_scholar"}, 4),
    ))

    assert not unknown.ok and not early.ok and accepted.ok and not repeated.ok
    assert store.load_apprenticeship(player_id).revision == revision
    assert before == after_accepted == apprenticeship_bytes(tmp_path, player_id)


def test_campaign_failure_prevents_apprenticeship_projection(tmp_path) -> None:
    store = FailingCampaignStore(tmp_path)
    service, _ = build_service(tmp_path, store=store)
    player_id = create_player(service)
    before = apprenticeship_bytes(tmp_path, player_id)
    store.fail_campaign = True

    _, result = complete_case(service, player_id, "old_paper_umbrella")

    assert result.ok
    assert result.campaign_status.value == "pending"
    assert result.apprenticeship_status is None
    assert apprenticeship_bytes(tmp_path, player_id) == before


def test_apprenticeship_failure_is_pending_and_reconcile_recovers(tmp_path) -> None:
    store = FailingApprenticeshipStore(tmp_path)
    service, _ = build_service(tmp_path, store=store)
    player_id = create_player(service)
    before = apprenticeship_bytes(tmp_path, player_id)
    store.fail_apprenticeship = True

    session_id, result = complete_case(service, player_id, "old_paper_umbrella")

    assert result.ok
    assert result.campaign_status.value == "ready"
    assert result.apprenticeship_status.value == "pending"
    assert result.apprenticeship_error_code == "apprenticeship_projection_pending"
    assert apprenticeship_bytes(tmp_path, player_id) == before
    assert store.load_campaign(player_id).revision == 1
    assert store.load_case_session(session_id).status.value == "completed"

    store.fail_apprenticeship = False
    recovered = service.reconcile_apprenticeship(
        ApprenticeshipPlayerInput(player_id=player_id)
    )
    stable = service.reconcile_apprenticeship(
        ApprenticeshipPlayerInput(player_id=player_id)
    )
    assert recovered.ok and recovered.apprenticeship_status.value == "ready"
    assert store.load_apprenticeship(player_id).completed_source_sessions == (session_id,)
    assert stable.ok and not stable.ability_changes


def test_cross_player_finish_and_source_tamper_write_nothing(tmp_path) -> None:
    service, store = build_service(tmp_path)
    owner = create_player(service, "来源玩家")
    other = create_player(service, "其他玩家")
    session_id, _ = complete_case(service, owner, "old_paper_umbrella")
    owner_before = apprenticeship_bytes(tmp_path, owner)
    other_before = apprenticeship_bytes(tmp_path, other)

    rejected = service.finish_episode(FinishEpisodeInput(
        player_id=other,
        case_id="old_paper_umbrella",
        session_id=session_id,
    ))
    assert not rejected.ok and rejected.error_code == "session_player_mismatch"
    assert apprenticeship_bytes(tmp_path, owner) == owner_before
    assert apprenticeship_bytes(tmp_path, other) == other_before

    session_path = tmp_path / "case_sessions" / f"{session_id}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["action_history"][0]["occurred_at"] = "2026-08-11T09:00:00Z"
    session_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    pending = service.finish_episode(FinishEpisodeInput(
        player_id=owner,
        case_id="old_paper_umbrella",
        session_id=session_id,
    ))
    assert pending.ok
    assert pending.apprenticeship_status.value == "pending"
    assert apprenticeship_bytes(tmp_path, owner) == owner_before


def test_two_process_reconcile_recovers_committed_growth(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    script = r'''
import sys
from pathlib import Path
from tests.r1_helpers import build_service, complete_case, create_player
from xuanyi_npc.application import ApprenticeshipPlayerInput
from xuanyi_npc.storage import JsonStateStore, StorageError
class Store(JsonStateStore):
    fail = False
    def save_apprenticeship(self, state):
        if self.fail: raise StorageError("injected")
        return super().save_apprenticeship(state)
root=Path(sys.argv[2]); mode=sys.argv[3]
if mode == "complete":
    store=Store(root); service,_=build_service(root,store=store); player=create_player(service); store.fail=True
    session,result=complete_case(service,player,"old_paper_umbrella")
    assert result.apprenticeship_status.value == "pending"
    print(player,session)
else:
    service,store=build_service(root,store=JsonStateStore(root)); player=sys.argv[4]
    result=service.reconcile_apprenticeship(ApprenticeshipPlayerInput(player_id=player))
    assert result.ok and result.apprenticeship_status.value == "ready"
    print(store.load_apprenticeship(player).completed_source_sessions[0])
'''
    env = {key: value for key, value in os.environ.items() if key not in {
        "DEEPSEEK_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"
    }}
    env["PYTHONPATH"] = str(ROOT / "src")
    first = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(state_dir), "complete"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert first.returncode == 0, first.stderr
    player_id, session_id = first.stdout.strip().split()
    second = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), str(state_dir), "reconcile", player_id],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == session_id
