from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from xuanyi_npc.agents import (
    DeepSeekGameplayAuthorization,
    DoctorAgent,
    ScriptedFakeLLM,
    build_authorized_deepseek_v0_agent,
    build_reference_fake_agent,
)
from xuanyi_npc.application import (
    CampaignRuleSet,
    CaseCatalog,
    CreatePlayerInput,
    StartEpisodeInput,
)
from xuanyi_npc.application.gameplay_modes import (
    GameplayMode,
    GameplayModeConfig,
    ModeAwareEpisodeRunner,
    ModeRunInput,
    SemanticShadowMode,
)
from xuanyi_npc.application.semantic_shadow import (
    EmptyMockShadowSearch,
    RecordingSemanticShadowObserver,
    ShadowCandidate,
    ShadowRetrievalStatus,
    ShadowSearchResult,
)
from xuanyi_npc.cli.play import PlayCLI, PlayConfig, create_play_service, main
from xuanyi_npc.domain import CaseSessionStatus
from xuanyi_npc.evaluation import EpisodeStatus
from xuanyi_npc.storage import JsonStateStore


ROOT = Path(__file__).parents[1]
CASE_DIR = ROOT / "data" / "cases"
CAMPAIGN_RULES = ROOT / "data" / "campaign" / "cross_episode_rules_v1.json"
CASE_IDS = ("gray_hearth_inn", "moon_well_echo", "old_paper_umbrella")


class FixedPlayerIds:
    def new_player_id(self) -> str:
        return "player_modes"


class FixedSessionIds:
    def __init__(self) -> None:
        self.number = 0

    def new_session_id(self) -> str:
        self.number += 1
        return f"session_modes_{self.number}"


class FixedClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


def service(root: Path):
    catalog = CaseCatalog(CASE_DIR)
    return create_service(root, catalog)


def create_service(root: Path, catalog: CaseCatalog):
    from xuanyi_npc.application import MultiCaseEpisodeService

    return MultiCaseEpisodeService(
        state_store=JsonStateStore(root),
        case_catalog=catalog,
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        clock=FixedClock(),
        campaign_rules=CampaignRuleSet.load(CAMPAIGN_RULES, catalog),
    )


def start(svc, case_id: str = "old_paper_umbrella"):
    created = svc.create_player(CreatePlayerInput(display_name="离线学徒"))
    opened = svc.start_episode(
        StartEpisodeInput(player_id=created.player_id, case_id=case_id)
    )
    return created.player_id, opened


def run_reference(
    root: Path,
    case_id: str,
    *,
    shadow: bool = False,
    observer=None,
):
    svc = service(root)
    player_id, opened = start(svc, case_id)
    case = svc.case_catalog.get(case_id)
    agent, fake = build_reference_fake_agent(case)
    runner = ModeAwareEpisodeRunner(
        service=svc,
        doctor_agent=agent,
        config=GameplayModeConfig(
            gameplay_mode=GameplayMode.FAKE,
            semantic_shadow_mode=(
                SemanticShadowMode.RECORD_ONLY
                if shadow
                else SemanticShadowMode.OFF
            ),
        ),
        shadow_observer=observer,
    )
    result = runner.run(
        ModeRunInput(
            player_id=player_id,
            case_id=case_id,
            session_id=opened.session_id,
        )
    )
    return svc, result, fake


def test_mode_contract_defaults_and_unknown_values_are_strict() -> None:
    config = GameplayModeConfig()
    assert config.gameplay_mode is GameplayMode.MANUAL
    assert config.semantic_shadow_mode is SemanticShadowMode.OFF
    with pytest.raises(ValidationError):
        GameplayModeConfig(gameplay_mode="agent")
    with pytest.raises(ValidationError):
        GameplayModeConfig(semantic_shadow_mode="inject")
    with pytest.raises(ValidationError):
        GameplayModeConfig(extra_field=True)


def test_mode_modules_import_without_torch_or_file_side_effects(tmp_path: Path) -> None:
    script = (
        "import sys; import xuanyi_npc.cli.play; "
        "assert 'torch' not in sys.modules; assert 'sentence_transformers' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_fake_reference_completes_each_case_through_persisted_service(
    tmp_path: Path,
    case_id: str,
) -> None:
    svc, result, fake = run_reference(tmp_path, case_id)
    episode = result.episode_result
    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.final_session.status is CaseSessionStatus.COMPLETED
    assert episode.final_session.score == 100
    assert [event.sequence for event in episode.events] == list(range(1, 9))
    assert episode.usage is None
    assert fake.remaining_responses == 0
    stored = svc.state_store.load_case_session(episode.episode_id)
    assert stored == episode.final_session
    assert result.public_result.campaign_status.value == "ready"
    assert result.public_result.campaign_event_sequences == (1,)


