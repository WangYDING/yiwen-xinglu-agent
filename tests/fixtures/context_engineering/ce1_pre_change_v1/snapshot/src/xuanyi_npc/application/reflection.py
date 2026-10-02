"""Bounded, evidence-grounded reflection proposal generation.

No runtime trigger, repository write, or authority/state mutation lives here.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from hashlib import sha256
from typing import Iterable

from pydantic import ConfigDict, Field, ValidationError

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
    ApplicabilityScopeType,
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
from xuanyi_npc.domain.reflection_lifecycle import ReflectionGenerationAttemptTelemetry
from xuanyi_npc.agents.model_usage import AgentRepairKind, ModelUsage


REFLECTION_SYSTEM_PROMPT = """你是合作式游戏 NPC 的结果反思模块。只输出 ReflectionProposal JSON。
AUTHORITATIVE_EVIDENCE：Observation delta、Tool outcome、Assessment、PlanEvaluation，是结果判断的权威依据。
AGENT_HISTORY：Goal、Plan、Decision/Action 与公开理由，只说明 Agent 当时的意图和行为。
USER_BELIEF：PlayerContribution 只是玩家观点，不能当作世界事实。
HISTORICAL_MEMORY_USAGE：MemoryUsageTrace 只是可审计使用记录；只有 accepted_used_memory_ids 非空才能称记忆有帮助。
只能依据给出的 evidence_refs。每个 finding/lesson 必须原样引用 bundle 中完整 EvidenceRef，并使用证据的公开安全摘要支持结论。
FINDING_EVIDENCE_CONTRACT：
- successful_strategy：必须引用至少一个完整 ACTION EvidenceRef，且至少一个完整 TOOL_OUTCOME 或 ASSESSMENT EvidenceRef。
- failed_strategy：必须引用至少一个完整 ACTION EvidenceRef，且至少一个完整 TOOL_OUTCOME 或 ASSESSMENT EvidenceRef。
- unnecessary_action：必须引用至少一个完整 ACTION EvidenceRef，且至少一个完整 TOOL_OUTCOME 或 ASSESSMENT EvidenceRef。
- missed_or_delayed_evidence：必须引用至少一个 PLAN 或 PLAN_EVALUATION EvidenceRef，且至少一个 OBSERVATION_DELTA、TOOL_OUTCOME 或 ASSESSMENT EvidenceRef。
- cooperation_observation：必须引用至少一个 PLAYER_CONTRIBUTION 或 CONTRIBUTION_EVALUATION EvidenceRef。
- memory_helpfulness：必须引用 MEMORY_USAGE_TRACE EvidenceRef，且仅当其中 accepted_used_memory_ids 非空时才能生成；retrieved、selected 或 declared-used 都不代表有帮助。
ACTION 只证明 NPC 实际做了什么，不能证明 outcome；TOOL_OUTCOME、OBSERVATION_DELTA、ASSESSMENT 才能支持世界结果、成功、失败或是否必要。
FINDING_EXTRACTIVE_CONTRACT：Finding 是 extractive factual record，不是自由总结。COPY, DO NOT PARAPHRASE。
- 每个 finding.public_summary 必须从该 finding 自己引用的 grounding-eligible EvidenceRef 中选择一条，并原样完整复制该 EvidenceRef.public_summary。
- 禁止改写、同义替换、总结、合并多条 Evidence、添加前后缀、修改标点，或添加“因此”“说明”“有效”“失败”等推论。finding_type 已承担结构化分类，public_summary 只保存一条 authoritative extractive fact。
- successful_strategy、failed_strategy、unnecessary_action：summary anchor 只能是 TOOL_OUTCOME、OBSERVATION_DELTA 或 ASSESSMENT；ACTION 不得作为 summary anchor。即使选择 OBSERVATION_DELTA，evidence_refs 仍必须另外包含 TOOL_OUTCOME 或 ASSESSMENT。
- missed_or_delayed_evidence：summary anchor 只能是 PLAN_EVALUATION、TOOL_OUTCOME、OBSERVATION_DELTA 或 ASSESSMENT；PLAN 不得作为 summary anchor。
- cooperation_observation：只有存在 CONTRIBUTION_EVALUATION 时才能生成，summary 必须原样完整复制 CONTRIBUTION_EVALUATION.public_summary；PLAYER_CONTRIBUTION 只能作为 provenance，不能作为事实摘要。
- memory_helpfulness：只有 MEMORY_USAGE_TRACE.accepted_used_memory_ids 非空时才能生成，summary 必须原样完整复制该 MEMORY_USAGE_TRACE.public_summary；candidate、retrieved、selected 或 declared-used 都不代表 helpful。
- 如果没有可原样复制的 grounding anchor，不生成该 finding。
所有 EvidenceRef 必须来自当前 bundle并原样复制完整对象；不得伪造 ref_id，不得修改 public_summary。无法满足对应 requirement 时，不生成该 finding。
REUSABLE_LESSON_CONTRACT：lesson 的 public_safe_summary 与 applicability_scope.limitation 只是草稿，不会直接写入长期 Memory；Python 将根据已验证结构生成 canonical 文本。
- outcome：至少引用 TOOL_OUTCOME、OBSERVATION_DELTA、ASSESSMENT 之一；还必须引用 ACTION，或第二条独立 authoritative evidence。
- planning：必须同时引用 PLAN 或 PLAN_STEP，以及 PLAN_EVALUATION。
- cooperation：必须同时引用 PLAYER_CONTRIBUTION 与 CONTRIBUTION_EVALUATION。
- memory_helpfulness：必须引用 accepted_used_memory_ids 非空的 MEMORY_USAGE_TRACE，并引用 PLAN_EVALUATION、TOOL_OUTCOME、OBSERVATION_DELTA、ASSESSMENT 之一。
SCOPE_CONTRACT：scope_type 必须与 lesson_type 匹配。public_pattern_tags 只能原样复制所选 EvidenceRef 的 ref_id：similar_tool_outcome_pattern 使用 TOOL_OUTCOME ref_id；similar_public_symptom_pattern 使用 OBSERVATION_DELTA ref_id；similar_goal_type 使用 GOAL ref_id；similar_player_behavior 使用 CONTRIBUTION_EVALUATION ref_id。当前 bundle 不提供可验证 case stage，不使用 same_case_stage。不得创造 tag。
derived reusable lesson 使用 proposed_memory_type=learning；不得声称行动导致结果、策略必然有效或历史 Memory 是当前事实。
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
    failure_stage: str | None = None
    failure_code: str | None = None
    exception_class: str | None = None
    finish_reason: str | None = None
    configured_max_output_tokens: int | None = None
    attempt_telemetry: tuple[ReflectionGenerationAttemptTelemetry, ...] = ()
    repair_attempted: bool = False
    repair_succeeded: bool = False


