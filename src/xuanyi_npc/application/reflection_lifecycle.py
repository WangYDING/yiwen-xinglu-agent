"""Lifecycle-bound orchestration for reflection and conservative consolidation."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

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
from xuanyi_npc.domain.reflection_memory import (
    ReflectionMemoryIndexStatus,
    ReflectionMemoryWriteOutcome,
)


class ReflectionLifecycleReceiptRepository(Protocol):
    def claim_reflection_trigger(self, *, trigger, player_id: str, owner_token: str): ...

    def complete_reflection_trigger(
        self, *, trigger_id: str, owner_token: str, result: ReflectionLifecycleResult
    ) -> None: ...


class ReflectionLifecycleService:
    """Run at most once for one stable trigger in this application lifecycle."""

    def __init__(
        self,
        *,
        generator: ReflectionProposalGenerator,
        consolidation_service: ReflectionMemoryConsolidationService,
        evidence_builder: ReflectionEvidenceBuilder | None = None,
        receipt_repository: ReflectionLifecycleReceiptRepository | None = None,
    ) -> None:
        self.generator = generator
        self.consolidation_service = consolidation_service
        self.evidence_builder = evidence_builder or ReflectionEvidenceBuilder()
        self.receipt_repository = receipt_repository
        self._owner_token = f"reflection_worker_{uuid4().hex}"
        self._completed: dict[str, ReflectionLifecycleResult] = {}

    def reconcile_pending_indexes(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
        embedding_dimension: int,
    ) -> tuple[ReflectionLifecycleResult, ...]:
        return self.consolidation_service.reconcile_pending_index_receipts(
            player_id=player_id,
            embedding_space_id=embedding_space_id,
            embedding_dimension=embedding_dimension,
        )

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
        persistent_claimed = False
        if self.receipt_repository is not None:
            try:
                disposition, persisted = self.receipt_repository.claim_reflection_trigger(
                    trigger=trigger,
                    player_id=player_id,
                    owner_token=self._owner_token,
                )
            except Exception:
                return ReflectionLifecycleResult(
                    trigger_id=trigger.trigger_id,
                    trigger_type=trigger.trigger_type,
                    status=ReflectionLifecycleStatus.FAILED_SAFE,
                    proposal_status=ReflectionProposalStatus.FAILED_SAFE,
                    reflection_attempt_count=0,
                    error_code="reflection_receipt_claim_failed",
                )
            if disposition == "replay" and persisted is not None:
                return persisted.model_copy(
                    update={
                        "status": ReflectionLifecycleStatus.IDEMPOTENT_REPLAY,
                        "reflection_attempt_count": 0,
                        "written_memory_ids": (),
                        "public_consolidation_summary": None,
                    }
                )
            if disposition in {"in_progress", "interrupted"}:
                return ReflectionLifecycleResult(
                    trigger_id=trigger.trigger_id,
                    trigger_type=trigger.trigger_type,
                    status=ReflectionLifecycleStatus.FAILED_SAFE,
                    proposal_status=ReflectionProposalStatus.FAILED_SAFE,
                    reflection_attempt_count=0,
                    error_code=(
                        "reflection_processing_interrupted"
                        if disposition == "interrupted"
                        else "reflection_processing_in_progress"
                    ),
                )
            persistent_claimed = disposition in {"acquired", "recovered"}
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
            usage = generated.usages[-1] if generated.usages else None
            final_attempt = generated.attempt_telemetry[-1] if generated.attempt_telemetry else None
            generation_telemetry = {
                "generation_failure_stage": final_attempt.failure_stage if final_attempt else generated.failure_stage,
                "generation_failure_code": final_attempt.failure_code if final_attempt else generated.failure_code,
                "generation_exception_class": final_attempt.exception_class if final_attempt else generated.exception_class,
                "finish_reason": final_attempt.finish_reason if final_attempt else generated.finish_reason,
                "provider_request_id": usage.provider_request_id if usage else None,
                "input_tokens": sum(item.input_tokens for item in generated.usages) if generated.usages else None,
                "output_tokens": sum(item.output_tokens for item in generated.usages) if generated.usages else None,
                "configured_max_output_tokens": (
                    final_attempt.configured_max_output_tokens
                    if final_attempt else generated.configured_max_output_tokens
                ),
                "generation_attempt_count": generated.attempts,
                "repair_attempted": generated.repair_attempted,
                "repair_succeeded": generated.repair_succeeded,
                "generation_attempts": generated.attempt_telemetry,
            }
            if generated.used_fallback:
                result = ReflectionLifecycleResult(
                    trigger_id=trigger.trigger_id,
                    trigger_type=trigger.trigger_type,
                    status=ReflectionLifecycleStatus.FALLBACK,
                    proposal_status=ReflectionProposalStatus.FALLBACK_EMPTY,
                    reflection_attempt_count=generated.attempts,
                    repaired=generated.repair_succeeded,
                    provenance_ref_ids=tuple(ref.ref_id for ref in bundle.evidence_refs),
                    error_code="reflection_generation_fallback",
                    **generation_telemetry,
                )
            else:
                consolidated = self.consolidation_service.consolidate(
                    player_id=player_id,
                    proposal=generated.proposal,
                    evidence_bundle=bundle,
                )
                written = consolidated.written_memory_ids
                repository_failed = any(
                    item.outcome is ReflectionMemoryWriteOutcome.REPOSITORY_FAILURE
                    for item in consolidated.decisions
                )
                if repository_failed:
                    lifecycle_status = ReflectionLifecycleStatus.REPOSITORY_FAILURE
                    lifecycle_error = "reflection_repository_write_failed"
                elif consolidated.index_status is ReflectionMemoryIndexStatus.PENDING:
                    lifecycle_status = ReflectionLifecycleStatus.INDEX_PENDING
                    lifecycle_error = consolidated.index_error_code
                elif written:
                    lifecycle_status = ReflectionLifecycleStatus.COMPLETED
                    lifecycle_error = None
                else:
                    lifecycle_status = ReflectionLifecycleStatus.NO_WRITE
                    lifecycle_error = None
                result = ReflectionLifecycleResult(
                    trigger_id=trigger.trigger_id,
                    trigger_type=trigger.trigger_type,
                    status=lifecycle_status,
                    proposal_status=ReflectionProposalStatus.VALID,
                    reflection_attempt_count=generated.attempts,
                    repaired=generated.repair_succeeded,
                    candidate_ids=consolidated.candidate_ids,
                    written_memory_ids=written,
                    write_decisions=consolidated.decisions,
                    provenance_ref_ids=tuple(ref.ref_id for ref in bundle.evidence_refs),
                    public_consolidation_summary=(
                        "NPC 从本次经历中沉淀了一条可复用经验。"
                        if written
                        else None
                    ),
                    index_status=consolidated.index_status,
                    error_code=lifecycle_error,
                    **generation_telemetry,
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
        if persistent_claimed and self.receipt_repository is not None:
            try:
                self.receipt_repository.complete_reflection_trigger(
                    trigger_id=trigger.trigger_id,
                    owner_token=self._owner_token,
                    result=result,
                )
            except Exception:
                result = result.model_copy(
                    update={
                        "status": ReflectionLifecycleStatus.FAILED_SAFE,
                        "error_code": "reflection_receipt_finalize_failed",
                    }
                )
                self._completed[trigger.trigger_id] = result
        return result
