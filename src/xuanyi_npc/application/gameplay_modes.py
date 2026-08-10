"""Orthogonal gameplay and semantic-shadow assembly for M5-P4a."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field

from xuanyi_npc.agents.doctor import (
    DoctorAgentInput,
    DoctorAgentInterface,
    FixedV0Curriculum,
)
from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMAdapterError
from xuanyi_npc.config import AgentVariant
from xuanyi_npc.domain import CaseEvent, CaseSessionStatus
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.evaluation import EpisodeResult, EpisodeStatus, EpisodeStep, ModelUsage

from .multicase import (
    CampaignProjectionStatus,
    FinishEpisodeInput,
    MultiCaseEpisodeService,
    MultiCaseServiceResult,
    ResumeEpisodeInput,
    SubmitActionInput,
)
from .semantic_shadow import SemanticShadowObserver, ShadowObservationResult
from .v0_runner import SAFE_REJECTION_FEEDBACK


class GameplayMode(str, Enum):
    MANUAL = "manual"
    FAKE = "fake"
    DEEPSEEK_V0 = "deepseek_v0"


class SemanticShadowMode(str, Enum):
    OFF = "off"
    RECORD_ONLY = "record_only"


class ModeRunStopReason(str, Enum):
    COMPLETED = "completed"
    MAX_STEPS_REACHED = "max_steps_reached"
    MODEL_FAILURE = "model_failure"
    CONTEXT_FAILURE = "context_failure"


class GameplayModeConfig(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gameplay_mode: GameplayMode = GameplayMode.MANUAL
    semantic_shadow_mode: SemanticShadowMode = SemanticShadowMode.OFF
    max_steps: Annotated[int, Field(ge=1, le=100)] = 8


class ModeRunInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    initial_user_message: NonEmptyText = "请依据当前公开病例状态继续教学与行动。"


class ModeRunResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gameplay_mode: GameplayMode
    semantic_shadow_mode: SemanticShadowMode
    stop_reason: ModeRunStopReason
    episode_result: EpisodeResult
    public_result: MultiCaseServiceResult
    campaign_status: CampaignProjectionStatus | None = None
    campaign_event_sequences: tuple[Annotated[int, Field(ge=1)], ...] = ()
    shadow_observations: tuple[ShadowObservationResult, ...] = ()


class ModeRunnerConfigurationError(ValueError):
    """Raised before any model or shadow dependency can be called."""


class ModeAwareEpisodeRunner:
    """Run Fake or DeepSeek V0 through the persisted multi-case service only."""

    def __init__(
        self,
        *,
        service: MultiCaseEpisodeService,
        doctor_agent: DoctorAgentInterface,
        config: GameplayModeConfig,
        curriculum: FixedV0Curriculum | None = None,
        shadow_observer: SemanticShadowObserver | None = None,
    ) -> None:
        if config.gameplay_mode is GameplayMode.MANUAL:
            raise ModeRunnerConfigurationError(
                "manual mode is interactive and cannot initialize an Agent runner"
            )
        if (
            config.semantic_shadow_mode is SemanticShadowMode.OFF
            and shadow_observer is not None
        ):
            raise ModeRunnerConfigurationError("shadow off cannot initialize an observer")
        if (
            config.semantic_shadow_mode is SemanticShadowMode.RECORD_ONLY
            and shadow_observer is None
        ):
            raise ModeRunnerConfigurationError(
                "record-only shadow requires an explicitly injected observer"
            )
        self.service = service
        self.doctor_agent = doctor_agent
        self.config = config
        self.curriculum = curriculum or FixedV0Curriculum()
        self.shadow_observer = shadow_observer

    def run(self, request: ModeRunInput) -> ModeRunResult:
        case = self.service.case_catalog.get(request.case_id)
        if case is None:
            raise ModeRunnerConfigurationError("case is unavailable")
        try:
            initial_session = self.service.state_store.load_case_session(
                request.session_id
            )
            player = self.service.state_store.load_player(request.player_id)
        except Exception as exc:
            raise ModeRunnerConfigurationError("session is unavailable") from exc
        if (
            initial_session.player_id != request.player_id
            or initial_session.case_id != request.case_id
            or initial_session.status is not CaseSessionStatus.ACTIVE
        ):
            raise ModeRunnerConfigurationError("session context is invalid")

        public = self.service.resume_episode(self._resume_input(request))
        if not public.ok or public.observation is None:
            raise ModeRunnerConfigurationError("safe Agent context is unavailable")
        try:
            player_view = self.service.context_filter.player_view(player)
        except Exception as exc:
            raise ModeRunnerConfigurationError(
                "safe player context is unavailable"
            ) from exc

        recent_messages: deque[ChatMessage] = deque(
            [
                ChatMessage(
                    role=ChatRole.USER,
                    content=self._safe_opening(request.initial_user_message, public),
                )
            ],
            maxlen=self.doctor_agent.config.recent_message_limit,
        )
        steps: list[EpisodeStep] = []
        events: list[CaseEvent] = []
        usages: list[ModelUsage] = []
        complete_usage = True
        score_breakdown = None
        shadow_observations: list[ShadowObservationResult] = []
        stop_reason = ModeRunStopReason.MAX_STEPS_REACHED
        status = EpisodeStatus.MAX_STEPS_REACHED
        failure_code: str | None = None
        failure_latency_ms: float | None = None

        for step_index in range(1, self.config.max_steps + 1):
            assert public.observation is not None
            try:
                decision = self.doctor_agent.decide(
                    DoctorAgentInput(
                        step_index=step_index,
                        player_view=player_view,
                        case_observation=public.observation,
                        recent_messages=tuple(recent_messages),
                        fixed_lesson=self.curriculum.lesson_for_step(step_index),
                    )
                )
            except LLMAdapterError as exc:
                if not exc.abort_episode:
                    raise
                usages.extend(exc.prior_usages)
                if exc.usage is not None:
                    usages.append(exc.usage)
                complete_usage = False
                status = EpisodeStatus.FAILED
                stop_reason = ModeRunStopReason.MODEL_FAILURE
                failure_code = getattr(exc, "code", "llm_execution_aborted")
                failure_latency_ms = exc.latency_ms
                break

            if len(decision.usages) != decision.llm_attempts:
                complete_usage = False
            usages.extend(decision.usages)
            recent_messages.append(
                ChatMessage(role=ChatRole.ASSISTANT, content=decision.action.dialogue)
            )
            receipt = self.service.submit_action_with_receipt(
                SubmitActionInput(
                    player_id=request.player_id,
                    case_id=request.case_id,
                    session_id=request.session_id,
                    action=decision.action,
                )
            )
            public = receipt.result
            accepted = public.ok
            if accepted:
                recent_messages.append(
                    ChatMessage(role=ChatRole.TOOL, content=public.message)
                )
            else:
                recent_messages.append(
                    ChatMessage(role=ChatRole.TOOL, content=SAFE_REJECTION_FEEDBACK)
                )
            events.extend(receipt.events)
            if receipt.score_breakdown is not None:
                score_breakdown = receipt.score_breakdown
            steps.append(
                EpisodeStep(
                    step_index=step_index,
                    action=decision.action,
                    accepted=accepted,
                    event_sequences=public.event_sequences,
                    error_code=None if accepted else public.error_code,
                    llm_attempts=decision.llm_attempts,
                    used_fallback=decision.used_fallback,
                    provider_usages=decision.usages,
                )
            )
            if receipt.events and self.shadow_observer is not None:
                shadow_observations.append(
                    self.shadow_observer.observe(public, receipt.events)
                )
            if (
                public.episode_result is not None
                and public.episode_result.status is CaseSessionStatus.COMPLETED
            ):
                completed_public = public
                confirmation = self.service.finish_episode(
                    FinishEpisodeInput(
                        player_id=request.player_id,
                        case_id=request.case_id,
                        session_id=request.session_id,
                    )
                )
                public = completed_public if confirmation.ok else confirmation
                status = EpisodeStatus.COMPLETED
                stop_reason = ModeRunStopReason.COMPLETED
                break

        final_session = self.service.state_store.load_case_session(request.session_id)
        episode = EpisodeResult(
            episode_id=request.session_id,
            variant=AgentVariant.V0,
            status=status,
            max_steps=self.config.max_steps,
            initial_session=initial_session,
            final_session=final_session,
            steps=tuple(steps),
            events=tuple(events),
            score_breakdown=score_breakdown,
            failure_code=failure_code,
            failure_latency_ms=failure_latency_ms,
            usage=aggregate_model_usage(
                usages,
                measurement_complete=complete_usage,
            ),
        )
        return ModeRunResult(
            gameplay_mode=self.config.gameplay_mode,
            semantic_shadow_mode=self.config.semantic_shadow_mode,
            stop_reason=stop_reason,
            episode_result=episode,
            public_result=public,
            campaign_status=public.campaign_status,
            campaign_event_sequences=public.campaign_event_sequences,
            shadow_observations=tuple(shadow_observations),
        )

    @staticmethod
    def _resume_input(request: ModeRunInput) -> ResumeEpisodeInput:
        return ResumeEpisodeInput(
            player_id=request.player_id,
            case_id=request.case_id,
            session_id=request.session_id,
        )

    @staticmethod
    def _safe_opening(message: str, public: MultiCaseServiceResult) -> str:
        additions = tuple(
            value
            for value in (
                public.history_reaction,
                public.investigation_recommendation_reason,
            )
            if value is not None
        )
        return "\n".join((message, *additions))


def aggregate_model_usage(
    usages: list[ModelUsage],
    *,
    measurement_complete: bool,
) -> ModelUsage | None:
    """Aggregate measured provider usage; Fake runs leave this absent."""

    if not usages:
        return None
    providers = {usage.provider_model for usage in usages}
    provider_model = providers.pop() if len(providers) == 1 else "mixed_models"
    costs = [usage.estimated_cost for usage in usages]
    currencies = {usage.cost_currency for usage in usages}
    aggregate_cost = (
        all(cost is not None for cost in costs)
        and len(currencies) == 1
        and None not in currencies
    )
    total_cost = (
        sum((cost for cost in costs if cost is not None), Decimal("0"))
        if aggregate_cost
        else None
    )
    return ModelUsage(
        provider_model=provider_model,
        input_tokens=sum(usage.input_tokens for usage in usages),
        output_tokens=sum(usage.output_tokens for usage in usages),
        cache_hit_input_tokens=sum(usage.cache_hit_input_tokens for usage in usages),
        cache_miss_input_tokens=sum(usage.cache_miss_input_tokens for usage in usages),
        reasoning_tokens=sum(usage.reasoning_tokens for usage in usages),
        latency_ms=float(sum(usage.latency_ms for usage in usages)),
        estimated_cost=total_cost,
        cost_currency=currencies.pop() if aggregate_cost else None,
        provider_request_id=(
            usages[0].provider_request_id if len(usages) == 1 else None
        ),
        system_fingerprint=(
            next(iter({usage.system_fingerprint for usage in usages}))
            if len({usage.system_fingerprint for usage in usages}) == 1
            else None
        ),
        measurement_complete=(
            measurement_complete
            and all(usage.measurement_complete for usage in usages)
        ),
    )
