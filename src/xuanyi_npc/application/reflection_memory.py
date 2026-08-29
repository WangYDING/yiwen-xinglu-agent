"""Conservative consolidation of validated reflection lessons into existing memory."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable, Protocol

from xuanyi_npc.domain.cooperative_memory import MemoryUsageAttributionStatus
from xuanyi_npc.domain.memory_taxonomy import (
    StructuredMemorySourceType,
    StructuredMemoryType,
)
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.reflection import (
    ApplicabilityScope,
    ApplicabilityScopeType,
    EvidenceRef,
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionEvidenceBundle,
    ReflectionProposal,
    ReusableLessonType,
    ReusableLessonProposal,
)
from xuanyi_npc.domain.reflection_lifecycle import (
    ReflectionLifecycleResult,
    ReflectionLifecycleStatus,
    ReflectionProposalStatus,
)
from xuanyi_npc.domain.reflection_memory import (
    ReflectionConsolidationResult,
    ReflectionMemoryIndexStatus,
    ReflectionMemoryCandidate,
    ReflectionMemoryWriteDecision,
    ReflectionMemoryWriteOutcome,
)
from xuanyi_npc.memory.canonical import canonical_json
from xuanyi_npc.memory.contracts import (
    AuthoritativeMemoryRecord,
    MemoryStatus,
    ProjectionWriteDisposition,
    ProjectionWriteResult,
    VerifiedMemorySource,
)
from xuanyi_npc.memory.projection import DeterministicMemoryProjector

from .reflection import ReflectionProposalValidator


REFLECTION_MEMORY_PROJECTION_VERSION = "reflection_memory_v1"
MAX_REFLECTION_CANDIDATES = 3
MAX_PERSISTED_PER_REFLECTION = 3
_WHITESPACE = re.compile(r"\s+")
_RECOVERABLE_INDEX_ERRORS = frozenset(
    {
        "embedding_contract_error",
        "embedding_error",
        "embedding_space_mismatch",
        "embedding_vector_invalid",
        "local_embedding_error",
        "local_embedding_inference_failed",
        "memory_embedding_conflict",
        "memory_index_incomplete",
        "reflection_memory_index_failed",
        "reflection_memory_index_incomplete",
    }
)


class ReflectionMemoryRepository(Protocol):
    def list_memories(
        self, *, player_id: str, include_inactive: bool = True
    ) -> tuple[AuthoritativeMemoryRecord, ...]: ...

    def write_projection(
        self, source: VerifiedMemorySource, memory: AuthoritativeMemoryRecord
    ) -> ProjectionWriteResult: ...

    def get_memory(self, *, player_id: str, memory_id: str): ...

    def get_embedding(
        self, *, player_id: str, memory_id: str, embedding_space_id: str
    ): ...

    def list_pending_reflection_index_receipts(
        self, *, player_id: str
    ) -> tuple[ReflectionLifecycleResult, ...]: ...

    def reconcile_reflection_index_receipt(
        self,
        *,
        player_id: str,
        trigger_id: str,
        expected: ReflectionLifecycleResult,
        reconciled: ReflectionLifecycleResult,
    ) -> str: ...


class ReflectionMemoryIndexService(Protocol):
    def index_player(self, *, player_id: str): ...


class DeterministicLessonRenderer:
    """Render validated public lesson structure without trusting model-authored prose."""

    _SCOPE_LABELS = {
        ApplicabilityScopeType.SIMILAR_PUBLIC_SYMPTOM_PATTERN: "相似公开观察模式",
        ApplicabilityScopeType.SIMILAR_GOAL_TYPE: "相似公开目标类型",
        ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR: "相似玩家合作模式",
        ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN: "相似公开工具结果模式",
    }
    _LESSON_LABELS = {
        ReusableLessonType.OUTCOME: "结果经验",
        ReusableLessonType.PLANNING: "规划经验",
        ReusableLessonType.COOPERATION: "合作经验",
        ReusableLessonType.MEMORY_HELPFULNESS: "记忆使用经验",
    }
    _AUTHORITATIVE = {
        EvidenceRefType.TOOL_OUTCOME,
        EvidenceRefType.OBSERVATION_DELTA,
        EvidenceRefType.PLAN_EVALUATION,
        EvidenceRefType.CONTRIBUTION_EVALUATION,
        EvidenceRefType.ASSESSMENT,
    }

    def render(
        self, lesson: ReusableLessonProposal
    ) -> tuple[str, ApplicabilityScope, tuple[EvidenceRef, ...]]:
        refs = tuple(sorted(lesson.evidence_refs, key=lambda item: (item.ref_type.value, item.ref_id)))
        scope = self.canonical_scope(lesson.applicability_scope)
        facts = self._facts(lesson.lesson_type, refs)
        if not facts:
            raise ValueError("validated lesson has no renderable public evidence")
        text = "；".join(
            (
                "历史经验参考（不是当前世界事实）",
                f"类别：{self._LESSON_LABELS[lesson.lesson_type]}",
                "公开依据：" + "；".join(facts),
                f"适用范围：{self._SCOPE_LABELS[scope.scope_type]}[{','.join(scope.public_pattern_tags)}]",
                "限制：仅在出现相同公开结构且与当前公开观察不冲突时参考，不保证产生相同结果",
            )
        ) + "。"
        return text, scope, refs

    @staticmethod
    def canonical_scope(scope: ApplicabilityScope) -> ApplicabilityScope:
        tags = tuple(sorted(set(scope.public_pattern_tags)))
        label = DeterministicLessonRenderer._SCOPE_LABELS.get(scope.scope_type)
        if label is None:
            raise ValueError("scope has no trusted deterministic renderer")
        return ApplicabilityScope(
            scope_type=scope.scope_type,
            public_case_stage=None,
            public_pattern_tags=tags,
            limitation=f"仅在{label}相同且不与当前公开观察冲突时参考，不保证相同结果。",
        )

    def _facts(
        self, lesson_type: ReusableLessonType, refs: tuple[EvidenceRef, ...]
    ) -> tuple[str, ...]:
        facts: list[str] = []
        if lesson_type is ReusableLessonType.OUTCOME:
            actions = [item for item in refs if item.ref_type is EvidenceRefType.ACTION]
            for item in actions:
                facts.append("公开行为=" + self._public_action_identity(item))
            facts.extend(self._authoritative_facts(refs, exclude={EvidenceRefType.PLAN_EVALUATION, EvidenceRefType.CONTRIBUTION_EVALUATION}))
        elif lesson_type is ReusableLessonType.PLANNING:
            for item in refs:
                if item.ref_type in {EvidenceRefType.PLAN, EvidenceRefType.PLAN_STEP}:
                    facts.append(f"{item.ref_type.value}={item.public_summary}")
            facts.extend(self._authoritative_facts(refs, exclude={EvidenceRefType.CONTRIBUTION_EVALUATION}))
        elif lesson_type is ReusableLessonType.COOPERATION:
            facts.extend(
                f"contribution_evaluation={item.public_summary}"
                for item in refs
                if item.ref_type is EvidenceRefType.CONTRIBUTION_EVALUATION
            )
            facts.extend(self._authoritative_facts(refs, exclude={EvidenceRefType.CONTRIBUTION_EVALUATION, EvidenceRefType.PLAN_EVALUATION}))
        else:
            for item in refs:
                if item.ref_type is EvidenceRefType.MEMORY_USAGE_TRACE:
                    accepted = self._accepted_memory_ids(item)
                    facts.append("accepted_used_memory_ids=" + ",".join(accepted))
            facts.extend(self._authoritative_facts(refs, exclude={EvidenceRefType.CONTRIBUTION_EVALUATION}))
        return tuple(facts)

    def _authoritative_facts(
        self, refs: tuple[EvidenceRef, ...], *, exclude: set[EvidenceRefType]
    ) -> tuple[str, ...]:
        return tuple(
            f"{item.ref_type.value}={item.public_summary}"
            for item in refs
            if item.ref_type in self._AUTHORITATIVE and item.ref_type not in exclude
        )

    @staticmethod
    def _public_action_identity(ref: EvidenceRef) -> str:
        try:
            payload = json.loads(ref.public_summary)
        except (TypeError, json.JSONDecodeError):
            return ref.ref_id
        capability = payload.get("capability")
        return str(capability) if isinstance(capability, str) and capability else ref.ref_id

    @staticmethod
    def _accepted_memory_ids(ref: EvidenceRef) -> tuple[str, ...]:
        try:
            payload = json.loads(ref.public_summary)
        except (TypeError, json.JSONDecodeError):
            return ()
        values = payload.get("accepted_used_memory_ids")
        if not isinstance(values, list):
            return ()
        return tuple(sorted(str(value) for value in values if isinstance(value, str) and value))


class ReflectionMemoryCandidateBuilder:
    """Convert only validator-accepted reusable lessons; findings are ignored."""

    def __init__(
        self,
        validator: ReflectionProposalValidator | None = None,
        renderer: DeterministicLessonRenderer | None = None,
    ) -> None:
        self.validator = validator or ReflectionProposalValidator()
        self.renderer = renderer or DeterministicLessonRenderer()

    def build(
        self,
        *,
        player_id: str,
        proposal: ReflectionProposal,
        evidence_bundle: ReflectionEvidenceBundle,
    ) -> tuple[ReflectionMemoryCandidate, ...]:
        self.validator.validate(proposal, evidence_bundle)
        candidates = []
        seen_fingerprints: set[str] = set()
        for lesson in proposal.reusable_lesson_candidates:
            if len(candidates) >= MAX_REFLECTION_CANDIDATES:
                break
            if len(lesson.evidence_refs) > 8:
                continue
            ordinal = len(candidates)
            canonical_summary, canonical_scope, canonical_refs = self.renderer.render(lesson)
            fingerprint_payload = {
                "player_id": player_id,
                "trigger_id": proposal.trigger_id,
                "proposal_id": proposal.proposal_id,
                "lesson_type": lesson.lesson_type.value,
                "public_safe_summary": canonical_summary,
                "applicability_scope": canonical_scope.model_dump(mode="json"),
                "evidence_refs": [item.model_dump(mode="json") for item in canonical_refs],
                "confidence": lesson.confidence.value,
                "proposed_memory_type": lesson.proposed_memory_type.value,
            }
            digest = sha256(
                canonical_json(fingerprint_payload).encode("utf-8")
            ).hexdigest()
            fingerprint = f"fp_{digest[:60]}"
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            identity_digest = sha256(
                canonical_json(
                    {
                        "player_id": player_id,
                        "trigger_id": proposal.trigger_id,
                        "candidate_ordinal": ordinal,
                    }
                ).encode("utf-8")
            ).hexdigest()
            candidates.append(
                ReflectionMemoryCandidate(
                    candidate_id=f"rmc_{identity_digest[:24]}",
                    fingerprint=fingerprint,
                    player_id=player_id,
                    source_reflection_proposal_id=proposal.proposal_id,
                    source_trigger_id=proposal.trigger_id,
                    episode_id=evidence_bundle.episode_id,
                    case_id=evidence_bundle.case_id,
                    lesson_type=lesson.lesson_type,
                    proposed_memory_type=lesson.proposed_memory_type,
                    public_safe_summary=canonical_summary,
                    applicability_scope=canonical_scope,
                    evidence_refs=canonical_refs,
                    reflection_confidence=lesson.confidence,
                    candidate_ordinal=ordinal,
                )
            )
        return tuple(candidates)


class ReflectionMemoryWritePolicy:
    """Prefer rejection over writing weak, broad, conflicting, or duplicate lessons."""

    AUTHORITATIVE_TYPES = {
        EvidenceRefType.TOOL_OUTCOME,
        EvidenceRefType.OBSERVATION_DELTA,
        EvidenceRefType.PLAN_EVALUATION,
        EvidenceRefType.ASSESSMENT,
    }

    def evaluate(
        self,
        candidate: ReflectionMemoryCandidate,
        *,
        player_id: str,
        active_memories: Iterable[AuthoritativeMemoryRecord],
        conflicting_memory_ids: frozenset[str] = frozenset(),
    ) -> ReflectionMemoryWriteDecision:
        if candidate.player_id != player_id:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_OWNERSHIP, "player_ownership_mismatch")
        if candidate.proposed_memory_type not in {MemoryType.EPISODIC, MemoryType.LEARNING}:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_UNSAFE, "memory_type_not_retrievable")
        if candidate.reflection_confidence is ReflectionConfidence.LOW:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "low_reflection_confidence")
        if len(candidate.evidence_refs) < 2:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "insufficient_provenance")
        evidence_types = {item.ref_type for item in candidate.evidence_refs}
        if not evidence_types.intersection(self.AUTHORITATIVE_TYPES):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "no_authoritative_outcome_evidence")
        if candidate.lesson_type is ReusableLessonType.OUTCOME and not evidence_types.intersection(
            {EvidenceRefType.TOOL_OUTCOME, EvidenceRefType.ASSESSMENT}
        ):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "outcome_not_grounded")
        if candidate.lesson_type is ReusableLessonType.PLANNING and not evidence_types.intersection(
            {EvidenceRefType.PLAN, EvidenceRefType.PLAN_EVALUATION}
        ):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "planning_not_grounded")
        if candidate.lesson_type is ReusableLessonType.COOPERATION and EvidenceRefType.CONTRIBUTION_EVALUATION not in evidence_types:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "cooperation_not_evaluated")
        if len(candidate.applicability_scope.public_pattern_tags) > 3:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_SCOPE_TOO_BROAD, "too_many_scope_tags")
        if len(self._normalize(candidate.public_safe_summary)) < 16:
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "lesson_is_too_generic")
        if self._promotes_player_belief(candidate):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_UNSAFE, "player_belief_is_not_fact")
        if self._claims_unaccepted_memory_helpfulness(candidate):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE, "memory_usage_not_accepted")

        active = tuple(active_memories)
        if any(item.player_id != player_id for item in active):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_OWNERSHIP, "repository_player_isolation_failure")
        if conflicting_memory_ids.intersection(item.memory_id for item in active):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.REJECT_CONFLICT, "active_memory_conflict")
        normalized = self._normalize(candidate.public_safe_summary)
        if any(
            item.memory_type is candidate.proposed_memory_type
            and self._normalize(item.content) == normalized
            for item in active
        ):
            return self._reject(candidate, ReflectionMemoryWriteOutcome.SKIP_DUPLICATE, "equivalent_active_memory")
        return ReflectionMemoryWriteDecision(
            candidate_id=candidate.candidate_id,
            outcome=ReflectionMemoryWriteOutcome.WRITE_NEW,
            reason_code="validated_reflection_lesson",
        )

    @staticmethod
    def _reject(
        candidate: ReflectionMemoryCandidate,
        outcome: ReflectionMemoryWriteOutcome,
        reason: str,
    ) -> ReflectionMemoryWriteDecision:
        return ReflectionMemoryWriteDecision(
            candidate_id=candidate.candidate_id,
            outcome=outcome,
            reason_code=reason,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return _WHITESPACE.sub("", value).casefold()

    def _promotes_player_belief(self, candidate: ReflectionMemoryCandidate) -> bool:
        contributions = [
            ref
            for ref in candidate.evidence_refs
            if ref.ref_type is EvidenceRefType.PLAYER_CONTRIBUTION
        ]
        if not contributions:
            return False
        evaluations = {
            self._normalize(ref.public_summary)
            for ref in candidate.evidence_refs
            if ref.ref_type is EvidenceRefType.CONTRIBUTION_EVALUATION
        }
        summary = self._normalize(candidate.public_safe_summary)
        return any(
            summary in self._normalize(ref.public_summary) for ref in contributions
        ) and not any(summary in value for value in evaluations)

    @staticmethod
    def _claims_unaccepted_memory_helpfulness(
        candidate: ReflectionMemoryCandidate,
    ) -> bool:
        traces = [
            ref
            for ref in candidate.evidence_refs
            if ref.ref_type is EvidenceRefType.MEMORY_USAGE_TRACE
        ]
        if not traces:
            return False
        for ref in traces:
            try:
                payload = json.loads(ref.public_summary)
            except json.JSONDecodeError:
                continue
            if (
                payload.get("attribution_status")
                == MemoryUsageAttributionStatus.ACCEPTED.value
                and payload.get("accepted_used_memory_ids")
            ):
                return False
        return True


class ReflectionMemoryConsolidationService:
    """Validate, decide, project through the existing repository, and audit."""

    def __init__(
        self,
        *,
        repository: ReflectionMemoryRepository,
        candidate_builder: ReflectionMemoryCandidateBuilder | None = None,
        write_policy: ReflectionMemoryWritePolicy | None = None,
        index_service: ReflectionMemoryIndexService | None = None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.candidate_builder = candidate_builder or ReflectionMemoryCandidateBuilder()
        self.write_policy = write_policy or ReflectionMemoryWritePolicy()
        self.index_service = index_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def reconcile_pending_index_receipts(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
        embedding_dimension: int,
    ) -> tuple[ReflectionLifecycleResult, ...]:
        """Finalize only receipts whose written memories are ready in this space."""

        reconciled_results: list[ReflectionLifecycleResult] = []
        pending = self.repository.list_pending_reflection_index_receipts(
            player_id=player_id
        )
        for result in pending:
            if (
                result.status is not ReflectionLifecycleStatus.INDEX_PENDING
                or result.index_status is not ReflectionMemoryIndexStatus.PENDING
                or result.proposal_status is not ReflectionProposalStatus.VALID
                or not result.written_memory_ids
                or result.error_code not in _RECOVERABLE_INDEX_ERRORS
            ):
                continue
            ready = True
            for memory_id in result.written_memory_ids:
                try:
                    memory = self.repository.get_memory(
                        player_id=player_id,
                        memory_id=memory_id,
                    )
                    embedding = self.repository.get_embedding(
                        player_id=player_id,
                        memory_id=memory_id,
                        embedding_space_id=embedding_space_id,
                    )
                except Exception:
                    ready = False
                    break
                if (
                    memory.status is not MemoryStatus.ACTIVE
                    or embedding.player_id != player_id
                    or embedding.embedding_space_id != embedding_space_id
                    or embedding.dimension != embedding_dimension
                    or embedding.content_hash != memory.content_hash
                ):
                    ready = False
                    break
            if not ready:
                continue
            updated = result.model_copy(
                update={
                    "status": ReflectionLifecycleStatus.COMPLETED,
                    "index_status": ReflectionMemoryIndexStatus.COMPLETE,
                    "error_code": None,
                    "index_reconciled": True,
                    "previous_index_status": result.index_status,
                    "previous_error_code": result.error_code,
                    "index_reconciliation_embedding_space_id": embedding_space_id,
                    "index_reconciled_memory_ids": result.written_memory_ids,
                    "index_reconciled_at": self._clock(),
                }
            )
            disposition = self.repository.reconcile_reflection_index_receipt(
                player_id=player_id,
                trigger_id=result.trigger_id,
                expected=result,
                reconciled=updated,
            )
            if disposition in {"updated", "idempotent"}:
                reconciled_results.append(updated)
        return tuple(reconciled_results)

    def consolidate(
        self,
        *,
        player_id: str,
        proposal: ReflectionProposal,
        evidence_bundle: ReflectionEvidenceBundle,
        conflicting_memory_ids: frozenset[str] = frozenset(),
    ) -> ReflectionConsolidationResult:
        candidates = self.candidate_builder.build(
            player_id=player_id,
            proposal=proposal,
            evidence_bundle=evidence_bundle,
        )
        decisions: list[ReflectionMemoryWriteDecision] = []
        written_ids: list[str] = []
        for candidate in candidates:
            active = self.repository.list_memories(
                player_id=player_id, include_inactive=False
            )
            decision = self.write_policy.evaluate(
                candidate,
                player_id=player_id,
                active_memories=active,
                conflicting_memory_ids=conflicting_memory_ids,
            )
            if decision.outcome is not ReflectionMemoryWriteOutcome.WRITE_NEW:
                decisions.append(decision)
                continue
            if len(written_ids) >= MAX_PERSISTED_PER_REFLECTION:
                decisions.append(
                    ReflectionMemoryWriteDecision(
                        candidate_id=candidate.candidate_id,
                        outcome=ReflectionMemoryWriteOutcome.REJECT_WEAK_EVIDENCE,
                        reason_code="reflection_write_limit_reached",
                    )
                )
                continue
            try:
                source, memory = self._project(candidate, proposal.proposal_revision)
                result = self.repository.write_projection(source, memory)
            except Exception:
                decisions.append(
                    ReflectionMemoryWriteDecision(
                        candidate_id=candidate.candidate_id,
                        outcome=ReflectionMemoryWriteOutcome.REPOSITORY_FAILURE,
                        reason_code="repository_write_failed",
                    )
                )
                continue
            if result.disposition is ProjectionWriteDisposition.CREATED:
                written_ids.append(result.memory_id)
                decisions.append(
                    ReflectionMemoryWriteDecision(
                        candidate_id=candidate.candidate_id,
                        outcome=ReflectionMemoryWriteOutcome.WRITE_NEW,
                        reason_code="repository_created",
                        memory_id=result.memory_id,
                    )
                )
            else:
                decisions.append(
                    ReflectionMemoryWriteDecision(
                        candidate_id=candidate.candidate_id,
                        outcome=ReflectionMemoryWriteOutcome.SKIP_DUPLICATE,
                        reason_code="repository_idempotent",
                    )
                )
        index_status = ReflectionMemoryIndexStatus.NOT_REQUIRED
        index_error_code = None
        if written_ids and self.index_service is not None:
            try:
                index_result = self.index_service.index_player(player_id=player_id)
                if index_result.state.status.value != "complete":
                    index_status = ReflectionMemoryIndexStatus.PENDING
                    index_error_code = "reflection_memory_index_incomplete"
                else:
                    index_status = ReflectionMemoryIndexStatus.COMPLETE
            except Exception as exc:
                index_status = ReflectionMemoryIndexStatus.PENDING
                index_error_code = getattr(exc, "code", "reflection_memory_index_failed")
        return ReflectionConsolidationResult(
            reflection_proposal_id=proposal.proposal_id,
            trigger_id=proposal.trigger_id,
            candidate_ids=tuple(item.candidate_id for item in candidates),
            written_memory_ids=tuple(written_ids),
            decisions=tuple(decisions),
            index_status=index_status,
            index_error_code=index_error_code,
        )

    def _project(
        self, candidate: ReflectionMemoryCandidate, proposal_revision: int
    ) -> tuple[VerifiedMemorySource, AuthoritativeMemoryRecord]:
        episodic = candidate.proposed_memory_type is MemoryType.EPISODIC
        projector = DeterministicMemoryProjector(
            projection_version=REFLECTION_MEMORY_PROJECTION_VERSION,
            projection_ordinal=0,
        )
        provenance_ids = tuple(
            sorted(
                {
                    candidate.source_trigger_id,
                    *(ref.ref_id for ref in candidate.evidence_refs),
                }
            )
        )
        source_sequence = int(
            sha256(candidate.candidate_id.encode("utf-8")).hexdigest()[:8], 16
        ) % 2_000_000_000 + 1
        return projector.project_structured_experience(
            player_id=candidate.player_id,
            source_session_id=candidate.episode_id,
            source_sequence=source_sequence,
            source_revision=proposal_revision,
            occurred_at=self._clock(),
            structured_memory_type=(
                StructuredMemoryType.CASE_EXPERIENCE
                if episodic
                else StructuredMemoryType.LEARNING_PATTERN
            ),
            source_type=(
                StructuredMemorySourceType.CASE_COMPLETION
                if episodic
                else StructuredMemorySourceType.ASSESSMENT
            ),
            source_reference_id=candidate.candidate_id,
            public_summary=candidate.public_safe_summary,
            reason_code="reflection_generated",
            source_case_id=candidate.case_id,
            lesson_id=candidate.source_reflection_proposal_id,
            ability_ids=provenance_ids,
        )
