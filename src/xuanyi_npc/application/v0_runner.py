"""Bounded M2-V0 episode loop over DoctorAgent and deterministic tools."""

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Protocol

from pydantic import ConfigDict, Field, StrictInt

from xuanyi_npc.agents import (
    AgentDecision,
    BoundedActionContractResolver,
    ChatMessage,
    ChatRole,
    DoctorAgentInput,
    DoctorAgentInterface,
    FixedV0Curriculum,
    LLMAdapterError,
)
from xuanyi_npc.config import AgentVariant
from xuanyi_npc.domain import (
    AgentActionType,
    CaseDefinition,
    CaseEvent,
    CaseSessionState,
    CaseSessionStatus,
    PlayerState,
)
from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.engine import RuleViolation, ScoreBreakdown
from xuanyi_npc.evaluation import (
    EpisodeResult,
    EpisodeStatus,
    EpisodeStep,
    ModelUsage,
)

from .v0_tools import ToolCallError, V0ToolExecutor
from .action_contract import build_safe_action_feedback
from .diagnosis_readiness import (
    DiagnosisReadinessPolicy,
    FixedV0DiagnosisReadinessPolicy,
)
from .views import AgentContextFilter, ViewContextError


class Clock(Protocol):
    def now(self) -> datetime:
        """Return a timezone-aware timestamp owned by the application layer."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class V0EpisodeConfig(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: Annotated[StrictInt, Field(ge=1, le=100)] = 12


class V0EpisodeRunner:
    """Run Prompt-Only V0 without memory, adaptive teaching, or Reflection."""

    def __init__(
        self,
        doctor_agent: DoctorAgentInterface,
        tool_executor: V0ToolExecutor | None = None,
        context_filter: AgentContextFilter | None = None,
        curriculum: FixedV0Curriculum | None = None,
        clock: Clock | None = None,
        config: V0EpisodeConfig | None = None,
        diagnosis_readiness_policy: DiagnosisReadinessPolicy | None = None,
        _preserve_historical_trace_semantics: bool = False,
    ) -> None:
        self.doctor_agent = doctor_agent
        if tool_executor is not None and diagnosis_readiness_policy is not None:
            raise ValueError(
                "inject diagnosis readiness through the runner or tool executor, not both"
            )
        if tool_executor is None:
            self.context_filter = context_filter or AgentContextFilter()
            self.tool_executor = V0ToolExecutor(
                context_filter=self.context_filter,
                diagnosis_readiness_policy=(
                    diagnosis_readiness_policy
                    or FixedV0DiagnosisReadinessPolicy()
                ),
            )
        else:
            if (
                context_filter is not None
                and context_filter is not tool_executor.context_filter
            ):
                raise ValueError(
                    "runner and tool executor must share one context filter"
                )
            self.tool_executor = tool_executor
            self.context_filter = tool_executor.context_filter
            if tool_executor.diagnosis_readiness_policy is None:
                raise ValueError(
                    "a custom fixed_v0 tool executor requires an explicit diagnosis policy"
                )
        self.curriculum = curriculum or FixedV0Curriculum()
        self.clock = clock or SystemClock()
        self.config = config or V0EpisodeConfig()
        self.action_contract = BoundedActionContractResolver()
        self._preserve_historical_trace_semantics = (
            _preserve_historical_trace_semantics
        )

    def run(
        self,
        episode_id: str,
        case: CaseDefinition,
        player: PlayerState,
        initial_session: CaseSessionState,
        initial_user_message: str,
    ) -> EpisodeResult:
        try:
            player_view = self.context_filter.player_view(player)
            self.tool_executor.case_observation(case, player, initial_session)
        except ViewContextError:
            return self._failed(
                episode_id,
                initial_session,
                "context_mismatch",
            )
        if initial_session.status is not CaseSessionStatus.ACTIVE:
            return self._failed(
                episode_id,
                initial_session,
                "invalid_initial_session",
            )

        recent_messages: deque[ChatMessage] = deque(
            [ChatMessage(role=ChatRole.USER, content=initial_user_message)],
            maxlen=self.doctor_agent.config.recent_message_limit,
        )
        current = initial_session
        steps: list[EpisodeStep] = []
        events: list[CaseEvent] = []
        usages: list[ModelUsage] = []
        complete_usage = True
        score_breakdown: ScoreBreakdown | None = None
        status = EpisodeStatus.MAX_STEPS_REACHED

        for step_index in range(1, self.config.max_steps + 1):
            observation = self.tool_executor.case_observation(case, player, current)
            agent_input = DoctorAgentInput(
                step_index=step_index,
                player_view=player_view,
                case_observation=observation,
                recent_messages=tuple(recent_messages),
                fixed_lesson=self.curriculum.lesson_for_step(step_index),
            )
            try:
                decision = self.doctor_agent.decide(agent_input)
                if not self._preserve_historical_trace_semantics:
                    resolution = self.action_contract.resolve(
                        self.doctor_agent,
                        agent_input,
                        decision,
                        observation,
                    )
                    decision = resolution.decision
                    contract_error = resolution.error_code
                else:
                    contract_error = None
            except LLMAdapterError as exc:
                if not exc.abort_episode:
                    raise
                usages.extend(exc.prior_usages)
                if exc.usage is not None:
                    usages.append(exc.usage)
                return EpisodeResult(
                    episode_id=episode_id,
                    variant=AgentVariant.V0,
                    status=EpisodeStatus.FAILED,
                    max_steps=self.config.max_steps,
                    initial_session=initial_session,
                    final_session=current,
                    steps=tuple(steps),
                    events=tuple(events),
                    failure_code=getattr(exc, "code", "llm_execution_aborted"),
                    failure_latency_ms=exc.latency_ms,
                    usage=self._aggregate_usage(
                        usages,
                        measurement_complete=False,
                    ),
                )
            if len(decision.usages) != decision.llm_attempts:
                complete_usage = False
            usages.extend(decision.usages)
            recent_messages.append(
                ChatMessage(role=ChatRole.ASSISTANT, content=decision.action.dialogue)
            )

            accepted = True
            error_code: str | None = None
            event_sequences: tuple[int, ...] = ()
            if contract_error is not None:
                accepted = False
                error_code = contract_error
                recent_messages.append(
                    ChatMessage(
                        role=ChatRole.TOOL,
                        content=build_safe_action_feedback(
                            contract_error,
                            observation,
                        ).model_dump_json(),
                    )
                )
            elif decision.action.action_type is AgentActionType.USE_TOOL:
                try:
                    tool_result = self.tool_executor.execute(
                        decision.action,
                        case,
                        player,
                        current,
                        self.clock.now(),
                    )
                except (RuleViolation, ToolCallError) as exc:
                    accepted = False
                    error_code = exc.code
                    recent_messages.append(
                        ChatMessage(
                            role=ChatRole.TOOL,
                            content=build_safe_action_feedback(
                                exc.code,
                                self.tool_executor.case_observation(
                                    case,
                                    player,
                                    current,
                                ),
                            ).model_dump_json(),
                        )
                    )
                else:
                    current = tool_result.session
                    events.extend(tool_result.events)
                    event_sequences = tuple(
                        event.sequence for event in tool_result.events
                    )
                    recent_messages.append(
                        ChatMessage(role=ChatRole.TOOL, content=tool_result.message)
                    )
                    if tool_result.score_breakdown is not None:
                        score_breakdown = tool_result.score_breakdown

            steps.append(
                self._episode_step(
                    step_index,
                    decision,
                    accepted,
                    event_sequences,
                    error_code,
                )
            )
            if current.status is CaseSessionStatus.COMPLETED:
                status = EpisodeStatus.COMPLETED
                break

        return EpisodeResult(
            episode_id=episode_id,
            variant=AgentVariant.V0,
            status=status,
            max_steps=self.config.max_steps,
            initial_session=initial_session,
            final_session=current,
            steps=tuple(steps),
            events=tuple(events),
            score_breakdown=score_breakdown,
            usage=self._aggregate_usage(
                usages,
                measurement_complete=complete_usage,
            ),
        )

    @staticmethod
    def _episode_step(
        step_index: int,
        decision: AgentDecision,
        accepted: bool,
        event_sequences: tuple[int, ...],
        error_code: str | None,
    ) -> EpisodeStep:
        return EpisodeStep(
            step_index=step_index,
            action=decision.action,
            accepted=accepted,
            event_sequences=event_sequences,
            error_code=error_code,
            llm_attempts=decision.llm_attempts,
            used_fallback=decision.used_fallback,
            repair_kind=decision.repair_kind,
            provider_usages=decision.usages,
        )

    def _failed(
        self,
        episode_id: str,
        session: CaseSessionState,
        failure_code: str,
    ) -> EpisodeResult:
        return EpisodeResult(
            episode_id=episode_id,
            variant=AgentVariant.V0,
            status=EpisodeStatus.FAILED,
            max_steps=self.config.max_steps,
            initial_session=session,
            final_session=session,
            failure_code=failure_code,
        )

    @staticmethod
    def _aggregate_usage(
        usages: list[ModelUsage],
        *,
        measurement_complete: bool = True,
    ) -> ModelUsage | None:
        if not usages:
            return None
        providers = {usage.provider_model for usage in usages}
        provider_model = providers.pop() if len(providers) == 1 else "mixed_models"
        costs = [usage.estimated_cost for usage in usages]
        currencies = {usage.cost_currency for usage in usages}
        can_aggregate_cost = bool(
            all(cost is not None for cost in costs)
            and len(currencies) == 1
            and None not in currencies
        )
        total_cost = (
            sum((cost for cost in costs if cost is not None), Decimal("0"))
            if can_aggregate_cost
            else None
        )
        cost_currency = currencies.pop() if can_aggregate_cost else None
        request_id = usages[0].provider_request_id if len(usages) == 1 else None
        fingerprints = {usage.system_fingerprint for usage in usages}
        system_fingerprint = (
            fingerprints.pop() if len(fingerprints) == 1 else None
        )
        return ModelUsage(
            provider_model=provider_model,
            input_tokens=sum(usage.input_tokens for usage in usages),
            output_tokens=sum(usage.output_tokens for usage in usages),
            cache_hit_input_tokens=sum(
                usage.cache_hit_input_tokens for usage in usages
            ),
            cache_miss_input_tokens=sum(
                usage.cache_miss_input_tokens for usage in usages
            ),
            reasoning_tokens=sum(usage.reasoning_tokens for usage in usages),
            latency_ms=float(sum(usage.latency_ms for usage in usages)),
            estimated_cost=total_cost,
            cost_currency=cost_currency,
            provider_request_id=request_id,
            system_fingerprint=system_fingerprint,
            measurement_complete=(
                measurement_complete
                and all(usage.measurement_complete for usage in usages)
            ),
        )
