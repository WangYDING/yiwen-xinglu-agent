"""Bounded, evidence-grounded reflection proposal generation.

No runtime trigger, repository write, or authority/state mutation lives here.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Iterable

from pydantic import ConfigDict, Field

from xuanyi_npc.agents.bounded_output import BoundedStructuredOutput
from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMAdapter, LLMRequest, LLMResponse
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cooperation import (
    GameNPCDecision,
    PlayerContribution,
    PlayerContributionEvaluation,
)
from xuanyi_npc.domain.cooperative_memory import MemoryUsageTrace
from xuanyi_npc.domain.cooperative_planning import AgentGoalState, AgentPlan, PlanEvaluation
from xuanyi_npc.domain.reflection import (
    EvidenceRef,
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionEvidenceBundle,
    ReflectionFinding,
    ReflectionFindingType,
    ReflectionProposal,
    ReflectionTrigger,
    ReusableLessonProposal,
    ReusableLessonType,
)
from xuanyi_npc.evaluation import AgentRepairKind, ModelUsage


REFLECTION_SYSTEM_PROMPT = """你是合作式游戏 NPC 的结果反思模块。只输出 ReflectionProposal JSON。
AUTHORITATIVE_EVIDENCE：Observation delta、Tool outcome、Assessment、PlanEvaluation，是结果判断的权威依据。
AGENT_HISTORY：Goal、Plan、Decision/Action 与公开理由，只说明 Agent 当时的意图和行为。
USER_BELIEF：PlayerContribution 只是玩家观点，不能当作世界事实。
HISTORICAL_MEMORY_USAGE：MemoryUsageTrace 只是可审计使用记录；只有 accepted_used_memory_ids 非空才能称记忆有帮助。
只能依据给出的 evidence_refs。每个 finding/lesson 必须原样引用 bundle 中完整 EvidenceRef，并使用证据的公开安全摘要支持结论。
不得创造诊断正确性、治疗效果或其他事实；不得输出 ToolCall、repository write 或 authority override。
无法形成可靠结论时输出空 findings 和空 reusable_lesson_candidates。"""


class PublicOutcomeEvidence(DomainModel):
    """Already-projected public Tool/CaseEngine outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome_id: Identifier
    public_summary: NonEmptyText


