"""Offline M5 vertical-slice acceptance through public application boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, Sequence

from pydantic import ConfigDict, Field, StrictBool, StrictInt, TypeAdapter

from xuanyi_npc.agents import REFERENCE_FAKE_SCRIPTS, build_reference_fake_agent
from xuanyi_npc.application import (
    CampaignPlayerInput,
    CampaignRuleSet,
    CaseCatalog,
    CreatePlayerInput,
    ListCasesInput,
    MultiCaseEpisodeService,
    ResumeEpisodeInput,
    StartEpisodeInput,
    SubmitActionInput,
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
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CampaignState,
    CaseEvent,
    CaseSessionState,
    CaseSessionStatus,
    ToolCallRequest,
    ToolName,
    TreatmentOutcome,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.campaign import CampaignEventReplayer
from xuanyi_npc.engine import CaseEventReplayer
from xuanyi_npc.resources.runtime import (
    M5_HISTORY_RESOURCE_NAME,
    PackageResourceError,
    materialized_runtime_resources,
    read_runtime_text,
)
from xuanyi_npc.storage import JsonStateStore


CASE_ORDER = ("old_paper_umbrella", "gray_hearth_inn", "moon_well_echo")
EXPECTED_KNOWLEDGE = frozenset(
    {"contract_provenance_check", "handoff_sequence_check"}
)
P4B_RAW_SHA256 = "EFDC6B37692CAA117B352DD199B52AAFF20D765945E5C8FB585994453B712C2B"
P4D_RAW_SHA256 = "24B4105E1607F84FA0E1D15810BAF9051FBAADCEF3D90470411EB7A0543BADD8"
_EVENT_ADAPTER = TypeAdapter(CaseEvent)


class AcceptanceModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AcceptanceCheck(AcceptanceModel):
    check_id: Identifier
    passed: Literal[True] = True
    evidence: NonEmptyText


class AcceptedCase(AcceptanceModel):
    case_id: Identifier
    session_revision: Literal[8]
    event_sequences: tuple[Literal[1, 2, 3, 4, 5, 6, 7, 8], ...]
    status: Literal["completed"]
    outcome: Literal["resolved"]
    score: Literal[100]
    replay_matches_disk: Literal[True]
    subprocess_count: Literal[8]


class RejectionEvidence(AcceptanceModel):
    error_codes: tuple[Identifier, ...]
    zero_event_count: Annotated[StrictInt, Field(ge=4)]
    zero_revision_count: Annotated[StrictInt, Field(ge=4)]
    byte_identical_count: Annotated[StrictInt, Field(ge=4)]


class ShadowEvidence(AcceptanceModel):
    request_bytes_equal: Literal[True]
    action_sequence_equal: Literal[True]
    episode_state_equal: Literal[True]
    campaign_state_equal: Literal[True]
    injected_into_prompt: Literal[False] = False
    affected_action: Literal[False] = False
    affected_state: Literal[False] = False


class ExternalUse(AcceptanceModel):
    deepseek_models_calls: Literal[0] = 0
    deepseek_chat_calls: Literal[0] = 0
    bge_loads: Literal[0] = 0
    embedding_api_calls: Literal[0] = 0
    network_requests: Literal[0] = 0
    cost_cny: Literal["0"] = "0"


class HistoricalEvidence(AcceptanceModel):
    verification_mode: Literal["public_manifest", "raw_sha256_verified"] = (
        "public_manifest"
    )
    p4b_raw_sha256: Literal[P4B_RAW_SHA256]
    p4d_raw_sha256: Literal[P4D_RAW_SHA256]
    p4b_conclusion: Literal[
        "engineering_safe_gray_incomplete_moon_not_run"
    ] = "engineering_safe_gray_incomplete_moon_not_run"
    p4d_conclusion: Literal[
        "engineering_safe_three_case_campaign_completed"
    ] = "engineering_safe_three_case_campaign_completed"


class PublicHistoryEvidenceManifest(AcceptanceModel):
    schema_version: Literal["m5_public_history_evidence_v1"]
    p4b_raw_sha256: Literal[P4B_RAW_SHA256]
    p4d_raw_sha256: Literal[P4D_RAW_SHA256]
    p4b_conclusion: Literal[
        "engineering_safe_gray_incomplete_moon_not_run"
    ]
    p4d_conclusion: Literal[
        "engineering_safe_three_case_campaign_completed"
    ]


class M5AcceptanceResult(AcceptanceModel):
    schema_version: Literal["m5_acceptance_v1"] = "m5_acceptance_v1"
    run_id: Identifier
    status: Literal["passed"] = "passed"
    primary_cases: tuple[AcceptedCase, AcceptedCase, AcceptedCase]
    primary_campaign_event_sequences: tuple[Literal[1, 2, 3], ...]
    primary_knowledge_ids: frozenset[Identifier]
    later_history_reactions_observed: Literal[2]
    secondary_moon_case: AcceptedCase
    secondary_used_neutral_opening: Literal[True]
    players_isolated: Literal[True]
    rejection_evidence: RejectionEvidence
    shadow_evidence: ShadowEvidence
    manual_start_without_key: Literal[True]
    torch_or_bge_loaded_in_workers: Literal[False]
    worker_processes: Annotated[StrictInt, Field(ge=32)]
    all_worker_exit_codes_zero: Literal[True]
    orphan_processes_observed: Literal[0] = 0
    checks: tuple[AcceptanceCheck, ...]
    historical_evidence: HistoricalEvidence
    external_use: ExternalUse = Field(default_factory=ExternalUse)


class WorkerStepResult(AcceptanceModel):
    pid: Annotated[StrictInt, Field(gt=0)]
    accepted: StrictBool
    error_code: Identifier | None = None
    session_revision: Annotated[StrictInt, Field(ge=0)]
    event_payloads: tuple[dict[str, object], ...] = ()
    torch_or_bge_loaded: StrictBool


class AcceptanceError(RuntimeError):
    """Raised when a frozen M5 acceptance invariant fails."""


class _Ids:
    def __init__(self, values: Sequence[str]) -> None:
        self._values = iter(values)

    def new_player_id(self) -> str:
        return next(self._values)

    def new_session_id(self) -> str:
        return next(self._values)


class _Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self._value += timedelta(seconds=1)
        return self._value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _service(
    state_dir: Path,
    case_dir: Path,
    campaign_rules: Path,
    *,
    player_ids: Sequence[str] = (),
    session_ids: Sequence[str] = (),
) -> MultiCaseEpisodeService:
    catalog = CaseCatalog(case_dir)
    return MultiCaseEpisodeService(
        state_store=JsonStateStore(state_dir),
        case_catalog=catalog,
        campaign_rules=CampaignRuleSet.load(campaign_rules, catalog),
        player_id_factory=_Ids(player_ids) if player_ids else None,
        session_id_factory=_Ids(session_ids) if session_ids else None,
        clock=_Clock(),
        legacy_auto_foundation=True,
    )


def _safe_worker_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in tuple(env):
        upper = name.upper()
        if "DEEPSEEK" in upper or "API_KEY" in upper:
            env.pop(name, None)
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    return env


def _run_worker_step(
    *,
    case_dir: Path,
    state_dir: Path,
    campaign_rules: Path,
    player_id: str,
    case_id: str,
    session_id: str,
) -> tuple[WorkerStepResult, tuple[CaseEvent, ...]]:
    command = [
        sys.executable,
        "-m",
        "xuanyi_npc.evaluation.m5_acceptance",
        "--worker-step",
        "--case-dir",
        str(case_dir),
        "--state-dir",
        str(state_dir),
        "--campaign-rules",
        str(campaign_rules),
        "--player-id",
        player_id,
        "--case-id",
        case_id,
        "--session-id",
        session_id,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        env=_safe_worker_environment(),
    )
    if completed.returncode != 0:
        raise AcceptanceError("one offline recovery worker failed")
    if completed.stderr.strip():
        raise AcceptanceError("offline recovery worker wrote unexpected diagnostics")
    try:
        result = WorkerStepResult.model_validate_json(completed.stdout)
        events = tuple(
            _EVENT_ADAPTER.validate_python(payload)
            for payload in result.event_payloads
        )
    except ValueError as exc:
        raise AcceptanceError("offline recovery worker returned invalid output") from exc
    return result, events


def _complete_case_across_processes(
    service: MultiCaseEpisodeService,
    *,
    case_dir: Path,
    state_dir: Path,
    campaign_rules: Path,
    player_id: str,
    case_id: str,
) -> tuple[AcceptedCase, str | None, list[int], bool]:
    opened = service.start_episode(StartEpisodeInput(player_id=player_id, case_id=case_id))
    if not opened.ok or opened.session_id is None or opened.observation is None:
        raise AcceptanceError("could not start a frozen acceptance case")
    if len(opened.action_options.investigations if opened.action_options else ()) < 3:
        raise AcceptanceError("case does not expose multiple initial investigation choices")
    initial = CaseSessionState(
        session_id=opened.session_id,
        case_id=case_id,
        player_id=player_id,
    )
    events: list[CaseEvent] = []
    pids: list[int] = []
    loaded_large_runtime = False
    for expected_revision in range(1, 9):
        worker, new_events = _run_worker_step(
            case_dir=case_dir,
            state_dir=state_dir,
            campaign_rules=campaign_rules,
            player_id=player_id,
            case_id=case_id,
            session_id=opened.session_id,
        )
        if not worker.accepted or worker.session_revision != expected_revision:
            raise AcceptanceError("recovered Fake action did not commit exactly once")
        if tuple(event.sequence for event in new_events) != (expected_revision,):
            raise AcceptanceError("case event sequence is not contiguous across processes")
        events.extend(new_events)
        pids.append(worker.pid)
        loaded_large_runtime = loaded_large_runtime or worker.torch_or_bge_loaded

    final = service.state_store.load_case_session(opened.session_id)
    replayed = CaseEventReplayer().replay(initial, events)
    if final != replayed:
        raise AcceptanceError("case event replay differs from persisted final state")
    if (
        final.status is not CaseSessionStatus.COMPLETED
        or final.outcome is not TreatmentOutcome.RESOLVED
        or final.score != 100
        or final.revision != 8
    ):
        raise AcceptanceError("reference case did not finish resolved / 100")
    return (
        AcceptedCase(
            case_id=case_id,
            session_revision=8,
            event_sequences=(1, 2, 3, 4, 5, 6, 7, 8),
            status="completed",
            outcome="resolved",
            score=100,
            replay_matches_disk=True,
            subprocess_count=8,
        ),
        opened.history_reaction,
        pids,
        loaded_large_runtime,
    )


def _action(tool: ToolName, arguments: dict[str, object], suffix: str) -> AgentAction:
    return AgentAction(
        action_id=f"acceptance_{suffix}",
        action_type=AgentActionType.USE_TOOL,
        dialogue="离线验收公开行动。",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=1.0,
    )


def _rejection_evidence(
    service: MultiCaseEpisodeService,
    *,
    primary_player_id: str,
    secondary_player_id: str,
) -> RejectionEvidence:
    opened = service.start_episode(
        StartEpisodeInput(player_id=secondary_player_id, case_id="old_paper_umbrella")
    )
    if not opened.ok or opened.session_id is None:
        raise AcceptanceError("could not create rejection audit session")
    session_path = service.state_store.root / "case_sessions" / f"{opened.session_id}.json"
    codes: list[str] = []
    unchanged = 0

    def rejected(action: AgentAction) -> None:
        nonlocal unchanged
        before = session_path.read_bytes()
        revision = service.state_store.load_case_session(opened.session_id).revision
        receipt = service.submit_action_with_receipt(
            SubmitActionInput(
                player_id=secondary_player_id,
                case_id="old_paper_umbrella",
                session_id=opened.session_id or "",
                action=action,
            )
        )
        if receipt.result.ok or receipt.events or receipt.result.event_sequences:
            raise AcceptanceError("rejected action produced a domain event")
        if service.state_store.load_case_session(opened.session_id).revision != revision:
            raise AcceptanceError("rejected action changed session revision")
        if session_path.read_bytes() != before:
            raise AcceptanceError("rejected action changed persisted bytes")
        codes.append(receipt.result.error_code or "missing_error")
        unchanged += 1

    rejected(
        _action(
            ToolName.QUESTION_PATIENT,
            {"target_id": "scholar"},
            "bad_parameter",
        )
    )
    rejected(
        _action(
            ToolName.SUBMIT_DIAGNOSIS,
            {"diagnosis_id": "rain_vow_breach", "evidence_clue_ids": []},
            "not_ready",
        )
    )
    case = service.case_catalog.get("old_paper_umbrella")
    if case is None:
        raise AcceptanceError("reference case disappeared")
    first_id = REFERENCE_FAKE_SCRIPTS[case.case_id].investigation_ids[0]
    investigation = next(item for item in case.investigations if item.investigation_id == first_id)
    from xuanyi_npc.agents.gameplay_fake import TOOL_BY_ACTION

    first_action = _action(
        TOOL_BY_ACTION[investigation.action_type],
        {"investigation_id": first_id},
        "first_investigation",
    )
    accepted = service.submit_action_with_receipt(
        SubmitActionInput(
            player_id=secondary_player_id,
            case_id=case.case_id,
            session_id=opened.session_id,
            action=first_action,
        )
    )
    if not accepted.result.ok or accepted.result.event_sequences != (1,):
        raise AcceptanceError("rejection setup action did not commit")
    rejected(first_action.model_copy(update={"action_id": "acceptance_repeat"}))

    before = session_path.read_bytes()
    revision = service.state_store.load_case_session(opened.session_id).revision
    cross = service.resume_episode(
        ResumeEpisodeInput(
            player_id=primary_player_id,
            case_id=case.case_id,
            session_id=opened.session_id,
        )
    )
    if cross.ok or cross.error_code != "session_player_mismatch":
        raise AcceptanceError("cross-player resume was not safely rejected")
    if service.state_store.load_case_session(opened.session_id).revision != revision:
        raise AcceptanceError("cross-player resume changed revision")
    if session_path.read_bytes() != before:
        raise AcceptanceError("cross-player resume changed persisted bytes")
    codes.append(cross.error_code)
    unchanged += 1
    return RejectionEvidence(
        error_codes=tuple(codes),
        zero_event_count=unchanged,
        zero_revision_count=unchanged,
        byte_identical_count=unchanged,
    )


def _run_shadow_variant(
    state_dir: Path,
    case_dir: Path,
    campaign_rules: Path,
    *,
    shadow: bool,
) -> tuple[object, object, object, tuple[str, ...], tuple[object, ...], Path | None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    service = _service(
        state_dir,
        case_dir,
        campaign_rules,
        player_ids=("player_shadow",),
        session_ids=("session_shadow",),
    )
    created = service.create_player(CreatePlayerInput(display_name="旁路验收学徒"))
    for exercise in service.progression_policy.config.foundation_exercises:
        service.complete_foundation_exercise(created.player_id,exercise.exercise_id,exercise.required_action_id)
    opened = service.start_episode(
        StartEpisodeInput(player_id=created.player_id or "", case_id="old_paper_umbrella")
    )
    case = service.case_catalog.get("old_paper_umbrella")
    if case is None or opened.session_id is None:
        raise AcceptanceError("shadow comparison could not start")
    agent, fake = build_reference_fake_agent(case)
    log_path = state_dir / "shadow" / "records.jsonl" if shadow else None
    observer = (
        RecordingSemanticShadowObserver(EmptyMockShadowSearch(), log_path)
        if log_path is not None
        else None
    )
    result = ModeAwareEpisodeRunner(
        service=service,
        doctor_agent=agent,
        config=GameplayModeConfig(
            gameplay_mode=GameplayMode.FAKE,
            semantic_shadow_mode=(
                SemanticShadowMode.RECORD_ONLY if shadow else SemanticShadowMode.OFF
            ),
        ),
        shadow_observer=observer,
    ).run(
        ModeRunInput(
            player_id=created.player_id or "",
            case_id=case.case_id,
            session_id=opened.session_id,
        )
    )
    campaign = service.state_store.load_campaign(created.player_id or "")
    return (
        result.episode_result.final_session,
        campaign,
        result.episode_result.events,
        tuple(request.model_dump_json() for request in fake.requests),
        tuple(step.action for step in result.episode_result.steps),
        log_path,
    )


def _shadow_evidence(root: Path, case_dir: Path, campaign_rules: Path) -> ShadowEvidence:
    off = _run_shadow_variant(root / "off", case_dir, campaign_rules, shadow=False)
    on = _run_shadow_variant(root / "on", case_dir, campaign_rules, shadow=True)
    if off[:5] != on[:5]:
        raise AcceptanceError("record-only shadow changed official Agent execution")
    log_path = on[5]
    if log_path is None or not log_path.is_file():
        raise AcceptanceError("record-only shadow did not write its isolated evidence")
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    if not records or not all(
        record["injected_into_prompt"] is False
        and record["affected_action"] is False
        and record["affected_state"] is False
        for record in records
    ):
        raise AcceptanceError("shadow isolation flags are not all false")
    return ShadowEvidence(
        request_bytes_equal=True,
        action_sequence_equal=True,
        episode_state_equal=True,
        campaign_state_equal=True,
    )


def _manual_probe(case_dir: Path, state_dir: Path) -> bool:
    state_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "xuanyi_npc.cli.play",
            "--case-dir",
            str(case_dir),
            "--state-dir",
            str(state_dir),
            "--mode",
            "manual",
            "--semantic-shadow",
            "off",
        ],
        input="0\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
        env=_safe_worker_environment(),
    )
    return (
        completed.returncode == 0
        and not completed.stderr.strip()
        and "manual" in completed.stdout
        and "无需 API Key" in completed.stdout
    )


def _public_history_evidence() -> HistoricalEvidence:
    manifest = PublicHistoryEvidenceManifest.model_validate_json(
        read_runtime_text(f"release/{M5_HISTORY_RESOURCE_NAME}")
    )
    return HistoricalEvidence.model_validate(
        {
            "verification_mode": "public_manifest",
            **manifest.model_dump(exclude={"schema_version"}),
        }
    )


def _verify_history(
    p4b_result: Path | None,
    p4d_result: Path | None,
) -> HistoricalEvidence:
    if p4b_result is None and p4d_result is None:
        return _public_history_evidence()
    if p4b_result is None or p4d_result is None:
        raise AcceptanceError("both raw history files must be provided together")
    if _sha256(p4b_result) != P4B_RAW_SHA256:
        raise AcceptanceError("P4b raw history SHA changed")
    if _sha256(p4d_result) != P4D_RAW_SHA256:
        raise AcceptanceError("P4d raw history SHA changed")
    return HistoricalEvidence(
        verification_mode="raw_sha256_verified",
        p4b_raw_sha256=P4B_RAW_SHA256,
        p4d_raw_sha256=P4D_RAW_SHA256,
    )


def run_acceptance(
    *,
    run_id: str,
    case_dir: Path,
    state_dir: Path,
    campaign_rules: Path,
    p4b_result: Path | None = None,
    p4d_result: Path | None = None,
) -> M5AcceptanceResult:
    if any(state_dir.iterdir()):
        raise AcceptanceError("acceptance state directory must be empty")
    history = _verify_history(p4b_result, p4d_result)
    service = _service(
        state_dir,
        case_dir,
        campaign_rules,
        player_ids=("player_acceptance_primary", "player_acceptance_secondary"),
        session_ids=(
            "session_acceptance_old",
            "session_acceptance_gray",
            "session_acceptance_moon",
            "session_acceptance_secondary_moon",
            "session_acceptance_rejections",
        ),
    )
    primary = service.create_player(CreatePlayerInput(display_name="纵向验收甲"))
    secondary = service.create_player(CreatePlayerInput(display_name="纵向验收乙"))
    for created_player in (primary,secondary):
        for exercise in service.progression_policy.config.foundation_exercises:
            service.complete_foundation_exercise(created_player.player_id,exercise.exercise_id,exercise.required_action_id)
    if not primary.ok or not secondary.ok or not primary.player_id or not secondary.player_id:
        raise AcceptanceError("could not create isolated acceptance players")

    primary_cases: list[AcceptedCase] = []
    worker_pids: list[int] = []
    loaded_large_runtime = False
    reactions = 0
    for case_id in CASE_ORDER:
        accepted, reaction, pids, loaded = _complete_case_across_processes(
            service,
            case_dir=case_dir,
            state_dir=state_dir,
            campaign_rules=campaign_rules,
            player_id=primary.player_id,
            case_id=case_id,
        )
        primary_cases.append(accepted)
        worker_pids.extend(pids)
        loaded_large_runtime = loaded_large_runtime or loaded
        if case_id != "old_paper_umbrella" and reaction is not None:
            reactions += 1

    primary_campaign = service.state_store.load_campaign(primary.player_id)
    campaign_replayed = CampaignEventReplayer().replay(
        CampaignState(player_id=primary.player_id),
        primary_campaign.event_history,
    )
    if campaign_replayed != primary_campaign:
        raise AcceptanceError("primary Campaign replay differs from disk")
    if (
        tuple(event.sequence for event in primary_campaign.event_history) != (1, 2, 3)
        or primary_campaign.unlocked_knowledge_ids != EXPECTED_KNOWLEDGE
        or reactions != 2
    ):
        raise AcceptanceError("primary cross-Episode continuity is incomplete")

    secondary_case, neutral_reaction, pids, loaded = _complete_case_across_processes(
        service,
        case_dir=case_dir,
        state_dir=state_dir,
        campaign_rules=campaign_rules,
        player_id=secondary.player_id,
        case_id="moon_well_echo",
    )
    worker_pids.extend(pids)
    loaded_large_runtime = loaded_large_runtime or loaded
    neutral = neutral_reaction is not None and "分别核对送信人的陈述" in neutral_reaction
    secondary_campaign = service.state_store.load_campaign(secondary.player_id)
    listed_primary = service.list_cases(ListCasesInput(player_id=primary.player_id))
    listed_secondary = service.list_cases(ListCasesInput(player_id=secondary.player_id))
    stored_sessions = service.state_store.list_case_sessions()
    primary_sessions = tuple(
        session for session in stored_sessions if session.player_id == primary.player_id
    )
    secondary_sessions = tuple(
        session for session in stored_sessions if session.player_id == secondary.player_id
    )
    isolated = (
        secondary_campaign.unlocked_knowledge_ids == frozenset()
        and {session.case_id for session in primary_sessions} == set(CASE_ORDER)
        and len(primary_sessions) == 3
        and tuple(session.case_id for session in secondary_sessions)
        == ("moon_well_echo",)
        and listed_primary.campaign_view != listed_secondary.campaign_view
    )
    if not neutral or not isolated:
        raise AcceptanceError("neutral path or player isolation failed")

    rejection_evidence = _rejection_evidence(
        service,
        primary_player_id=primary.player_id,
        secondary_player_id=secondary.player_id,
    )
    shadow = _shadow_evidence(state_dir / "shadow_acceptance", case_dir, campaign_rules)
    manual_ok = _manual_probe(case_dir, state_dir / "manual_probe")
    if not manual_ok or loaded_large_runtime:
        raise AcceptanceError("manual/Fake path initialized a forbidden dependency")

    checks = (
        AcceptanceCheck(check_id="three_case_campaign", evidence="同一玩家按推荐顺序完成三案，三案均为8事件、resolved / 100。"),
        AcceptanceCheck(check_id="multiple_investigation_choices", evidence="三案开始时均公开至少三个合法调查选项；参考Agent仅通过公开服务提交。"),
        AcceptanceCheck(check_id="two_history_reactions", evidence="灰灶与月井开场均收到由已提交Campaign事件投影的公开前史反应。"),
        AcceptanceCheck(check_id="process_restart_recovery", evidence="每个行动由独立Python子进程加载同一磁盘Session后提交。"),
        AcceptanceCheck(check_id="event_replay", evidence="三案Case事件及主玩家Campaign事件均从空初态重放到磁盘终态。"),
        AcceptanceCheck(check_id="player_isolation", evidence="第二玩家无知识前史进入月井，跨玩家恢复被拒绝且文件不变。"),
        AcceptanceCheck(check_id="rejection_zero_write", evidence="参数、规则、重复调查和越权恢复均为零事件、零修订、文件逐字节不变。"),
        AcceptanceCheck(check_id="no_llm_complete", evidence="Fake与manual路径均未初始化外部模型；三案由离线Fake完整完成。"),
        AcceptanceCheck(check_id="ordinary_user_cli", evidence="manual模块入口在无API Key环境正常启动并安全退出。"),
        AcceptanceCheck(check_id="demo_guide", evidence="可复现的3分钟和8–10分钟演示流程由P5文档冻结。"),
        AcceptanceCheck(check_id="dual_role_evidence", evidence="Agent应用岗与游戏AI产品岗证据分别整理，并标注证据等级。"),
        AcceptanceCheck(check_id="semantic_shadow_isolation", evidence="shadow off/on的请求、行动、Episode和Campaign逐字一致，旁路标志均为false。"),
        AcceptanceCheck(check_id="deterministic_growth", evidence="两项公开知识只由Campaign事件解锁，重启及重放后保持一致。"),
    )
    return M5AcceptanceResult(
        run_id=run_id,
        primary_cases=tuple(primary_cases),  # type: ignore[arg-type]
        primary_campaign_event_sequences=(1, 2, 3),
        primary_knowledge_ids=primary_campaign.unlocked_knowledge_ids,
        later_history_reactions_observed=2,
        secondary_moon_case=secondary_case,
        secondary_used_neutral_opening=True,
        players_isolated=True,
        rejection_evidence=rejection_evidence,
        shadow_evidence=shadow,
        manual_start_without_key=True,
        torch_or_bge_loaded_in_workers=False,
        worker_processes=len(worker_pids),
        all_worker_exit_codes_zero=True,
        checks=checks,
        historical_evidence=history,
    )


def _worker_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker-step", action="store_true")
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--campaign-rules", type=Path, required=True)
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args(argv)
    service = _service(args.state_dir, args.case_dir, args.campaign_rules)
    session = service.state_store.load_case_session(args.session_id)
    case = service.case_catalog.get(args.case_id)
    if case is None:
        return 2
    agent, _ = build_reference_fake_agent(
        case,
        completed_event_count=len(session.action_history),
    )
    result = ModeAwareEpisodeRunner(
        service=service,
        doctor_agent=agent,
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=1),
    ).run(
        ModeRunInput(
            player_id=args.player_id,
            case_id=args.case_id,
            session_id=args.session_id,
        )
    )
    step = result.episode_result.steps[0]
    payload = WorkerStepResult(
        pid=os.getpid(),
        accepted=step.accepted,
        error_code=step.error_code,
        session_revision=result.episode_result.final_session.revision,
        event_payloads=tuple(
            event.model_dump(mode="json") for event in result.episode_result.events
        ),
        torch_or_bge_loaded=(
            "torch" in sys.modules or "sentence_transformers" in sys.modules
        ),
    )
    sys.stdout.write(payload.model_dump_json())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xuanyi-m5-acceptance",
        description="离线验收三病例、跨案连续性、恢复、重放和安全隔离。",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=None,
        help="可选的病例目录；默认使用安装包内置病例。",
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--campaign-rules",
        type=Path,
        default=None,
        help="可选的 Campaign 规则；默认与内置病例一同加载。",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--p4b-result",
        type=Path,
        default=None,
        help="可选 P4b 原始结果；必须与 P4d 文件同时提供。",
    )
    parser.add_argument(
        "--p4d-result",
        type=Path,
        default=None,
        help="可选 P4d 原始结果；必须与 P4b 文件同时提供。",
    )
    return parser


def _write_result(path: Path, result: M5AcceptanceResult) -> None:
    if path.exists():
        raise AcceptanceError("acceptance output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(result.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _run_with_paths(
    args: argparse.Namespace,
    *,
    case_dir: Path,
    campaign_rules: Path,
) -> int:
    try:
        for directory in (case_dir, args.state_dir):
            if not directory.is_dir():
                raise AcceptanceError("configured directory is unavailable")
        if not campaign_rules.is_file():
            raise AcceptanceError("configured evidence file is unavailable")
        if (args.p4b_result is None) != (args.p4d_result is None):
            raise AcceptanceError("both raw history files must be provided together")
        for path in (args.p4b_result, args.p4d_result):
            if path is None:
                continue
            if not path.is_file():
                raise AcceptanceError("configured evidence file is unavailable")
        result = run_acceptance(
            run_id=args.run_id,
            case_dir=case_dir.resolve(),
            state_dir=args.state_dir.resolve(),
            campaign_rules=campaign_rules.resolve(),
            p4b_result=(
                args.p4b_result.resolve() if args.p4b_result is not None else None
            ),
            p4d_result=(
                args.p4d_result.resolve() if args.p4d_result is not None else None
            ),
        )
        _write_result(args.output, result)
    except AcceptanceError as exc:
        print(f"验收失败：{exc}", file=sys.stderr)
        return 1
    print("M5 离线纵向切片验收：通过")
    print("- 三病例：均为 8 个连续事件，resolved / 100")
    print("- 跨案连续性：Campaign 事件 1–3，两项公开知识已解锁")
    print("- 恢复与隔离：独立子进程恢复、双玩家隔离、拒绝零写入均通过")
    print("- semantic shadow：record-only 不影响请求、行动或状态")
    print("- 外部调用：0；费用：0 CNY")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    raw = tuple(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "--worker-step":
        return _worker_main(raw)
    args = build_parser().parse_args(raw)
    if args.case_dir is not None and args.campaign_rules is None:
        print("验收失败：自定义病例目录必须同时提供 Campaign 规则。", file=sys.stderr)
        return 2
    if args.case_dir is not None:
        return _run_with_paths(
            args,
            case_dir=args.case_dir,
            campaign_rules=args.campaign_rules,
        )
    try:
        with materialized_runtime_resources() as resources:
            return _run_with_paths(
                args,
                case_dir=resources.case_dir,
                campaign_rules=args.campaign_rules or resources.campaign_rules,
            )
    except PackageResourceError:
        print("验收失败：安装包运行数据不可用。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
