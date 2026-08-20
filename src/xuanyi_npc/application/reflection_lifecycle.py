"""Lifecycle-bound orchestration for reflection and conservative consolidation."""

from __future__ import annotations

from xuanyi_npc.domain.cooperation import (
    GameNPCDecision,
    PlayerContribution,
    PlayerContributionEvaluation,
)
from xuanyi_npc.domain.cooperative_memory import MemoryUsageTrace
from xuanyi_npc.domain.cooperative_planning import AgentGoalState, AgentPlan, PlanEvaluation
from xuanyi_npc.domain.reflection import ReflectionTrigger
from xuanyi_npc.domain.reflection_lifecycle import (
    ReflectionLifecycleResult,
    ReflectionLifecycleStatus,
    ReflectionProposalStatus,
)

from .reflection import (
    PublicAssessmentEvidence,
    PublicObservationDeltaEvidence,
    PublicOutcomeEvidence,
    ReflectionEvidenceBuilder,
    ReflectionProposalGenerator,
)
from .reflection_memory import ReflectionMemoryConsolidationService


class ReflectionLifecycleService:
    """Run at most once for one stable trigger in this application lifecycle."""

    def __init__(
        self,
        *,
        generator: ReflectionProposalGenerator,
        consolidation_service: ReflectionMemoryConsolidationService,
        evidence_builder: ReflectionEvidenceBuilder | None = None,
    ) -> None:
        self.generator = generator
        self.consolidation_service = consolidation_service
        self.evidence_builder = evidence_builder or ReflectionEvidenceBuilder()
        self._completed: dict[str, ReflectionLifecycleResult] = {}

    def process(
        self,
        *,
        trigger: ReflectionTrigger,
        player_id: str,
        goals: tuple[AgentGoalState, ...] = (),
        plans: tuple[AgentPlan, ...] = (),
        plan_evaluations: tuple[PlanEvaluation, ...] = (),
        decisions: tuple[GameNPCDecision, ...] = (),
        tool_outcomes: tuple[PublicOutcomeEvidence, ...] = (),
        observation_deltas: tuple[PublicObservationDeltaEvidence, ...] = (),
        player_contributions: tuple[PlayerContribution, ...] = (),
        contribution_evaluations: tuple[PlayerContributionEvaluation, ...] = (),
        memory_usage_traces: tuple[MemoryUsageTrace, ...] = (),
        assessments: tuple[PublicAssessmentEvidence, ...] = (),
    ) -> ReflectionLifecycleResult:
        prior = self._completed.get(trigger.trigger_id)
        if prior is not None:
            return prior.model_copy(
                update={
                    "status": ReflectionLifecycleStatus.IDEMPOTENT_REPLAY,
                    "reflection_attempt_count": 0,
                    "written_memory_ids": (),
                    "public_consolidation_summary": None,
                }
            )
        try:
            bundle = self.evidence_builder.build(
                trigger,
                goals=goals,
                plans=plans,
                plan_evaluations=plan_evaluations,
                decisions=decisions,
                tool_outcomes=tool_outcomes,
                observation_deltas=observation_deltas,
                player_contributions=player_contributions,
                contribution_evaluations=contribution_evaluations,
                memory_usage_traces=memory_usage_traces,
                assessments=assessments,
            )
            generated = self.generator.generate(trigger, bundle)
            if generated.used_fallback:
                result = ReflectionLifecycleResult(
                    trigger_id=trigger.trigger_id,
                    trigger_type=trigger.trigger_type,
                    status=ReflectionLifecycleStatus.FALLBACK,
                    proposal_status=ReflectionProposalStatus.FALLBACK_EMPTY,
                    reflection_attempt_count=1,
                    repaired=generated.attempts == 2,
                    provenance_ref_ids=tuple(ref.ref_id for ref in bundle.evidence_refs),
                    error_code="reflection_generation_fallback",
                )
            else:
                consolidated = self.consolidation_service.consolidate(
                    player_id=player_id,
                    proposal=generated.proposal,
                    evidence_bundle=bundle,
                )
                written = consolidated.written_memory_ids
                result = ReflectionLifecycleResult(
                    trigger_id=trigger.trigger_id,
                    trigger_type=trigger.trigger_type,
                    status=ReflectionLifecycleStatus.COMPLETED,
                    proposal_status=ReflectionProposalStatus.VALID,
                    reflection_attempt_count=1,
                    repaired=generated.attempts == 2,
                    candidate_ids=consolidated.candidate_ids,
                    written_memory_ids=written,
                    write_decisions=consolidated.decisions,
                    provenance_ref_ids=tuple(ref.ref_id for ref in bundle.evidence_refs),
                    public_consolidation_summary=(
                        "NPC 从本次经历中沉淀了一条可复用经验。"
                        if written
                        else None
                    ),
                )
        except Exception:
            result = ReflectionLifecycleResult(
                trigger_id=trigger.trigger_id,
                trigger_type=trigger.trigger_type,
                status=ReflectionLifecycleStatus.FAILED_SAFE,
                proposal_status=ReflectionProposalStatus.FAILED_SAFE,
                reflection_attempt_count=1,
                error_code="reflection_lifecycle_failed_safe",
            )
        self._completed[trigger.trigger_id] = result
        return result

