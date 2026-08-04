"""Budget-bounded runner for the three frozen M2b-P0 scenarios."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ConfigDict, Field

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekModelDiscovery,
    DoctorAgent,
    DoctorAgentConfig,
    LLMAdapter,
)
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.evaluation import (
    DeepSeekPilotPricing,
    DevEpisodeEvaluator,
    DevEvaluationResult,
    EpisodeResult,
    load_deepseek_pilot_pricing,
)
from xuanyi_npc.evaluation.dev_runner import (
    DEFAULT_CASE_PATH,
    DEFAULT_DEV_SUITE_PATH,
    load_dev_suite,
)

from .v0_runner import V0EpisodeConfig, V0EpisodeRunner


FROZEN_P0_SCENARIO_IDS = (
    "dev_case_correct_001",
    "dev_case_wrong_hypothesis_001",
    "dev_recovery_001",
)


class DeepSeekPilotAdapter(LLMAdapter, Protocol):
    config: DeepSeekAdapterConfig

    def discover_models(self) -> DeepSeekModelDiscovery:
        """Return the models currently available to this credential."""


class PilotRunStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    USAGE_UNAVAILABLE = "usage_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"


class PilotEpisodeRecord(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: Identifier
    episode: EpisodeResult
    evaluation: DevEvaluationResult


class PilotExecutionConfig(DomainModel):
    """Non-secret configuration persisted with every Pilot checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["deepseek"] = "deepseek"
    base_url: NonEmptyText
    requested_model: NonEmptyText
    prompt_version: NonEmptyText
    timeout_seconds: float = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_steps_per_episode: Literal[8]
    max_format_repair_attempts_per_step: Literal[1]
    runs_per_scenario: Literal[1]
    pricing_snapshot_id: Identifier


class DeepSeekPilotRunResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: PilotRunStatus
    execution_config: PilotExecutionConfig
    configured_model: NonEmptyText
    available_models: tuple[NonEmptyText, ...]
    budget_limit: Decimal = Field(gt=0)
    estimated_cost: Decimal = Field(ge=0)
    cost_currency: Literal["CNY"] = "CNY"
    completed_episodes: tuple[PilotEpisodeRecord, ...]
    unstarted_scenario_ids: tuple[Identifier, ...]


class PilotBudgetGuard:
    """Track returned cost estimates and decide whether another Episode may start."""

    def __init__(self, max_cost_cny: Decimal) -> None:
        if max_cost_cny <= 0:
            raise ValueError("Pilot budget must be positive")
        self.max_cost_cny = max_cost_cny
        self.estimated_cost_cny = Decimal("0")

    @property
    def can_start_episode(self) -> bool:
        return self.estimated_cost_cny < self.max_cost_cny

    def add_episode(self, episode: EpisodeResult) -> bool:
        usage = episode.usage
        if (
            usage is None
            or usage.estimated_cost is None
            or usage.cost_currency != "CNY"
        ):
            return False
        self.estimated_cost_cny += usage.estimated_cost
        return usage.measurement_complete