def test_fake_reference_can_resume_from_committed_event(tmp_path: Path) -> None:
    svc = service(tmp_path)
    player_id, opened = start(svc)
    case = svc.case_catalog.get("old_paper_umbrella")
    full_agent, _ = build_reference_fake_agent(case)
    partial = ModeAwareEpisodeRunner(
        service=svc,
        doctor_agent=full_agent,
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=1),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id=case.case_id,
            session_id=opened.session_id,
        )
    )
    assert partial.episode_result.final_session.revision == 1
    resumed_agent, _ = build_reference_fake_agent(case, completed_event_count=1)
    resumed = ModeAwareEpisodeRunner(
        service=svc,
        doctor_agent=resumed_agent,
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=7),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id=case.case_id,
            session_id=opened.session_id,
        )
    )
    assert resumed.episode_result.status is EpisodeStatus.COMPLETED
    assert [event.sequence for event in resumed.episode_result.events] == list(
        range(2, 9)
    )


def test_fake_campaign_a_projects_knowledge_and_public_history(tmp_path: Path) -> None:
    svc = service(tmp_path)
    created = svc.create_player(CreatePlayerInput(display_name="跨案学徒"))
    player_id = created.player_id
    observed_reactions: list[str] = []
    for case_id in ("old_paper_umbrella", "gray_hearth_inn", "moon_well_echo"):
        opened = svc.start_episode(
            StartEpisodeInput(player_id=player_id, case_id=case_id)
        )
        if opened.history_reaction is not None:
            observed_reactions.append(opened.history_reaction)
        case = svc.case_catalog.get(case_id)
        agent, _ = build_reference_fake_agent(case)
        result = ModeAwareEpisodeRunner(
            service=svc,
            doctor_agent=agent,
            config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE),
        ).run(
            ModeRunInput(
                player_id=player_id,
                case_id=case_id,
                session_id=opened.session_id,
            )
        )
        assert result.episode_result.final_session.score == 100
    campaign = svc.state_store.load_campaign(player_id)
    assert tuple(event.sequence for event in campaign.event_history) == (1, 2, 3)
    assert campaign.unlocked_knowledge_ids == {
        "contract_provenance_check",
        "handoff_sequence_check",
    }
    assert len(observed_reactions) == 3
    assert "旧纸伞案" in observed_reactions[1]
    assert "灰灶案" in observed_reactions[2]


def test_format_repair_and_rule_rejection_remain_bounded(tmp_path: Path) -> None:
    svc = service(tmp_path)
    player_id, opened = start(svc)
    repaired = json.dumps(
        {
            "action_id": "agent_step_001",
            "action_type": "use_tool",
            "dialogue": "过早提交公开候选。",
            "tool_call": {
                "name": "submit_diagnosis",
                "arguments": {
                    "diagnosis_id": "rain_vow_breach",
                    "evidence_clue_ids": [],
                },
            },
            "confidence": 0.5,
        },
        ensure_ascii=False,
    )
    fake = ScriptedFakeLLM(("not-json", repaired))
    result = ModeAwareEpisodeRunner(
        service=svc,
        doctor_agent=DoctorAgent(fake),
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=1),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=opened.session_id,
        )
    )
    step = result.episode_result.steps[0]
    assert step.llm_attempts == 2
    assert step.accepted is False
    assert step.error_code == "diagnosis_not_ready"
    assert result.episode_result.events == ()
    assert result.episode_result.final_session.revision == 0


def test_deterministic_fallback_stops_at_max_steps_without_state_pollution(
    tmp_path: Path,
) -> None:
    svc = service(tmp_path)
    player_id, opened = start(svc)
    fake = ScriptedFakeLLM(("bad", "bad", "bad", "bad"))
    result = ModeAwareEpisodeRunner(
        service=svc,
        doctor_agent=DoctorAgent(fake),
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=2),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=opened.session_id,
        )
    )
    assert result.episode_result.status is EpisodeStatus.MAX_STEPS_REACHED
    assert all(step.used_fallback for step in result.episode_result.steps)
    assert all(step.error_code == "unsupported_action" for step in result.episode_result.steps)
    assert result.episode_result.events == ()
    assert result.episode_result.final_session.revision == 0


