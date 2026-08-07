"""Budget-bounded runner for three independent real-model behavior probes."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, model_validator

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekBudgetExceededError,
    DeepSeekModelDiscovery,
    DeepSeekRequestBudgetGuard,
    DeepSeekUsageUnavailableError,
    DoctorAgent,
    DoctorAgentConfig,
    LLMAdapter,
)
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.evaluation import (
    DeepSeekPilotPricing,
    EpisodeResult,
    PilotBehaviorEvaluator,
    PilotEvaluationResult,
    load_deepseek_pilot_pricing,
)
from xuanyi_npc.evaluation.dev_runner import DEFAULT_CASE_PATH
from xuanyi_npc.evaluation.pilot_runner import (
    DEFAULT_PILOT_PROBE_PATH,
    load_pilot_probe_suite,
)

from .v0_runner import V0EpisodeConfig, V0EpisodeRunner


FROZEN_PILOT_PROBE_IDS = (
    "pilot_standard_completion_001",
    "pilot_wrong_induction_resistance_001",
    "pilot_premature_action_safety_001",
)
SAFETY_PILOT_PROBE_IDS = FROZEN_PILOT_PROBE_IDS[1:]


class DeepSeekPilotAdapter(LLMAdapter, Protocol):
    config: DeepSeekAdapterConfig
    request_budget: DeepSeekRequestBudgetGuard

    def discover_models(self) -> DeepSeekModelDiscovery:
        """Return the models currently available to this credential."""


class PilotRunStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    USAGE_UNAVAILABLE = "usage_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"


class PilotRunMode(str, Enum):
    ALL_PROBES = "all_probes"
    STANDARD_ONLY = "standard_only"
    SAFETY_ONLY = "safety_only"


class PilotEpisodeRecord(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_id: Identifier
    episode: EpisodeResult
    evaluation: PilotEvaluationResult


class PilotExecutionConfig(DomainModel):
    """Non-secret configuration persisted with every Pilot checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["deepseek"] = "deepseek"
    run_mode: PilotRunMode = PilotRunMode.ALL_PROBES
    base_url: NonEmptyText
    requested_model: NonEmptyText
    prompt_version: NonEmptyText
    timeout_seconds: float = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_steps_per_episode: Literal[8]
    max_format_repair_attempts_per_step: Literal[1]
    runs_per_probe: Literal[1]
    pricing_snapshot_id: Identifier
    request_input_token_upper_bound_method: Literal[
        "utf8_bytes_plus_framing"
    ] = "utf8_bytes_plus_framing"
    request_framing_token_allowance: int = Field(default=4096, ge=256)


class DeepSeekPilotRunResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: PilotRunStatus
    execution_config: PilotExecutionConfig
    configured_model: NonEmptyText
    available_models: tuple[NonEmptyText, ...]
    budget_limit: Decimal = Field(gt=0)
    estimated_cost: Decimal = Field(ge=0)
    maximum_committed_cost: Decimal = Field(ge=0)
    cost_currency: Literal["CNY"] = "CNY"
    completed_episodes: tuple[PilotEpisodeRecord, ...]
    unstarted_probe_ids: tuple[Identifier, ...]

    @model_validator(mode="before")
    @classmethod
    def migrate_pre_request_budget_checkpoint(cls, data: object) -> object:
        if isinstance(data, dict) and "maximum_committed_cost" not in data:
            return {**data, "maximum_committed_cost": data.get("estimated_cost", 0)}
        return data

    @model_validator(mode="after")
    def validate_budget_bounds(self) -> "DeepSeekPilotRunResult":
        if self.estimated_cost > self.maximum_committed_cost:
            raise ValueError("known cost cannot exceed maximum committed cost")
        if self.maximum_committed_cost > self.budget_limit:
            raise ValueError("maximum committed cost cannot exceed budget limit")
        return self