class DeepSeekPilotRunner:
    """Run exactly one Episode for each frozen scenario after model discovery."""

    def __init__(
        self,
        adapter: DeepSeekPilotAdapter,
        *,
        pricing: DeepSeekPilotPricing | None = None,
        suite_path: Path | str = DEFAULT_DEV_SUITE_PATH,
        case_path: Path | str = DEFAULT_CASE_PATH,
    ) -> None:
        self.adapter = adapter
        self.pricing = pricing or load_deepseek_pilot_pricing()
        self.suite_path = Path(suite_path)
        self.case_path = Path(case_path)
        self._validate_policy()

    def run(self, checkpoint_path: Path | str | None = None) -> DeepSeekPilotRunResult:
        suite = load_dev_suite(self.suite_path)
        case = CaseDefinition.model_validate_json(
            self.case_path.read_text(encoding="utf-8")
        )
        scenario_ids = tuple(scenario.scenario_id for scenario in suite.scenarios)
        if scenario_ids != FROZEN_P0_SCENARIO_IDS:
            raise ValueError("Pilot suite must contain only the frozen P0 scenarios")

        discovery = self.adapter.discover_models()
        if not discovery.configured_model_available:
            result = self._result(
                PilotRunStatus.MODEL_UNAVAILABLE,
                discovery,
                Decimal("0"),
                (),
                scenario_ids,
            )
            self._checkpoint(checkpoint_path, result)
            return result

        player = build_demo_player()
        evaluator = DevEpisodeEvaluator()
        budget = PilotBudgetGuard(self.adapter.config.pilot_max_cost_cny)
        records: list[PilotEpisodeRecord] = []

        for index, scenario in enumerate(suite.scenarios):
            pending = scenario_ids[index:]
            if not budget.can_start_episode:
                result = self._result(
                    PilotRunStatus.BUDGET_EXHAUSTED,
                    discovery,
                    budget.estimated_cost_cny,
                    tuple(records),
                    pending,
                )
                self._checkpoint(checkpoint_path, result)
                return result

            initial_session = CaseSessionState(
                session_id=f"pilot_{scenario.scenario_id}",
                case_id=case.case_id,
                player_id=player.player_id,
            )
            episode = V0EpisodeRunner(
                DoctorAgent(self.adapter),
                config=V0EpisodeConfig(
                    max_steps=self.pricing.max_steps_per_episode
                ),
            ).run(
                episode_id=f"pilot_{scenario.scenario_id}",
                case=case,
                player=player,
                initial_session=initial_session,
                initial_user_message=scenario.initial_user_message,
            )
            records.append(
                PilotEpisodeRecord(
                    scenario_id=scenario.scenario_id,
                    episode=episode,
                    evaluation=evaluator.evaluate(
                        scenario,
                        "pilot_run_001",
                        episode,
                    ),
                )
            )
            remaining = scenario_ids[index + 1 :]
            if not budget.add_episode(episode):
                result = self._result(
                    PilotRunStatus.USAGE_UNAVAILABLE,
                    discovery,
                    budget.estimated_cost_cny,
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
                budget.estimated_cost_cny,
                tuple(records),
                remaining,
            )
            self._checkpoint(checkpoint_path, snapshot)
            if status in {
                PilotRunStatus.BUDGET_EXHAUSTED,
                PilotRunStatus.COMPLETED,
            }:
                return snapshot

        raise RuntimeError("validated Pilot suite unexpectedly contained no scenarios")

    def _validate_policy(self) -> None:
        if tuple(self.pricing.allowed_scenario_ids) != FROZEN_P0_SCENARIO_IDS:
            raise ValueError("pricing snapshot does not match frozen P0 scenarios")
        if self.pricing.runs_per_scenario != 1:
            raise ValueError("Pilot only permits one run per scenario")
        if self.pricing.max_steps_per_episode != 8:
            raise ValueError("Pilot Episode max steps must remain 8")
        if self.pricing.max_format_repair_attempts_per_step != 1:
            raise ValueError("Pilot format repair limit must remain one")
        if self.pricing.model != self.adapter.config.model:
            raise ValueError("Pilot pricing and adapter model must match")

    def _result(
        self,
        status: PilotRunStatus,
        discovery: DeepSeekModelDiscovery,
        estimated_cost: Decimal,
        records: tuple[PilotEpisodeRecord, ...],
        unstarted: tuple[str, ...],
    ) -> DeepSeekPilotRunResult:
        return DeepSeekPilotRunResult(
            status=status,
            execution_config=PilotExecutionConfig(
                base_url=self.adapter.config.base_url,
                requested_model=self.adapter.config.model,
                prompt_version=DoctorAgentConfig().prompt_version,
                timeout_seconds=self.adapter.config.timeout_seconds,
                max_output_tokens=self.adapter.config.max_output_tokens,
                max_steps_per_episode=self.pricing.max_steps_per_episode,
                max_format_repair_attempts_per_step=(
                    self.pricing.max_format_repair_attempts_per_step
                ),
                runs_per_scenario=self.pricing.runs_per_scenario,
                pricing_snapshot_id=self.pricing.snapshot_id,
            ),
            configured_model=discovery.configured_model,
            available_models=discovery.available_models,
            budget_limit=self.adapter.config.pilot_max_cost_cny,
            estimated_cost=estimated_cost,
            completed_episodes=records,
            unstarted_scenario_ids=unstarted,
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
