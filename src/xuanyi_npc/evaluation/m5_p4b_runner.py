"""Budget-bounded real DeepSeek validation over the formal M5 Campaign path."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal, Sequence

from pydantic import ConfigDict, Field, StrictBool, model_validator

from xuanyi_npc.agents import (
    DeepSeekChatAdapter,
    DeepSeekGameplayAuthorization,
    DeepSeekModelDiscovery,
    DoctorAgent,
    DoctorAgentConfig,
    LLMAdapter,
    LLMRequest,
    LLMResponse,
    build_authorized_deepseek_v0_agent,
    build_reference_fake_agent,
)
from xuanyi_npc.application import (
    CampaignRuleSet,
    CaseCatalog,
    CreatePlayerInput,
    MultiCaseEpisodeService,
    ResumeEpisodeInput,
    StartEpisodeInput,
)
from xuanyi_npc.application.gameplay_modes import (
    GameplayMode,
    GameplayModeConfig,
    ModeAwareEpisodeRunner,
    ModeRunInput,
    ModeRunResult,
    SemanticShadowMode,
)
from xuanyi_npc.domain import (
    CampaignEventReplayer,
    CampaignState,
    CaseSessionStatus,
    TreatmentOutcome,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.evaluation import EpisodeStatus
from xuanyi_npc.storage import JsonStateStore


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PACKAGED_RESOURCES = files("xuanyi_npc.resources")
DEFAULT_CASE_DIR = Path(str(_PACKAGED_RESOURCES.joinpath("cases")))
DEFAULT_CAMPAIGN_RULES = Path(
    str(
        _PACKAGED_RESOURCES
        .joinpath("campaign")
        .joinpath("cross_episode_rules_v1.json")
    )
)
P4A_BASELINE_COMMIT = "bb06270878c8dd10cbd98cdb72fa42cbcaa0f53d"
P4B_BUDGET_CNY = Decimal("0.05")
P4B_CASE_IDS = ("gray_hearth_inn", "moon_well_echo")
SEMANTIC_MEMORY_MARKERS = (
    "retrieved_memories",
    "memory_context_status",
    "MemoryView",
    "memory_id",
    "source_session_id",
    "embedding_space_id",
    '"similarity"',
)


class P4bRunStatus(str, Enum):
    COMPLETED = "completed"
    STOPPED_AFTER_GRAY = "stopped_after_gray"
    STOPPED_BEFORE_CHAT = "stopped_before_chat"
    STOPPED_ON_ERROR = "stopped_on_error"


class PromptRequestAudit(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_index: Annotated[int, Field(ge=1)]
    request_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    semantic_memory_markers_found: tuple[NonEmptyText, ...] = ()


class PublicEpisodeContext(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Identifier
    history_reaction: NonEmptyText | None = None
    recommended_investigation_id: Identifier | None = None
    unlocked_knowledge_ids: tuple[Identifier, ...] = ()


class P4bHistoryCheckpoint(DomainModel):
    """Sanitized proof that the free Campaign history predates provider discovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Identifier
    status: Literal["deterministic_history_ready"] = "deterministic_history_ready"
    execution_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    models_request_count: Literal[0] = 0
    chat_request_count: Literal[0] = 0
    player_ref_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    old_paper: ModeRunResult
    old_paper_replay_consistent: Literal[True] = True
    semantic_shadow: Literal["off"] = "off"