def test_shadow_on_and_off_leave_requests_actions_state_and_campaign_identical(
    tmp_path: Path,
) -> None:
    off_root = tmp_path / "off"
    on_root = tmp_path / "on"
    log = tmp_path / "results" / "shadow.jsonl"
    observer = RecordingSemanticShadowObserver(EmptyMockShadowSearch(), log)
    _, off, off_fake = run_reference(off_root, "old_paper_umbrella")
    _, on, on_fake = run_reference(
        on_root,
        "old_paper_umbrella",
        shadow=True,
        observer=observer,
    )
    assert [request.model_dump_json() for request in off_fake.requests] == [
        request.model_dump_json() for request in on_fake.requests
    ]
    assert [step.action for step in off.episode_result.steps] == [
        step.action for step in on.episode_result.steps
    ]
    assert off.episode_result.events == on.episode_result.events
    assert off.episode_result.final_session == on.episode_result.final_session
    assert off.public_result.campaign_view == on.public_result.campaign_view
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 8
    assert all(record["injected_into_prompt"] is False for record in records)
    assert all(record["affected_action"] is False for record in records)
    assert all(record["affected_state"] is False for record in records)
    serialized = log.read_text(encoding="utf-8")
    assert "root_cause" not in serialized
    assert "valid_diagnosis_ids" not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized


class FailingShadow:
    def search(self, query):
        del query
        raise RuntimeError("private backend detail")


def test_shadow_failure_does_not_change_official_episode(tmp_path: Path) -> None:
    off_root = tmp_path / "off"
    failed_root = tmp_path / "failed"
    observer = RecordingSemanticShadowObserver(
        FailingShadow(), tmp_path / "results" / "failure.jsonl"
    )
    _, off, _ = run_reference(off_root, "gray_hearth_inn")
    _, failed, _ = run_reference(
        failed_root,
        "gray_hearth_inn",
        shadow=True,
        observer=observer,
    )
    assert off.episode_result.events == failed.episode_result.events
    assert off.episode_result.final_session == failed.episode_result.final_session
    assert all(
        item.status is ShadowRetrievalStatus.UNAVAILABLE
        for item in failed.shadow_observations
    )
    assert "private backend detail" not in (
        tmp_path / "results" / "failure.jsonl"
    ).read_text(encoding="utf-8")


class CrossPlayerShadow:
    def search(self, query):
        return ShadowSearchResult(
            status=ShadowRetrievalStatus.READY,
            embedding_space_id="mock_space",
            candidates=(
                ShadowCandidate(
                    player_id="player_other",
                    source_session_id="session_other",
                    memory_id="memory_other",
                    similarity=0.99,
                ),
                ShadowCandidate(
                    player_id=query.player_id,
                    source_session_id=query.source_session_id,
                    memory_id="memory_current",
                    similarity=0.98,
                ),
            ),
        )


def test_shadow_filters_other_player_and_current_episode(tmp_path: Path) -> None:
    log = tmp_path / "results" / "safety.jsonl"
    observer = RecordingSemanticShadowObserver(CrossPlayerShadow(), log)
    _, result, _ = run_reference(
        tmp_path / "state",
        "moon_well_echo",
        shadow=True,
        observer=observer,
    )
    assert all(item.eligible_candidate_count == 0 for item in result.shadow_observations)
    assert all(
        item.status is ShadowRetrievalStatus.SAFETY_ERROR
        for item in result.shadow_observations
    )
    text = log.read_text(encoding="utf-8")
    assert "player_other" not in text
    assert "memory_other" not in text
    assert '"current_episode_excluded":true' in text


def test_shadow_off_does_not_create_files_or_call_backend(tmp_path: Path) -> None:
    backend = EmptyMockShadowSearch()
    run_reference(tmp_path / "state", "old_paper_umbrella")
    assert backend.calls == 0
    assert not (tmp_path / "state" / "shadow").exists()


def test_shadow_off_rejects_an_initialized_observer(tmp_path: Path) -> None:
    svc = service(tmp_path / "state")
    case = svc.case_catalog.get("old_paper_umbrella")
    agent, _ = build_reference_fake_agent(case)
    observer = RecordingSemanticShadowObserver(
        EmptyMockShadowSearch(), tmp_path / "results" / "unexpected.jsonl"
    )
    with pytest.raises(ValueError):
        ModeAwareEpisodeRunner(
            service=svc,
            doctor_agent=agent,
            config=GameplayModeConfig(
                gameplay_mode=GameplayMode.FAKE,
                semantic_shadow_mode=SemanticShadowMode.OFF,
            ),
            shadow_observer=observer,
        )
    assert not (tmp_path / "results").exists()