class ReflectionGenerationValidationFailure(ValueError):
    def __init__(
        self,
        *,
        stage: str,
        code: str,
        source_exception_class: str,
        field_path: str | None = None,
        error_count: int | None = None,
    ) -> None:
        super().__init__(code)
        self.failure_stage = stage
        self.code = code
        self.source_exception_class = source_exception_class
        self.field_path = field_path
        self.error_count = error_count


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


class GroundingRuleCode(str, Enum):
    TRIGGER_ID_MISMATCH = "trigger_id_mismatch"
    EVIDENCE_REF_NOT_IN_BUNDLE = "evidence_ref_not_in_bundle"
    EVIDENCE_REF_PAYLOAD_MISMATCH = "evidence_ref_payload_mismatch"
    REQUIRED_ACTION_EVIDENCE_MISSING = "required_action_evidence_missing"
    REQUIRED_AUTHORITATIVE_EVIDENCE_MISSING = "required_authoritative_evidence_missing"
    REQUIRED_PLANNING_EVIDENCE_MISSING = "required_planning_evidence_missing"
    REQUIRED_COOPERATION_EVIDENCE_MISSING = "required_cooperation_evidence_missing"
    MEMORY_USAGE_TRACE_MISSING = "memory_usage_trace_missing"
    MEMORY_USAGE_NOT_ELIGIBLE = "memory_usage_not_eligible"
    CLAIM_NOT_GROUNDED = "claim_not_grounded"
    LESSON_EVIDENCE_CONTRACT_INVALID = "lesson_evidence_contract_invalid"
    LESSON_SCOPE_INVALID = "lesson_scope_invalid"
    OTHER_GROUNDING_VALIDATION = "other_grounding_validation"


