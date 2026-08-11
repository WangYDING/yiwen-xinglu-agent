"""Deterministic inheritance gate, grant flow, and restricted resource access."""

import hashlib
from dataclasses import dataclass

from pydantic import ConfigDict

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.inheritance import InheritanceDecision, InheritanceDefinition
from xuanyi_npc.domain.permissions import (
    InheritanceGranted,
    KnowledgeUnlocked,
    PermissionGranted,
    PermissionLevel,
)
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage.json_store import JsonStateStore, StateNotFoundError

from .permissions import PermissionAccessError, PermissionCoordinator, RestrictedKnowledgeView
from xuanyi_npc.domain.structured_memory import RetrievedStructuredMemory


class InheritanceServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class InheritanceApplicationResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ok: bool
    code: Identifier
    message: NonEmptyText
    decision: InheritanceDecision
    granted: bool


class MentorAdvancementContext(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_id: Identifier
    teaching_stage: str
    exam_eligible: bool
    latest_exam_passed: bool | None = None
    latest_exam_score: int | None = None
    improvement_areas: tuple[Identifier, ...] = ()
    public_permissions: tuple[str, ...]
    inheritance_eligible: bool
    inheritance_public_reason_codes: tuple[Identifier, ...]
    structured_memories: tuple[RetrievedStructuredMemory, ...] = ()


@dataclass(frozen=True)
class InheritanceDecisionPolicy:
    store: JsonStateStore

    def __post_init__(self) -> None:
        definition = InheritanceDefinition.model_validate_json(
            read_runtime_text("inheritance/trace_vow_restore_v1.json")
        )
        object.__setattr__(self, "definition", definition)

    def decide(self, player_id: str) -> InheritanceDecision:
        self.store.load_player(player_id)
        apprenticeship = self.store.load_apprenticeship(player_id)
        try:
            plan = self.store.load_teaching_plan(player_id)
        except StateNotFoundError:
            return self._decision(False, ("remediation_incomplete", "exam_required", "knowledge_incomplete"), ("lessons", "exam", "knowledge"), apprenticeship.revision, 0, 0, 0)
        try:
            campaign = self.store.load_campaign(player_id)
        except StateNotFoundError:
            campaign = None
        try:
            permission = self.store.load_permission_state(player_id)
        except StateNotFoundError:
            return self._decision(False, ("exam_required",), ("exam",), apprenticeship.revision, plan.revision, campaign.revision, 0)
        reasons: list[str] = []
        categories: list[str] = []
        # Safety and unresolved teaching issues have priority over all social gates.
        blocking = set(self.definition.blocking_improvement_areas)
        if blocking.intersection(plan.unresolved_improvement_areas):
            reasons.append("ethics_unresolved")
            categories.append("conduct")
        if plan.unresolved_improvement_areas:
            reasons.append("remediation_incomplete")
            categories.append("remediation")
        if permission.passed_exam_attempt_id is None:
            reasons.append("exam_required")
            categories.append("exam")
        if permission.teaching_stage.value != self.definition.required_stage.value:
            if "exam_required" not in reasons:
                reasons.append("exam_required")
                categories.append("stage")
        effective_recognition = apprenticeship.relationship.recognition + permission.exam_recognition_bonus
        relationship_values = {
            "trust": apprenticeship.relationship.trust,
            "recognition": effective_recognition,
            "affinity": apprenticeship.relationship.affinity,
        }
        for requirement in self.definition.required_relationship:
            if relationship_values[requirement.dimension.value] < requirement.minimum_value:
                code = f"{requirement.dimension.value}_insufficient"
                reasons.append(code)
                categories.append("relationship")
        if any(
            apprenticeship.abilities[item.ability_id].proficiency < item.minimum_proficiency
            for item in self.definition.required_abilities
        ):
            reasons.append("ability_evidence_insufficient")
            categories.append("ability")
        if not set(self.definition.required_lessons).issubset(plan.completed_core_lessons):
            reasons.append("remediation_incomplete")
            categories.append("lessons")
        if campaign is None or not set(self.definition.required_knowledge_ids).issubset(campaign.unlocked_knowledge_ids):
            reasons.append("knowledge_incomplete")
            categories.append("knowledge")
        reasons = list(dict.fromkeys(reasons))
        categories = list(dict.fromkeys(categories))
        return self._decision(
            not reasons, tuple(reasons), tuple(categories),
            apprenticeship.revision, plan.revision, 0 if campaign is None else campaign.revision, permission.revision,
        )

    def _decision(self, eligible, reasons, categories, *revisions) -> InheritanceDecision:
        key = "|".join((self.definition.inheritance_id, *(str(item) for item in revisions), *reasons))
        revision = "decision_" + hashlib.sha256(key.encode()).hexdigest()[:20]
        return InheritanceDecision(
            eligible=eligible, public_reason_codes=reasons,
            missing_requirement_categories=categories,
            inheritance_id=self.definition.inheritance_id, decision_revision=revision,
        )


@dataclass(frozen=True)
class InheritanceService:
    store: JsonStateStore
    permission_coordinator: PermissionCoordinator
    clock: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy", InheritanceDecisionPolicy(self.store))
        object.__setattr__(self, "definition", self.policy.definition)

    def request(self, player_id: str) -> InheritanceApplicationResult:
        decision = self.policy.decide(player_id)
        if not decision.eligible:
            messages = tuple(self.definition.public_reason_messages[code] for code in decision.public_reason_codes)
            return InheritanceApplicationResult(
                ok=True, code="inheritance_refused", message="；".join(messages),
                decision=decision, granted=False,
            )
        state = self.store.load_permission_state(player_id)
        if self.definition.inheritance_id in state.granted_inheritance_ids:
            return InheritanceApplicationResult(
                ok=True, code="inheritance_already_granted", message="这项传承已经授予。",
                decision=decision, granted=True,
            )
        if PermissionLevel.CORE_TEACHING not in state.permissions:
            state = self.permission_coordinator._append(state, PermissionGranted(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                permission=PermissionLevel.CORE_TEACHING,
                source_reference_id=decision.decision_revision,
            ))
        if PermissionLevel.INHERITANCE not in state.permissions:
            state = self.permission_coordinator._append(state, PermissionGranted(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                permission=PermissionLevel.INHERITANCE,
                source_reference_id=decision.decision_revision,
            ))
        content = self.definition.granted_content
        if content.content_id not in state.unlocked_knowledge_ids:
            state = self.permission_coordinator._append(state, KnowledgeUnlocked(
                sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
                knowledge_id=content.content_id, permission=PermissionLevel.INHERITANCE,
                source_reference_id=decision.decision_revision,
            ))
        state = self.permission_coordinator._append(state, InheritanceGranted(
            sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            inheritance_id=self.definition.inheritance_id, content_id=content.content_id,
            decision_revision=decision.decision_revision,
        ))
        self.store.save_permission_state(state)
        return InheritanceApplicationResult(
            ok=True, code="inheritance_granted", message="玄医先生已正式授予你‘溯契还因’。",
            decision=decision, granted=True,
        )

    def request_with_explanation(self, player_id: str, explain_fn) -> InheritanceApplicationResult:
        """Keep a committed rule decision authoritative if mentor expression fails."""
        result = self.request(player_id)
        try:
            explain_fn(result.decision, result.message)
        except Exception:
            return result.model_copy(update={
                "code": "mentor_explanation_pending",
                "message": "规则结果已经提交；导师解释尚待重试。",
            })
        return result

    def read_content(self, player_id: str, content_id: str) -> RestrictedKnowledgeView:
        if content_id != self.definition.granted_content.content_id:
            raise PermissionAccessError("requested knowledge is not available")
        state = self.permission_coordinator.require(player_id, PermissionLevel.INHERITANCE)
        if content_id not in state.unlocked_knowledge_ids:
            raise PermissionAccessError("requested knowledge is not available")
        content = self.definition.granted_content
        return RestrictedKnowledgeView(
            content_id=content.content_id, title=content.public_title,
            description=content.restricted_text,
        )

    def read_mentor_secret(self, player_id: str) -> RestrictedKnowledgeView:
        self.permission_coordinator.require(player_id, PermissionLevel.MENTOR_SECRET)
        raise PermissionAccessError("requested knowledge is not available")

    def build_mentor_context(
        self, player_id: str,
        structured_memories: tuple[RetrievedStructuredMemory, ...] = (),
    ) -> MentorAdvancementContext:
        if len(structured_memories) > 3:
            raise InheritanceServiceError("mentor_memory_limit", "导师最多读取三条结构化记忆。")
        view = self.permission_coordinator.public_view(player_id)
        attempts = sorted(
            (item for item in self.store.list_exam_sessions() if item.player_id == player_id and item.result is not None),
            key=lambda item: item.attempt_number,
        )
        latest = attempts[-1].result if attempts else None
        decision = self.policy.decide(player_id)
        return MentorAdvancementContext(
            player_id=player_id, teaching_stage=view.teaching_stage.value,
            exam_eligible=view.exam_eligible,
            latest_exam_passed=None if latest is None else latest.passed,
            latest_exam_score=None if latest is None else latest.total_score,
            improvement_areas=() if latest is None else tuple(item.value for item in latest.improvement_areas),
            public_permissions=tuple(
                item.value for item in view.permissions if item is not PermissionLevel.MENTOR_SECRET
            ),
            inheritance_eligible=decision.eligible,
            inheritance_public_reason_codes=decision.public_reason_codes,
            structured_memories=structured_memories,
        )