def model_handler(captured: list[bytes]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "deepseek-v4-flash"}]},
            )
        captured.append(request.content)
        content = json.dumps(
            {
                "action_id": "agent_step_001",
                "action_type": "use_tool",
                "dialogue": "只使用公开选项。",
                "tool_call": {
                    "name": "observe_patient",
                    "arguments": {"investigation_id": "unknown_public_option"},
                },
                "confidence": 0.5,
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={
                "id": "request_modes",
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "model": "deepseek-v4-flash",
                "system_fingerprint": "fp_modes",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 100,
                },
            },
        )

    return handler


def run_deepseek_mock_once(tmp_path: Path, *, shadow: bool) -> bytes:
    state_root = tmp_path / "state"
    result_dir = tmp_path / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    captured: list[bytes] = []
    client = httpx.Client(transport=httpx.MockTransport(model_handler(captured)))
    auth = DeepSeekGameplayAuthorization(
        confirm_paid=True,
        max_cost_cny=Decimal("0.03"),
        results_dir=result_dir,
    )
    agent, adapter, discovery = build_authorized_deepseek_v0_agent(
        auth,
        environ={"DEEPSEEK_API_KEY": "placeholder", "DEEPSEEK_BASE_URL": "https://api.deepseek.test"},
        client=client,
    )
    assert discovery.configured_model_available
    svc = service(state_root)
    player_id, opened = start(svc)
    observer = (
        RecordingSemanticShadowObserver(
            EmptyMockShadowSearch(), result_dir / "deepseek_shadow.jsonl"
        )
        if shadow
        else None
    )
    ModeAwareEpisodeRunner(
        service=svc,
        doctor_agent=agent,
        config=GameplayModeConfig(
            gameplay_mode=GameplayMode.DEEPSEEK_V0,
            semantic_shadow_mode=(SemanticShadowMode.RECORD_ONLY if shadow else SemanticShadowMode.OFF),
            max_steps=1,
        ),
        shadow_observer=observer,
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id="old_paper_umbrella",
            session_id=opened.session_id,
        )
    )
    adapter.close()
    assert len(captured) == 1
    return captured[0]


@pytest.mark.parametrize("shadow", [False, True])
def test_deepseek_mock_request_never_contains_semantic_memory(
    tmp_path: Path,
    shadow: bool,
) -> None:
    body = run_deepseek_mock_once(tmp_path, shadow=shadow).decode("utf-8")
    assert "retrieved_memories" not in body
    assert "similarity" not in body
    assert "CampaignFact" not in body
    assert "memory_id" not in body


def test_deepseek_shadow_off_and_on_requests_are_byte_identical(
    tmp_path: Path,
) -> None:
    off = run_deepseek_mock_once(tmp_path / "off", shadow=False)
    on = run_deepseek_mock_once(tmp_path / "on", shadow=True)
    assert off == on


def test_deepseek_missing_paid_gates_stop_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    calls = 0

    def forbidden_send(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(httpx.Client, "send", forbidden_send)
    exit_code = main(
        (
            "--case-dir",
            str(CASE_DIR),
            "--state-dir",
            str(state_dir),
            "--mode",
            "deepseek-v0",
        )
    )
    assert exit_code == 2
    assert calls == 0


def test_manual_rejects_deepseek_only_flags_before_network(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    exit_code = main(
        (
            "--case-dir",
            str(CASE_DIR),
            "--state-dir",
            str(state_dir),
            "--mode",
            "manual",
            "--confirm-paid-agent",
            "--max-cost-cny",
            "0.03",
            "--results-dir",
            str(result_dir),
        )
    )
    assert exit_code == 2


def test_manual_cli_initializes_no_agent_or_shadow_file(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = PlayConfig.load(case_dir=CASE_DIR, state_dir=state_dir)
    cli = PlayCLI(
        create_play_service(config),
        config=config,
        input_fn=lambda _: "0",
    )
    assert cli.run() == 0
    assert not (state_dir / "shadow").exists()


def test_fake_cli_displays_each_public_step_and_result(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = PlayConfig.load(
        case_dir=CASE_DIR,
        state_dir=state_dir,
        gameplay_mode=GameplayMode.FAKE,
    )
    answers = iter(("1", "录屏学徒", "1", "1", "99"))
    stdout = StringIO()
    cli = PlayCLI(
        create_play_service(config),
        config=config,
        input_fn=lambda _: next(answers),
        stdout=stdout,
    )
    assert cli.run() == 0
    output = stdout.getvalue()
    assert "行动模式：fake（离线演示 Agent）" in output
    assert "第 1 步" in output
    assert "第 8 步" in output
    assert "结局：resolved" in output
    assert "得分：100" in output
    assert "API Key" in output