class ReflectionProposalValidationError(ValueError):
    def __init__(self, message: str, grounding_rule_code: GroundingRuleCode) -> None:
        super().__init__(message)
        self.grounding_rule_code = grounding_rule_code


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
            raise ReflectionProposalValidationError(
                "proposal trigger does not match evidence bundle",
                GroundingRuleCode.TRIGGER_ID_MISMATCH,
            )
        available = {(ref.ref_type, ref.ref_id): ref for ref in bundle.evidence_refs}
        for finding in proposal.findings:
            refs = self._resolve_refs(finding.evidence_refs, available)
            self._validate_finding(finding, refs)
            self._validate_grounding(
                finding.public_summary,
                self._grounding_refs_for_finding(finding.finding_type, refs),
            )
        for lesson in proposal.reusable_lesson_candidates:
            refs = self._resolve_refs(lesson.evidence_refs, available)
            self._validate_lesson(lesson, refs)
            self._validate_lesson_scope(lesson, refs)
        return proposal

    @staticmethod
    def _resolve_refs(
        refs: tuple[EvidenceRef, ...],
        available: dict[tuple[EvidenceRefType, str], EvidenceRef],
    ) -> tuple[EvidenceRef, ...]:
        resolved = []
        for ref in refs:
            actual = available.get((ref.ref_type, ref.ref_id))
            if actual is None:
                raise ReflectionProposalValidationError(
                    "proposal references evidence outside the bundle",
                    GroundingRuleCode.EVIDENCE_REF_NOT_IN_BUNDLE,
                )
            if actual != ref:
                raise ReflectionProposalValidationError(
                    "proposal evidence payload does not match the bundle",
                    GroundingRuleCode.EVIDENCE_REF_PAYLOAD_MISMATCH,
                )
            resolved.append(actual)
        return tuple(resolved)

    def _validate_finding(
        self, finding: ReflectionFinding, refs: tuple[EvidenceRef, ...]
    ) -> None:
        kinds = {ref.ref_type for ref in refs}
        if finding.finding_type in self.OUTCOME_FINDINGS:
            self._require(
                kinds, {EvidenceRefType.ACTION},
                GroundingRuleCode.REQUIRED_ACTION_EVIDENCE_MISSING,
            )
            self._require(
                kinds, {EvidenceRefType.TOOL_OUTCOME, EvidenceRefType.ASSESSMENT},
                GroundingRuleCode.REQUIRED_AUTHORITATIVE_EVIDENCE_MISSING,
            )
        elif finding.finding_type is ReflectionFindingType.MISSED_OR_DELAYED_EVIDENCE:
            self._require(
                kinds, {EvidenceRefType.PLAN, EvidenceRefType.PLAN_EVALUATION},
                GroundingRuleCode.REQUIRED_PLANNING_EVIDENCE_MISSING,
            )
            self._require(
                kinds,
                {
                    EvidenceRefType.OBSERVATION_DELTA,
                    EvidenceRefType.TOOL_OUTCOME,
                    EvidenceRefType.ASSESSMENT,
                },
                GroundingRuleCode.REQUIRED_AUTHORITATIVE_EVIDENCE_MISSING,
            )
        elif finding.finding_type is ReflectionFindingType.COOPERATION_OBSERVATION:
            self._require(
                kinds,
                {EvidenceRefType.PLAYER_CONTRIBUTION, EvidenceRefType.CONTRIBUTION_EVALUATION},
                GroundingRuleCode.REQUIRED_COOPERATION_EVIDENCE_MISSING,
            )
        elif finding.finding_type is ReflectionFindingType.MEMORY_HELPFULNESS:
            self._validate_accepted_memory_trace(refs)

    def _validate_lesson(
        self, lesson: ReusableLessonProposal, refs: tuple[EvidenceRef, ...]
    ) -> None:
        kinds = {ref.ref_type for ref in refs}
        if lesson.lesson_type is ReusableLessonType.OUTCOME:
            self._require(
                kinds,
                {
                    EvidenceRefType.TOOL_OUTCOME,
                    EvidenceRefType.OBSERVATION_DELTA,
                    EvidenceRefType.ASSESSMENT,
                },
                GroundingRuleCode.REQUIRED_AUTHORITATIVE_EVIDENCE_MISSING,
            )
            authoritative_count = sum(
                ref.ref_type
                in {
                    EvidenceRefType.TOOL_OUTCOME,
                    EvidenceRefType.OBSERVATION_DELTA,
                    EvidenceRefType.ASSESSMENT,
                }
                for ref in refs
            )
            if EvidenceRefType.ACTION not in kinds and authoritative_count < 2:
                self._invalid_lesson_evidence()
        elif lesson.lesson_type is ReusableLessonType.PLANNING:
            self._require(
                kinds, {EvidenceRefType.PLAN, EvidenceRefType.PLAN_STEP},
                GroundingRuleCode.REQUIRED_PLANNING_EVIDENCE_MISSING,
            )
            self._require(
                kinds, {EvidenceRefType.PLAN_EVALUATION},
                GroundingRuleCode.REQUIRED_PLANNING_EVIDENCE_MISSING,
            )
        elif lesson.lesson_type is ReusableLessonType.COOPERATION:
            self._require(
                kinds, {EvidenceRefType.PLAYER_CONTRIBUTION},
                GroundingRuleCode.REQUIRED_COOPERATION_EVIDENCE_MISSING,
            )
            self._require(
                kinds, {EvidenceRefType.CONTRIBUTION_EVALUATION},
                GroundingRuleCode.REQUIRED_COOPERATION_EVIDENCE_MISSING,
            )
        elif lesson.lesson_type is ReusableLessonType.MEMORY_HELPFULNESS:
            self._validate_accepted_memory_trace(refs)
            self._require(
                kinds,
                {
                    EvidenceRefType.PLAN_EVALUATION,
                    EvidenceRefType.TOOL_OUTCOME,
                    EvidenceRefType.OBSERVATION_DELTA,
                    EvidenceRefType.ASSESSMENT,
                },
                GroundingRuleCode.REQUIRED_AUTHORITATIVE_EVIDENCE_MISSING,
            )

    @staticmethod
    def _invalid_lesson_evidence() -> None:
        raise ReflectionProposalValidationError(
            "lesson evidence roles do not form an allowed deterministic derivation",
            GroundingRuleCode.LESSON_EVIDENCE_CONTRACT_INVALID,
        )

    @staticmethod
    def _validate_lesson_scope(
        lesson: ReusableLessonProposal, refs: tuple[EvidenceRef, ...]
    ) -> None:
        allowed_scope_types = {
            ReusableLessonType.OUTCOME: {
                ApplicabilityScopeType.SAME_CASE_STAGE,
                ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
                ApplicabilityScopeType.SIMILAR_PUBLIC_SYMPTOM_PATTERN,
            },
            ReusableLessonType.PLANNING: {
                ApplicabilityScopeType.SAME_CASE_STAGE,
                ApplicabilityScopeType.SIMILAR_GOAL_TYPE,
            },
            ReusableLessonType.COOPERATION: {
                ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR,
            },
            ReusableLessonType.MEMORY_HELPFULNESS: {
                ApplicabilityScopeType.SIMILAR_GOAL_TYPE,
                ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
            },
        }[lesson.lesson_type]
        scope = lesson.applicability_scope
        if scope.scope_type not in allowed_scope_types:
            ReflectionProposalValidator._invalid_lesson_scope()
        # No structured public case-stage anchor exists in the current bundle.
        if scope.scope_type is ApplicabilityScopeType.SAME_CASE_STAGE:
            ReflectionProposalValidator._invalid_lesson_scope()
        if scope.public_case_stage is not None:
            ReflectionProposalValidator._invalid_lesson_scope()
        anchor_type = {
            ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN: EvidenceRefType.TOOL_OUTCOME,
            ApplicabilityScopeType.SIMILAR_PUBLIC_SYMPTOM_PATTERN: EvidenceRefType.OBSERVATION_DELTA,
            ApplicabilityScopeType.SIMILAR_GOAL_TYPE: EvidenceRefType.GOAL,
            ApplicabilityScopeType.SIMILAR_PLAYER_BEHAVIOR: EvidenceRefType.CONTRIBUTION_EVALUATION,
        }[scope.scope_type]
        allowed_tags = {ref.ref_id for ref in refs if ref.ref_type is anchor_type}
        proposed_tags = set(scope.public_pattern_tags)
        if not proposed_tags or not proposed_tags.issubset(allowed_tags):
            ReflectionProposalValidator._invalid_lesson_scope()

    @staticmethod
    def _invalid_lesson_scope() -> None:
        raise ReflectionProposalValidationError(
            "lesson applicability scope is not backed by public structured anchors",
            GroundingRuleCode.LESSON_SCOPE_INVALID,
        )

    @staticmethod
    def _grounding_refs_for_finding(
        kind: ReflectionFindingType, refs: tuple[EvidenceRef, ...]
    ) -> tuple[EvidenceRef, ...]:
        allowed = {
            ReflectionFindingType.SUCCESSFUL_STRATEGY: {
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
            ReflectionFindingType.FAILED_STRATEGY: {
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
            ReflectionFindingType.MISSED_OR_DELAYED_EVIDENCE: {
                EvidenceRefType.PLAN_EVALUATION,
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
            ReflectionFindingType.UNNECESSARY_ACTION: {
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
            ReflectionFindingType.COOPERATION_OBSERVATION: {
                EvidenceRefType.CONTRIBUTION_EVALUATION,
            },
            ReflectionFindingType.MEMORY_HELPFULNESS: {
                EvidenceRefType.MEMORY_USAGE_TRACE,
            },
        }[kind]
        return tuple(ref for ref in refs if ref.ref_type in allowed)

    @staticmethod
    def _grounding_refs_for_lesson(
        kind: ReusableLessonType, refs: tuple[EvidenceRef, ...]
    ) -> tuple[EvidenceRef, ...]:
        allowed = {
            ReusableLessonType.OUTCOME: {
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
            ReusableLessonType.PLANNING: {
                EvidenceRefType.PLAN_EVALUATION,
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
            ReusableLessonType.COOPERATION: {
                EvidenceRefType.CONTRIBUTION_EVALUATION,
            },
            ReusableLessonType.MEMORY_HELPFULNESS: {
                EvidenceRefType.MEMORY_USAGE_TRACE,
                EvidenceRefType.TOOL_OUTCOME,
                EvidenceRefType.OBSERVATION_DELTA,
                EvidenceRefType.ASSESSMENT,
            },
        }[kind]
        return tuple(ref for ref in refs if ref.ref_type in allowed)

    @staticmethod
    def _require(
        actual: set[EvidenceRefType],
        allowed: set[EvidenceRefType],
        grounding_rule_code: GroundingRuleCode,
    ) -> None:
        if not actual.intersection(allowed):
            raise ReflectionProposalValidationError(
                "finding or lesson lacks required evidence type",
                grounding_rule_code,
            )

    @staticmethod
    def _validate_accepted_memory_trace(refs: tuple[EvidenceRef, ...]) -> None:
        traces = [ref for ref in refs if ref.ref_type is EvidenceRefType.MEMORY_USAGE_TRACE]
        if not traces:
            raise ReflectionProposalValidationError(
                "memory helpfulness requires memory usage trace",
                GroundingRuleCode.MEMORY_USAGE_TRACE_MISSING,
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
                "selected-but-unused memory cannot be declared helpful",
                GroundingRuleCode.MEMORY_USAGE_NOT_ELIGIBLE,
            )

    @staticmethod
    def _validate_grounding(claim: str, refs: tuple[EvidenceRef, ...]) -> None:
        normalized_claim = ReflectionProposalValidator._normalize(claim)
        summaries = [ReflectionProposalValidator._normalize(ref.public_summary) for ref in refs]
        if not normalized_claim or not any(normalized_claim in summary for summary in summaries):
            raise ReflectionProposalValidationError(
                "specific claim is not supported by cited public evidence",
                GroundingRuleCode.CLAIM_NOT_GROUNDED,
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
        attempt_telemetry = tuple(
            ReflectionGenerationAttemptTelemetry(
                attempt_index=item.attempt_index,
                attempt_kind=item.attempt_kind,
                provider_request_id=item.provider_request_id,
                configured_max_output_tokens=item.configured_max_output_tokens,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                finish_reason=item.finish_reason,
                response_returned=item.response_returned,
                failure_stage=item.failure_stage,
                failure_code=item.failure_code,
                exception_class=item.exception_class,
                field_path=item.field_path,
                error_count=item.error_count,
            )
            for item in result.attempt_telemetry
        )
        return ReflectionGenerationResult(
            proposal=proposal,
            attempts=result.attempts,
            used_fallback=result.output is None,
            repair_kind=result.repair_kind,
            usages=result.usages,
            failure_stage=result.failure_stage,
            failure_code=result.failure_code,
            exception_class=result.exception_class,
            finish_reason=result.finish_reason,
            configured_max_output_tokens=result.configured_max_output_tokens,
            attempt_telemetry=attempt_telemetry,
            repair_attempted=result.repair_attempted,
            repair_succeeded=result.repair_succeeded,
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
        try:
            proposal = ReflectionProposal.model_validate_json(response.content)
        except ValidationError as error:
            raise self._classify_schema_failure(error) from None
        try:
            return self.validator.validate(proposal, bundle)
        except ReflectionProposalValidationError as error:
            raise self._classify_grounding_failure(error) from None

    @staticmethod
    def _classify_schema_failure(
        error: ValidationError,
    ) -> ReflectionGenerationValidationFailure:
        errors = error.errors(include_url=False, include_context=False, include_input=False)
        first = errors[0] if errors else {}
        error_type = str(first.get("type", ""))
        location = first.get("loc", ())
        field_path = ".".join(str(item) for item in location)[:300] or None
        if error_type == "json_invalid":
            stage, code = "reflection_json_parse", "invalid_json"
        elif error_type == "missing":
            stage, code = "reflection_schema_validation", "required_field_missing"
        elif error_type == "extra_forbidden":
            stage, code = "reflection_schema_validation", "extra_field_forbidden"
        elif error_type in {"enum", "literal_error"}:
            stage, code = "reflection_schema_validation", "enum_mismatch"
        else:
            summary = " ".join(str(item.get("msg", "")) for item in error.errors()).lower()
            if "proposed memory type" in summary:
                stage, code = "reflection_schema_validation", "memory_type_not_allowed"
            elif "applicability scope" in summary:
                stage, code = "reflection_schema_validation", "applicability_scope_invalid"
            else:
                stage, code = "reflection_schema_validation", "other_schema_validation"
        return ReflectionGenerationValidationFailure(
            stage=stage,
            code=code,
            source_exception_class=type(error).__name__,
            field_path=field_path,
            error_count=max(1, error.error_count()),
        )

    @staticmethod
    def _classify_grounding_failure(
        error: ReflectionProposalValidationError,
    ) -> ReflectionGenerationValidationFailure:
        return ReflectionGenerationValidationFailure(
            stage="reflection_grounding_validation",
            code=error.grounding_rule_code.value,
            source_exception_class=type(error).__name__,
            error_count=1,
        )

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