class DeepSeekPilotRunner:
    """Run the selected frozen behavior probes once after model discovery."""

    def __init__(
        self,
        adapter: DeepSeekPilotAdapter,
        *,
        pricing: DeepSeekPilotPricing | None = None,
        probe_path: Path | str = DEFAULT_PILOT_PROBE_PATH,
        case_path: Path | str = DEFAULT_CASE_PATH,
        run_mode: PilotRunMode = PilotRunMode.ALL_PROBES,
    ) -> None:
        self.adapter = adapter
        self.pricing = pricing or load_deepseek_pilot_pricing()
        self.probe_path = Path(probe_path)
        self.case_path = Path(case_path)
        self.run_mode = PilotRunMode(run_mode)
        self._validate_policy()

    def run(self, checkpoint_path: Path | str | None = None) -> DeepSeekPilotRunResult:
        suite = load_pilot_probe_suite(self.probe_path)
        case = CaseDefinition.model_validate_json(
            self.case_path.read_text(encoding="utf-8")
        )
        frozen_probe_ids = tuple(probe.probe_id for probe in suite.probes)
        if frozen_probe_ids != FROZEN_PILOT_PROBE_IDS:
            raise ValueError("Pilot suite must contain only the frozen behavior probes")
        if self.run_mode is PilotRunMode.STANDARD_ONLY:
            selected_probes = suite.probes[:1]
        elif self.run_mode is PilotRunMode.SAFETY_ONLY:
            selected_probes = suite.probes[1:]
        else:
            selected_probes = suite.probes
        probe_ids = tuple(probe.probe_id for probe in selected_probes)

        discovery = self.adapter.discover_models()
        if not discovery.configured_model_available:
            result = self._result(
                PilotRunStatus.MODEL_UNAVAILABLE,
                discovery,
                (),
                probe_ids,
            )
            self._checkpoint(checkpoint_path, result)
            return result

        player = build_demo_player()
        evaluator = PilotBehaviorEvaluator()
        budget = self.adapter.request_budget
        records: list[PilotEpisodeRecord] = []

        for index, probe in enumerate(selected_probes):
            pending = probe_ids[index:]
            if not budget.can_start_episode:
                result = self._result(
                    PilotRunStatus.BUDGET_EXHAUSTED,
                    discovery,
                    tuple(records),
                    pending,
                )
                self._checkpoint(checkpoint_path, result)
                return result

            initial_session = CaseSessionState(
                session_id=f"pilot_{probe.probe_id}",
                case_id=case.case_id,
                player_id=player.player_id,
            )
            episode = V0EpisodeRunner(
                DoctorAgent(self.adapter),
                config=V0EpisodeConfig(
                    max_steps=self.pricing.max_steps_per_episode
                ),
            ).run(
                episode_id=f"pilot_{probe.probe_id}",
                case=case,
                player=player,
                initial_session=initial_session,
                initial_user_message=probe.initial_user_message,
            )
            record = PilotEpisodeRecord(
                probe_id=probe.probe_id,
                episode=episode,
                evaluation=evaluator.evaluate(probe, episode)
            )
            remaining = probe_ids[index + 1 :]
            if episode.failure_code == DeepSeekBudgetExceededError.code:
                request_already_recorded = bool(
                    episode.steps or episode.usage is not None
                )
                if request_already_recorded:
                    records.append(record)
                result = self._result(
                    PilotRunStatus.BUDGET_EXHAUSTED,
                    discovery,
                    tuple(records),
                    remaining if request_already_recorded else pending,
                )
                self._checkpoint(checkpoint_path, result)
                return result
            records.append(record)
            if (
                episode.failure_code == DeepSeekUsageUnavailableError.code
                or budget.halted
            ):
                result = self._result(
                    PilotRunStatus.USAGE_UNAVAILABLE,
                    discovery,
                    tuple(records),
                    remaining,
                )
                self._checkpoint(checkpoint_path, result)
                return result

            status = (
                PilotRunStatus.COMPLETED
                if not remaining
                else (
                    PilotRunStatus.BUDGET_EXHAUSTED
                    if not budget.can_start_episode
                    else PilotRunStatus.IN_PROGRESS
                )
            )
            snapshot = self._result(
                status,
                discovery,
                tuple(records),
                remaining,
            )
            self._checkpoint(checkpoint_path, snapshot)
            if status in {
                PilotRunStatus.BUDGET_EXHAUSTED,
                PilotRunStatus.COMPLETED,
            }:
                return snapshot

        raise RuntimeError("validated Pilot suite unexpectedly contained no probes")

    def _validate_policy(self) -> None:
        if tuple(self.pricing.allowed_probe_ids) != FROZEN_PILOT_PROBE_IDS:
            raise ValueError("pricing snapshot does not match frozen Pilot probes")
        if self.pricing.runs_per_probe != 1:
            raise ValueError("Pilot only permits one run per probe")
        if self.pricing.max_steps_per_episode != 8:
            raise ValueError("Pilot Episode max steps must remain 8")
        if self.pricing.max_format_repair_attempts_per_step != 1:
            raise ValueError("Pilot format repair limit must remain one")
        if self.pricing.model != self.adapter.config.model:
            raise ValueError("Pilot pricing and adapter model must match")
        if (
            self.adapter.request_budget.max_cost_cny
            != self.adapter.config.pilot_max_cost_cny
        ):
            raise ValueError("request budget and configured Pilot budget must match")

    def _result(
        self,
        status: PilotRunStatus,
        discovery: DeepSeekModelDiscovery,
        records: tuple[PilotEpisodeRecord, ...],
        unstarted: tuple[str, ...],
    ) -> DeepSeekPilotRunResult:
        return DeepSeekPilotRunResult(
            status=status,
            execution_config=PilotExecutionConfig(
                run_mode=self.run_mode,
                base_url=self.adapter.config.base_url,
                requested_model=self.adapter.config.model,
                prompt_version=DoctorAgentConfig().prompt_version,
                timeout_seconds=self.adapter.config.timeout_seconds,
                max_output_tokens=self.adapter.config.max_output_tokens,
                max_steps_per_episode=self.pricing.max_steps_per_episode,
                max_format_repair_attempts_per_step=(
                    self.pricing.max_format_repair_attempts_per_step
                ),
                runs_per_probe=self.pricing.runs_per_probe,
                pricing_snapshot_id=self.pricing.snapshot_id,
                request_input_token_upper_bound_method=(
                    self.pricing.request_input_token_upper_bound_method
                ),
                request_framing_token_allowance=(
                    self.pricing.request_framing_token_allowance
                ),
            ),
            configured_model=discovery.configured_model,
            available_models=discovery.available_models,
            budget_limit=self.adapter.config.pilot_max_cost_cny,
            estimated_cost=self.adapter.request_budget.known_cost_cny,
            maximum_committed_cost=(
                self.adapter.request_budget.maximum_committed_cost_cny
            ),
            completed_episodes=records,
            unstarted_probe_ids=unstarted,
        )

    @staticmethod
    def _checkpoint(
        checkpoint_path: Path | str | None,
        result: DeepSeekPilotRunResult,
    ) -> None:
        if checkpoint_path is None:
            return
        destination = Path(checkpoint_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(destination)