class PublicObservationDeltaEvidence(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    delta_id: Identifier
    public_summary: NonEmptyText


class PublicAssessmentEvidence(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assessment_id: Identifier
    public_summary: NonEmptyText


class ReflectionGenerationResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal: ReflectionProposal
    attempts: int = Field(ge=1, le=2)
    used_fallback: bool
    repair_kind: AgentRepairKind | None = None
    usages: tuple[ModelUsage, ...] = ()


class ReflectionEvidenceBuilder:
    """Project stable, ownership-bound refs from public cooperative records."""

    def build(
        self,
        trigger: ReflectionTrigger,
        *,
        goals: Iterable[AgentGoalState] = (),
        plans: Iterable[AgentPlan] = (),
        plan_evaluations: Iterable[PlanEvaluation] = (),
        decisions: Iterable[GameNPCDecision] = (),
        tool_outcomes: Iterable[PublicOutcomeEvidence] = (),
        observation_deltas: Iterable[PublicObservationDeltaEvidence] = (),
        player_contributions: Iterable[PlayerContribution] = (),
        contribution_evaluations: Iterable[PlayerContributionEvaluation] = (),
        memory_usage_traces: Iterable[MemoryUsageTrace] = (),
        assessments: Iterable[PublicAssessmentEvidence] = (),
    ) -> ReflectionEvidenceBundle:
        episode_id, case_id = trigger.episode_id, trigger.case_id
        refs: list[EvidenceRef] = []

        def add(ref_type: EvidenceRefType, source_id: str, summary: str) -> None:
            refs.append(
                EvidenceRef(
                    ref_type=ref_type,
                    ref_id=self._stable_ref_id(ref_type, source_id),
                    episode_id=episode_id,
                    case_id=case_id,
                    public_summary=summary,
                )
            )

        for goal in goals:
            add(EvidenceRefType.GOAL, goal.goal_id, goal.public_description)
        for plan in plans:
            add(
                EvidenceRefType.PLAN,
                plan.plan_id,
                self._json_summary(
                    {"status": plan.status.value, "steps": [step.public_summary for step in plan.steps]}
                ),
            )
            for step in plan.steps:
                add(EvidenceRefType.PLAN_STEP, step.step_id, step.public_summary)
        for evaluation in plan_evaluations:
            add(EvidenceRefType.PLAN_EVALUATION, evaluation.evaluation_id, evaluation.public_summary)
        for decision in decisions:
            action = decision.proposal.action
            add(
                EvidenceRefType.ACTION,
                action.action_id,
                self._json_summary(
                    {
                        "capability": decision.proposal.capability.value,
                        "dialogue": action.dialogue,
                        "public_rationale": decision.proposal.explanation,
                    }
                ),
            )
        for outcome in tool_outcomes:
            add(EvidenceRefType.TOOL_OUTCOME, outcome.outcome_id, outcome.public_summary)
        for delta in observation_deltas:
            add(EvidenceRefType.OBSERVATION_DELTA, delta.delta_id, delta.public_summary)
        for contribution in player_contributions:
            if contribution.case_id != case_id:
                raise ValueError("player contribution belongs to another case")
            add(EvidenceRefType.PLAYER_CONTRIBUTION, contribution.contribution_id, contribution.public_text)
        for evaluation in contribution_evaluations:
            add(EvidenceRefType.CONTRIBUTION_EVALUATION, evaluation.contribution_id, evaluation.explanation)
        for trace in memory_usage_traces:
            source_id = trace.retrieval_id or self._digest(trace.model_dump_json())
            add(
                EvidenceRefType.MEMORY_USAGE_TRACE,
                source_id,
                self._json_summary(
                    {
                        "retrieval_status": trace.retrieval_status.value,
                        "selected_memory_ids": trace.selected_memory_ids,
                        "accepted_used_memory_ids": trace.accepted_used_memory_ids,
                        "attribution_status": trace.attribution_status.value,
                        "public_effect_summary": trace.public_effect_summary,
                    }
                ),
            )
        for assessment in assessments:
            add(EvidenceRefType.ASSESSMENT, assessment.assessment_id, assessment.public_summary)
        return ReflectionEvidenceBundle(
            episode_id=episode_id,
            case_id=case_id,
            trigger=trigger,
            evidence_refs=tuple(refs),
        )

    @staticmethod
    def _stable_ref_id(ref_type: EvidenceRefType, source_id: str) -> str:
        digest = sha256(source_id.encode("utf-8")).hexdigest()[:16]
        return f"ev_{ref_type.value}_{digest}"

    @staticmethod
    def _digest(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _json_summary(value: dict[str, object]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ReflectionProposalValidationError(ValueError):
    pass


class ReflectionProposalValidator:
    """Closed-world validation against the exact safe evidence projection."""

    OUTCOME_FINDINGS = {
        ReflectionFindingType.SUCCESSFUL_STRATEGY,
        ReflectionFindingType.FAILED_STRATEGY,
        ReflectionFindingType.UNNECESSARY_ACTION,
    }

    def validate(
        self, proposal: ReflectionProposal, bundle: ReflectionEvidenceBundle
    ) -> ReflectionProposal:
        if proposal.trigger_id != bundle.trigger.trigger_id:
            raise ReflectionProposalValidationError("proposal trigger does not match evidence bundle")
        available = {(ref.ref_type, ref.ref_id): ref for ref in bundle.evidence_refs}
        for finding in proposal.findings:
            refs = self._resolve_refs(finding.evidence_refs, available)
            self._validate_finding(finding, refs)
            self._validate_grounding(finding.public_summary, refs)
        for lesson in proposal.reusable_lesson_candidates:
            refs = self._resolve_refs(lesson.evidence_refs, available)
            self._validate_lesson(lesson, refs)
            self._validate_grounding(lesson.public_safe_summary, refs)
        return proposal

    @staticmethod
    def _resolve_refs(
        refs: tuple[EvidenceRef, ...],
        available: dict[tuple[EvidenceRefType, str], EvidenceRef],
    ) -> tuple[EvidenceRef, ...]:
        resolved = []
        for ref in refs:
            actual = available.get((ref.ref_type, ref.ref_id))
            if actual is None or actual != ref:
                raise ReflectionProposalValidationError(
                    "proposal references evidence outside the bundle"
                )
            resolved.append(actual)
        return tuple(resolved)

    def _validate_finding(
        self, finding: ReflectionFinding, refs: tuple[EvidenceRef, ...]
    ) -> None:
        kinds = {ref.ref_type for ref in refs}
        if finding.finding_type in self.OUTCOME_FINDINGS:
            self._require(kinds, {EvidenceRefType.ACTION})
            self._require(kinds, {EvidenceRefType.TOOL_OUTCOME, EvidenceRefType.ASSESSMENT})
        elif finding.finding_type is ReflectionFindingType.MISSED_OR_DELAYED_EVIDENCE:
            self._require(kinds, {EvidenceRefType.PLAN, EvidenceRefType.PLAN_EVALUATION})
            self._require(
                kinds,
                {
                    EvidenceRefType.OBSERVATION_DELTA,
                    EvidenceRefType.TOOL_OUTCOME,
                    EvidenceRefType.ASSESSMENT,
                },
            )
        elif finding.finding_type is ReflectionFindingType.COOPERATION_OBSERVATION:
            self._require(
                kinds,
                {EvidenceRefType.PLAYER_CONTRIBUTION, EvidenceRefType.CONTRIBUTION_EVALUATION},
            )
        elif finding.finding_type is ReflectionFindingType.MEMORY_HELPFULNESS:
            self._validate_accepted_memory_trace(refs)

    def _validate_lesson(
        self, lesson: ReusableLessonProposal, refs: tuple[EvidenceRef, ...]
    ) -> None:
        kinds = {ref.ref_type for ref in refs}
        if lesson.lesson_type is ReusableLessonType.OUTCOME:
            self._require(kinds, {EvidenceRefType.TOOL_OUTCOME, EvidenceRefType.ASSESSMENT})
        elif lesson.lesson_type is ReusableLessonType.PLANNING:
            self._require(kinds, {EvidenceRefType.PLAN, EvidenceRefType.PLAN_EVALUATION})
        elif lesson.lesson_type is ReusableLessonType.COOPERATION:
            self._require(
                kinds,
                {EvidenceRefType.PLAYER_CONTRIBUTION, EvidenceRefType.CONTRIBUTION_EVALUATION},
            )
        elif lesson.lesson_type is ReusableLessonType.MEMORY_HELPFULNESS:
            self._validate_accepted_memory_trace(refs)

    @staticmethod
    def _require(actual: set[EvidenceRefType], allowed: set[EvidenceRefType]) -> None:
        if not actual.intersection(allowed):
            raise ReflectionProposalValidationError(
                "finding or lesson lacks required evidence type"
            )

    @staticmethod
    def _validate_accepted_memory_trace(refs: tuple[EvidenceRef, ...]) -> None:
        traces = [ref for ref in refs if ref.ref_type is EvidenceRefType.MEMORY_USAGE_TRACE]
        if not traces:
            raise ReflectionProposalValidationError(
                "memory helpfulness requires memory usage trace"
            )
        accepted = False
        for ref in traces:
            try:
                payload = json.loads(ref.public_summary)
                accepted = accepted or bool(payload.get("accepted_used_memory_ids"))
            except (TypeError, json.JSONDecodeError):
                pass
        if not accepted:
            raise ReflectionProposalValidationError(
                "selected-but-unused memory cannot be declared helpful"
            )

    @staticmethod
    def _validate_grounding(claim: str, refs: tuple[EvidenceRef, ...]) -> None:
        normalized_claim = ReflectionProposalValidator._normalize(claim)
        summaries = [ReflectionProposalValidator._normalize(ref.public_summary) for ref in refs]
        if not normalized_claim or not any(normalized_claim in summary for summary in summaries):
            raise ReflectionProposalValidationError(
                "specific claim is not supported by cited public evidence"
            )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()


class ReflectionProposalGenerator:
    """One model attempt, one repair, then a non-assertive empty fallback."""

    def __init__(
        self, adapter: LLMAdapter, validator: ReflectionProposalValidator | None = None
    ) -> None:
        self.output = BoundedStructuredOutput(adapter)
        self.validator = validator or ReflectionProposalValidator()

    def generate(
        self, trigger: ReflectionTrigger, bundle: ReflectionEvidenceBundle
    ) -> ReflectionGenerationResult:
        if trigger.trigger_id != bundle.trigger.trigger_id:
            raise ValueError("trigger does not match evidence bundle")
        request = self._request(trigger, bundle)
        result = self.output.run(
            request,
            parse=lambda response: self._parse(response, bundle),
            repair_request=lambda original, invalid, error: self._repair_request(
                original, invalid, error
            ),
        )
        proposal = result.output or self._fallback(trigger)
        return ReflectionGenerationResult(
            proposal=proposal,
            attempts=result.attempts,
            used_fallback=result.output is None,
            repair_kind=result.repair_kind,
            usages=result.usages,
        )

    @staticmethod
    def _request(
        trigger: ReflectionTrigger, bundle: ReflectionEvidenceBundle
    ) -> LLMRequest:
        context = (
            "reflection_trigger:\n"
            + trigger.model_dump_json(indent=2)
            + "\nreflection_evidence_bundle:\n"
            + bundle.model_dump_json(indent=2)
        )
        return LLMRequest(
            messages=(
                ChatMessage(role=ChatRole.SYSTEM, content=REFLECTION_SYSTEM_PROMPT),
                ChatMessage(role=ChatRole.USER, content=context),
            ),
            response_schema=ReflectionProposal.model_json_schema(),
        )

    def _parse(
        self, response: LLMResponse, bundle: ReflectionEvidenceBundle
    ) -> ReflectionProposal:
        proposal = ReflectionProposal.model_validate_json(response.content)
        return self.validator.validate(proposal, bundle)

    @staticmethod
    def _repair_request(
        original: LLMRequest, invalid: LLMResponse, error: Exception
    ) -> LLMRequest:
        return LLMRequest(
            messages=(
                *original.messages,
                ChatMessage(role=ChatRole.ASSISTANT, content=invalid.content),
                ChatMessage(
                    role=ChatRole.USER,
                    content=(
                        "上一 ReflectionProposal 未通过封闭 evidence 校验。仅引用 bundle "
                        "内完整 EvidenceRef，摘要使用证据中的公开文本；无法支持则删除该 "
                        "finding/lesson。只修复 JSON。校验信息：" + str(error)[:1000]
                    ),
                ),
            ),
            response_schema=original.response_schema,
        )

    @staticmethod
    def _fallback(trigger: ReflectionTrigger) -> ReflectionProposal:
        return ReflectionProposal(
            proposal_id=f"reflection_fallback_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            findings=(),
            reusable_lesson_candidates=(),
            overall_confidence=ReflectionConfidence.LOW,
        )
