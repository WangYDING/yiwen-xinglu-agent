"""Conservative consolidation of validated reflection lessons into existing memory."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable, Protocol

from xuanyi_npc.domain.cooperative_memory import MemoryUsageAttributionStatus
from xuanyi_npc.domain.curriculum import (
    StructuredMemorySourceType,
    StructuredTeachingMemoryType,
)
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.reflection import (
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionEvidenceBundle,
    ReflectionProposal,
    ReusableLessonType,
)
from xuanyi_npc.domain.reflection_memory import (
    ReflectionConsolidationResult,
    ReflectionMemoryCandidate,
    ReflectionMemoryWriteDecision,
    ReflectionMemoryWriteOutcome,
)
from xuanyi_npc.memory.canonical import canonical_json
from xuanyi_npc.memory.contracts import (
    AuthoritativeMemoryRecord,
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


class ReflectionMemoryRepository(Protocol):
    def list_memories(
        self, *, player_id: str, include_inactive: bool = True
    ) -> tuple[AuthoritativeMemoryRecord, ...]: ...

    def write_projection(
        self, source: VerifiedMemorySource, memory: AuthoritativeMemoryRecord
    ) -> ProjectionWriteResult: ...


class ReflectionMemoryCandidateBuilder:
    """Convert only validator-accepted reusable lessons; findings are ignored."""

    def __init__(self, validator: ReflectionProposalValidator | None = None) -> None:
        self.validator = validator or ReflectionProposalValidator()

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
            fingerprint_payload = {
                "player_id": player_id,
                "trigger_id": proposal.trigger_id,
                "proposal_id": proposal.proposal_id,
                "lesson": lesson.model_dump(mode="json"),
            }
            digest = sha256(
                canonical_json(fingerprint_payload).encode("utf-8")
            ).hexdigest()
            fingerprint = f"fp_{digest[:60]}"
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            ordinal = len(candidates)
            candidates.append(
                ReflectionMemoryCandidate(
                    candidate_id=f"rmc_{digest[:24]}",
                    fingerprint=fingerprint,
                    player_id=player_id,
                    source_reflection_proposal_id=proposal.proposal_id,
                    source_trigger_id=proposal.trigger_id,
                    episode_id=evidence_bundle.episode_id,
                    case_id=evidence_bundle.case_id,
                    lesson_type=lesson.lesson_type,
                    proposed_memory_type=lesson.proposed_memory_type,
                    public_safe_summary=lesson.public_safe_summary,
                    applicability_scope=lesson.applicability_scope,
                    evidence_refs=lesson.evidence_refs,
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
        clock=None,
    ) -> None:
        self.repository = repository
        self.candidate_builder = candidate_builder or ReflectionMemoryCandidateBuilder()
        self.write_policy = write_policy or ReflectionMemoryWritePolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

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
        return ReflectionConsolidationResult(
            reflection_proposal_id=proposal.proposal_id,
            trigger_id=proposal.trigger_id,
            candidate_ids=tuple(item.candidate_id for item in candidates),
            written_memory_ids=tuple(written_ids),
            decisions=tuple(decisions),
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
        source_sequence = int(candidate.fingerprint.removeprefix("fp_")[:8], 16) % 2_000_000_000 + 1
        return projector.project_structured_teaching_fact(
            player_id=candidate.player_id,
            source_session_id=candidate.episode_id,
            source_sequence=source_sequence,
            source_revision=proposal_revision,
            occurred_at=self._clock(),
            structured_memory_type=(
                StructuredTeachingMemoryType.CASE_EXPERIENCE
                if episodic
                else StructuredTeachingMemoryType.LEARNING_PATTERN
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