class P4bCampaignRunResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Identifier
    status: P4bRunStatus
    p4a_baseline_commit: Literal[P4A_BASELINE_COMMIT] = P4A_BASELINE_COMMIT
    execution_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    provider: Literal["deepseek"] = "deepseek"
    requested_model: Literal["deepseek-v4-flash"] = "deepseek-v4-flash"
    prompt_version: Literal["v0.2.1"] = "v0.2.1"
    semantic_shadow: Literal["off"] = "off"
    budget_limit_cny: Decimal = Field(default=P4B_BUDGET_CNY, gt=0)
    known_cost_cny: Decimal = Field(default=Decimal("0"), ge=0)
    maximum_committed_cost_cny: Decimal = Field(default=Decimal("0"), ge=0)
    models_request_count: Annotated[int, Field(ge=0, le=1)] = 0
    chat_request_count: Annotated[int, Field(ge=0, le=32)] = 0
    configured_model_available: StrictBool | None = None
    available_models: tuple[NonEmptyText, ...] = ()
    player_ref_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    old_paper: ModeRunResult
    old_paper_replay_consistent: StrictBool
    gray_context: PublicEpisodeContext | None = None
    gray_hearth: ModeRunResult | None = None
    gray_episode_replay_consistent: StrictBool | None = None
    gray_campaign_replay_consistent: StrictBool | None = None
    moon_context: PublicEpisodeContext | None = None
    moon_well: ModeRunResult | None = None
    moon_episode_replay_consistent: StrictBool | None = None
    moon_campaign_replay_consistent: StrictBool | None = None
    request_audits: tuple[PromptRequestAudit, ...] = ()
    stop_reason: Identifier | None = None

    @model_validator(mode="after")
    def validate_run(self) -> "P4bCampaignRunResult":
        if self.known_cost_cny > self.maximum_committed_cost_cny:
            raise ValueError("known cost cannot exceed maximum committed cost")
        if self.maximum_committed_cost_cny > self.budget_limit_cny:
            raise ValueError("maximum committed cost cannot exceed budget")
        if self.chat_request_count != len(self.request_audits):
            raise ValueError("every Chat request requires one request audit")
        if any(audit.semantic_memory_markers_found for audit in self.request_audits):
            raise ValueError("semantic memory markers cannot enter V0 requests")
        if self.moon_well is not None and self.gray_hearth is None:
            raise ValueError("moon well cannot run before gray hearth")
        return self


class AuditedLLMAdapter:
    """Record non-sensitive request identity and block memory injection pre-network."""

    def __init__(self, delegate: LLMAdapter) -> None:
        self.delegate = delegate
        self.audits: list[PromptRequestAudit] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        canonical = request.model_dump_json()
        found = tuple(marker for marker in SEMANTIC_MEMORY_MARKERS if marker in canonical)
        audit = PromptRequestAudit(
            chat_index=len(self.audits) + 1,
            request_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            semantic_memory_markers_found=found,
        )
        self.audits.append(audit)
        if found:
            raise RuntimeError("semantic memory marker detected before provider call")
        return self.delegate.complete(request)


class FixedPilotPlayerIds:
    def new_player_id(self) -> str:
        return "player_m5_p4b"


class SequentialPilotSessionIds:
    def __init__(self) -> None:
        self._next = 0

    def new_session_id(self) -> str:
        self._next += 1
        return f"session_m5_p4b_{self._next}"


class M5P4bCampaignRunner:
    """Execute at most one paid run for each new case after frozen free history."""

    def __init__(
        self,
        *,
        service: MultiCaseEpisodeService,
        adapter: DeepSeekChatAdapter,
        discovery: DeepSeekModelDiscovery,
        execution_commit: str,
        run_id: str,
        player_id: str,
        old_paper: ModeRunResult,
    ) -> None:
        self.service = service
        self.adapter = adapter
        self.discovery = discovery
        self.execution_commit = execution_commit
        self.run_id = run_id
        self.player_id = player_id
        self.old_paper = old_paper
        self.audit_adapter = AuditedLLMAdapter(adapter)
        self.doctor_agent = DoctorAgent(
            self.audit_adapter,
            DoctorAgentConfig(prompt_version="v0.2.1"),
        )

    def run(self, checkpoint_path: Path) -> P4bCampaignRunResult:
        player_id = self.player_id
        old = self.old_paper
        gray_context, gray_session_id = self._start_paid_context(
            player_id, "gray_hearth_inn"
        )
        gray = self._run_paid_case(
            player_id, "gray_hearth_inn", gray_session_id
        )
        if not self._gray_allows_moon(player_id, gray):
            result = self._result(
                player_id=player_id,
                status=P4bRunStatus.STOPPED_AFTER_GRAY,
                old=old,
                gray_context=gray_context,
                gray=gray,
                stop_reason="gray_did_not_unlock_moon",
            )
            self._checkpoint(checkpoint_path, result)
            return result

        moon_context, moon_session_id = self._start_paid_context(
            player_id, "moon_well_echo"
        )
        moon = self._run_paid_case(player_id, "moon_well_echo", moon_session_id)
        result = self._result(
            player_id=player_id,
            status=P4bRunStatus.COMPLETED,
            old=old,
            gray_context=gray_context,
            gray=gray,
            moon_context=moon_context,
            moon=moon,
        )
        self._checkpoint(checkpoint_path, result)
        return result

    def _run_paid_case(
        self, player_id: str, case_id: str, session_id: str
    ) -> ModeRunResult:
        if not self.adapter.request_budget.can_start_episode:
            raise RuntimeError("paid budget cannot start another episode")
        return ModeAwareEpisodeRunner(
            service=self.service,
            doctor_agent=self.doctor_agent,
            config=GameplayModeConfig(
                gameplay_mode=GameplayMode.DEEPSEEK_V0,
                semantic_shadow_mode=SemanticShadowMode.OFF,
                max_steps=8,
            ),
        ).run(
            ModeRunInput(
                player_id=player_id,
                case_id=case_id,
                session_id=session_id,
            )
        )

    def _assert_old_history(self, player_id: str, result: ModeRunResult) -> None:
        episode = result.episode_result
        campaign = self.service.state_store.load_campaign(player_id)
        if (
            episode.status is not EpisodeStatus.COMPLETED
            or episode.final_session.outcome is not TreatmentOutcome.RESOLVED
            or episode.final_session.selected_treatment_id
            != "return_token_and_fulfill_vow"
            or "contract_provenance_check" not in campaign.unlocked_knowledge_ids
        ):
            raise RuntimeError("deterministic history precondition failed")
        self._assert_episode_replay(result)
        self._assert_campaign_replay(player_id)

    def _gray_allows_moon(self, player_id: str, result: ModeRunResult) -> bool:
        episode = result.episode_result
        if (
            episode.status is not EpisodeStatus.COMPLETED
            or episode.final_session.status is not CaseSessionStatus.COMPLETED
            or episode.final_session.outcome is not TreatmentOutcome.RESOLVED
            or result.campaign_status is None
            or result.campaign_status.value != "ready"
        ):
            return False
        campaign = self.service.state_store.load_campaign(player_id)
        return "handoff_sequence_check" in campaign.unlocked_knowledge_ids

    def _start_paid_context(
        self, player_id: str, case_id: str
    ) -> tuple[PublicEpisodeContext, str]:
        opened = self.service.start_episode(
            StartEpisodeInput(player_id=player_id, case_id=case_id)
        )
        if not opened.ok or opened.session_id is None:
            raise RuntimeError("failed to establish public paid context")
        resumed = self.service.resume_episode(
            ResumeEpisodeInput(
                player_id=player_id,
                case_id=case_id,
                session_id=opened.session_id,
            )
        )
        campaign = resumed.campaign_view
        return (
            PublicEpisodeContext(
                case_id=case_id,
                history_reaction=resumed.history_reaction,
                recommended_investigation_id=resumed.recommended_investigation_id,
                unlocked_knowledge_ids=(
                    tuple(item.knowledge_id for item in campaign.unlocked_knowledge)
                    if campaign is not None
                    else ()
                ),
            ),
            opened.session_id,
        )

    def _result(
        self,
        *,
        player_id: str,
        status: P4bRunStatus,
        old: ModeRunResult,
        gray_context: PublicEpisodeContext | None = None,
        gray: ModeRunResult | None = None,
        moon_context: PublicEpisodeContext | None = None,
        moon: ModeRunResult | None = None,
        stop_reason: str | None = None,
    ) -> P4bCampaignRunResult:
        budget = self.adapter.request_budget
        return P4bCampaignRunResult(
            run_id=self.run_id,
            status=status,
            execution_commit=self.execution_commit,
            known_cost_cny=budget.known_cost_cny,
            maximum_committed_cost_cny=budget.maximum_committed_cost_cny,
            models_request_count=1,
            chat_request_count=len(self.audit_adapter.audits),
            configured_model_available=self.discovery.configured_model_available,
            available_models=self.discovery.available_models,
            player_ref_sha256=hashlib.sha256(player_id.encode("utf-8")).hexdigest(),
            old_paper=old,
            old_paper_replay_consistent=self._episode_replay_consistent(old),
            gray_context=gray_context,
            gray_hearth=gray,
            gray_episode_replay_consistent=(
                self._episode_replay_consistent(gray) if gray is not None else None
            ),
            gray_campaign_replay_consistent=(
                self._campaign_replay_consistent(player_id) if gray is not None else None
            ),
            moon_context=moon_context,
            moon_well=moon,
            moon_episode_replay_consistent=(
                self._episode_replay_consistent(moon) if moon is not None else None
            ),
            moon_campaign_replay_consistent=(
                self._campaign_replay_consistent(player_id) if moon is not None else None
            ),
            request_audits=tuple(self.audit_adapter.audits),
            stop_reason=stop_reason,
        )

    @staticmethod
    def _assert_episode_replay(result: ModeRunResult) -> None:
        if not M5P4bCampaignRunner._episode_replay_consistent(result):
            raise RuntimeError("episode replay mismatch")

    @staticmethod
    def _episode_replay_consistent(result: ModeRunResult) -> bool:
        episode = result.episode_result
        try:
            from xuanyi_npc.engine import CaseEventReplayer

            replayed = CaseEventReplayer().replay(
                episode.initial_session,
                episode.events,
            )
        except Exception:
            return False
        return replayed == episode.final_session

    def _assert_campaign_replay(self, player_id: str) -> None:
        if not self._campaign_replay_consistent(player_id):
            raise RuntimeError("campaign replay mismatch")

    def _campaign_replay_consistent(self, player_id: str) -> bool:
        try:
            state = self.service.state_store.load_campaign(player_id)
            initial = CampaignState(player_id=player_id)
            replayed = CampaignEventReplayer().replay(initial, state.event_history)
        except Exception:
            return False
        return replayed == state

    @staticmethod
    def _checkpoint(
        path: Path, result: P4bCampaignRunResult | P4bHistoryCheckpoint
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump_json(indent=2)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except OSError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise


def _git_text(*args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return completed.stdout.strip()


def validate_execution_preflight(
    *,
    freeze_commit: str,
    state_dir: Path,
    output: Path,
) -> None:
    if _git_text("rev-parse", "HEAD") != freeze_commit:
        raise RuntimeError("HEAD does not match the authorized execution commit")
    if _git_text("status", "--porcelain"):
        raise RuntimeError("working tree must be clean")
    if freeze_commit == P4A_BASELINE_COMMIT:
        raise RuntimeError("P4b requires a dedicated runner execution commit")
    if not state_dir.is_dir() or tuple(state_dir.iterdir()):
        raise RuntimeError("state directory must exist and be empty")
    if output.exists() or not output.parent.is_dir():
        raise RuntimeError("output must be new and its parent must exist")
    for path in (state_dir, output):
        ignored = subprocess.run(
            ("git", "check-ignore", "--quiet", str(path)),
            cwd=REPOSITORY_ROOT,
            check=False,
            timeout=15,
        )
        if ignored.returncode != 0:
            raise RuntimeError("state and result paths must be Git ignored")


def build_service(state_dir: Path) -> MultiCaseEpisodeService:
    catalog = CaseCatalog(DEFAULT_CASE_DIR)
    rules = CampaignRuleSet.load(DEFAULT_CAMPAIGN_RULES, catalog)
    return MultiCaseEpisodeService(
        state_store=JsonStateStore(state_dir),
        case_catalog=catalog,
        player_id_factory=FixedPilotPlayerIds(),
        session_id_factory=SequentialPilotSessionIds(),
        campaign_rules=rules,
    )


def prepare_deterministic_history(
    service: MultiCaseEpisodeService,
) -> tuple[str, ModeRunResult]:
    """Create and verify the free old-paper history before provider discovery."""

    player = service.create_player(
        CreatePlayerInput(display_name="M5-P4b 公开前史测试玩家")
    )
    if not player.ok or player.player_id is None:
        raise RuntimeError("failed to create isolated pilot player")
    player_id = player.player_id
    opened = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="old_paper_umbrella")
    )
    case = service.case_catalog.get("old_paper_umbrella")
    if not opened.ok or opened.session_id is None or case is None:
        raise RuntimeError("failed to start deterministic history episode")
    agent, _ = build_reference_fake_agent(case)
    result = ModeAwareEpisodeRunner(
        service=service,
        doctor_agent=agent,
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=8),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id=case.case_id,
            session_id=opened.session_id,
        )
    )
    episode = result.episode_result
    campaign = service.state_store.load_campaign(player_id)
    if (
        episode.status is not EpisodeStatus.COMPLETED
        or episode.final_session.outcome is not TreatmentOutcome.RESOLVED
        or episode.final_session.selected_treatment_id
        != "return_token_and_fulfill_vow"
        or "contract_provenance_check" not in campaign.unlocked_knowledge_ids
        or not M5P4bCampaignRunner._episode_replay_consistent(result)
        or CampaignEventReplayer().replay(
            CampaignState(player_id=player_id), campaign.event_history
        )
        != campaign
    ):
        raise RuntimeError("deterministic history precondition failed")
    return player_id, result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen M5-P4b Campaign Pilot")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-real-paid-run", action="store_true")
    parser.add_argument("--budget-cny", type=Decimal, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_real_paid_run:
        print("--confirm-real-paid-run is required", file=sys.stderr)
        return 2
    if args.budget_cny != P4B_BUDGET_CNY:
        print("budget must equal the authorized 0.05 CNY", file=sys.stderr)
        return 2
    try:
        validate_execution_preflight(
            freeze_commit=args.freeze_commit,
            state_dir=args.state_dir,
            output=args.output,
        )
        service = build_service(args.state_dir)
        player_id, old_paper = prepare_deterministic_history(service)
        M5P4bCampaignRunner._checkpoint(
            args.output,
            P4bHistoryCheckpoint(
                run_id=args.run_id,
                execution_commit=args.freeze_commit,
                player_ref_sha256=hashlib.sha256(
                    player_id.encode("utf-8")
                ).hexdigest(),
                old_paper=old_paper,
            ),
        )
        authorization = DeepSeekGameplayAuthorization(
            confirm_paid=True,
            max_cost_cny=P4B_BUDGET_CNY,
            timeout_seconds=180,
            results_dir=args.output.parent,
        )
        _, adapter, discovery = build_authorized_deepseek_v0_agent(authorization)
        try:
            result = M5P4bCampaignRunner(
                service=service,
                adapter=adapter,
                discovery=discovery,
                execution_commit=args.freeze_commit,
                run_id=args.run_id,
                player_id=player_id,
                old_paper=old_paper,
            ).run(args.output)
        finally:
            adapter.close()
    except Exception as exc:
        print(f"P4b stopped safely: {getattr(exc, 'code', type(exc).__name__)}", file=sys.stderr)
        return 1
    print(
        f"P4b finished: {result.status.value}; models=1; chats={result.chat_request_count}; "
        f"known_cost_cny={result.known_cost_cny}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
