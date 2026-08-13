"""Deterministic public communication plans for versioned mentor expression."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.mentor import MentorActionType
from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMRequest
from xuanyi_npc.agents.mentor import MENTOR_SYSTEM_PROMPT


class MentorCommunicationPlan(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: Identifier
    interaction_type: Identifier
    required_public_point_ids: tuple[Identifier, ...] = Field(min_length=1)
    required_public_facts: dict[Identifier, NonEmptyText]
    point_validation_terms: dict[Identifier, tuple[NonEmptyText, ...]]
    point_contradiction_terms: dict[Identifier, tuple[NonEmptyText, ...]] = {}
    forbidden_topics: tuple[NonEmptyText, ...]
    allowed_reason_codes: tuple[Identifier, ...]
    allowed_reference_ids: tuple[Identifier, ...]
    tone_profile: Identifier
    allowed_action_types: tuple[MentorActionType, ...]
    allowed_hint_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_points(self) -> "MentorCommunicationPlan":
        required = set(self.required_public_point_ids)
        if set(self.required_public_facts) != required or set(self.point_validation_terms) != required:
            raise ValueError("every required point must have one public fact and validation terms")
        if not set(self.point_contradiction_terms).issubset(required):
            raise ValueError("contradictions may reference only required points")
        return self


class MentorActionV2(DomainModel):
    """Pilot-only expression contract; historical MentorAction remains unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action_type: MentorActionType
    message: NonEmptyText
    covered_point_ids: tuple[Identifier, ...] = Field(min_length=1)
    hint_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_hint(self) -> "MentorActionV2":
        if (self.action_type is MentorActionType.GIVE_HINT) != (self.hint_id is not None):
            raise ValueError("hint_id is required only for give_hint")
        return self


class CommunicationEvaluation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    structured_coverage_valid: bool
    text_consistent: bool
    safe: bool
    missing_point_ids: tuple[Identifier, ...]
    unknown_point_ids: tuple[Identifier, ...]
    contradicted_point_ids: tuple[Identifier, ...]
    unsupported_claimed_point_ids: tuple[Identifier, ...]
    forbidden_topic_hits: tuple[NonEmptyText, ...]
    player_action_replacement: bool
    complete: bool


class PilotStopCategory(str, Enum):
    PROTOCOL = "protocol_stop"
    CONTRACT = "contract_stop"
    SAFETY = "safety_stop"
    TEACHING_QUALITY = "teaching_quality_stop"
    BUDGET = "budget_stop"
    TIMEOUT = "timeout_stop"
    PROVIDER_IDENTITY = "provider_identity_stop"


class MentorCommunicationPlanner:
    """Project existing public authority into stable, complete expression plans."""

    def build(self, request_id: str, public_context: dict[str, Any]) -> MentorCommunicationPlan:
        builders = {
            "initial_lesson_hint_1": self._initial,
            "wrong_diagnosis_remediation_1": self._remediation,
            "exam_failure_explanation_1": self._exam,
            "inheritance_refusal_1": self._refusal,
            "inheritance_grant_1": self._grant,
        }
        try:
            return builders[request_id](public_context)
        except KeyError as exc:
            raise ValueError("unsupported communication interaction") from exc

    @staticmethod
    def _initial(ctx: dict[str, Any]) -> MentorCommunicationPlan:
        role = ctx["mentor_role"]
        lesson = ctx["lesson"]
        hint = ctx["allowed_hint_cards"][0]
        return _plan("initial_lesson_hint_1", "initial_lesson_hint", {
            "player_is_apprentice": role,
            "player_acts_personally": "弟子亲自调查、诊断和处置。",
            "mentor_teaches_without_taking_over": "导师只教学并提供有限提示，不替弟子行动。",
            "lesson_goal": lesson["goal"],
            "bounded_hint_available": "当前只提供一次已授权公开提示。",
        }, {
            "player_is_apprentice": ("弟子",), "player_acts_personally": ("亲自",),
            "mentor_teaches_without_taking_over": ("不替", "只负责教学"), "lesson_goal": ("事实", "证据"),
            "bounded_hint_available": ("提示",),
        }, ("正确诊断", "正确处置", "隐藏线索"), ("lesson_start",), (hint["hint_id"],), (MentorActionType.GIVE_HINT,), (hint["hint_id"],))

    @staticmethod
    def _remediation(ctx: dict[str, Any]) -> MentorCommunicationPlan:
        decision = ctx["deterministic_curriculum_decision"]
        return _plan("wrong_diagnosis_remediation_1", "wrong_diagnosis_remediation", {
            "diagnosis_needs_improvement": ctx["submitted_result"],
            "assigned_remediation": f"已确定安排{decision['title']}（{decision['remediation_id']}）。",
            "remediation_reason": "安排原因是公开改进项 reason_diagnosis，需要改进辨证推理。",
            "remediation_has_no_direct_skill_gain": decision["effect"],
            "future_case_performance_proves_improvement": "完成补课后仍需以后续病例中的正确表现证明改善。",
        }, {
            "diagnosis_needs_improvement": ("辨证", "诊断"), "assigned_remediation": ("补课",),
            "remediation_reason": ("原因", "因为"), "remediation_has_no_direct_skill_gain": ("不直接增加", "不会直接增加"),
            "future_case_performance_proves_improvement": ("后续", "以后"),
        }, ("诊断正确", "已经掌握", "能力已增加"), ("reason_diagnosis", "remediate_diagnostic_reasoning_v1"), (), (MentorActionType.RECOMMEND_FIXED_NEXT_STEP,))

    @staticmethod
    def _exam(ctx: dict[str, Any]) -> MentorCommunicationPlan:
        result = ctx["exam_result"]
        return _plan("exam_failure_explanation_1", "exam_failure_explanation", {
            "exam_not_passed": f"本次考试未通过，总分{result['total_score']}。",
            "public_failure_categories": "公开改进类别为诊断推理（reason_diagnosis）。",
            "assigned_remediation": f"已安排{result['required_remediation_ids'][0]}。",
            "retake_requires_remediation": "完成指定补课前不能重考。",
            "score_and_permission_unchanged": "导师不能修改分数、通过状态或权限。",
        }, {
            "exam_not_passed": ("未通过", "失败"), "public_failure_categories": ("诊断", "辨证"),
            "assigned_remediation": ("补课",), "retake_requires_remediation": ("重考",),
            "score_and_permission_unchanged": ("不能修改", "不会修改"),
        }, ("正确答案", "标准答案", "改为通过"), ("exam_failed", "reason_diagnosis"), (), (MentorActionType.REVIEW_EXAM,))

    @staticmethod
    def _refusal(ctx: dict[str, Any]) -> MentorCommunicationPlan:
        reasons = "、".join(ctx["public_reason_categories"])
        return _plan("inheritance_refusal_1", "inheritance_refusal", {
            "inheritance_not_granted": "当前暂不授予传承。",
            "public_missing_categories": f"公开原因类别为：{reasons}。",
            "decision_owned_by_rules": "拒绝决定来自确定性规则。",
            "mentor_cannot_override": "导师不能绕过规则或自行写入权限。",
            "requirements_may_be_completed_later": "弟子以后补足公开条件后可以再次申请。",
        }, {
            "inheritance_not_granted": ("暂不授予", "拒绝"), "public_missing_categories": ("考试", "能力", "认可"),
            "decision_owned_by_rules": ("规则",), "mentor_cannot_override": ("不能绕过", "不能自行"),
            "requirements_may_be_completed_later": ("以后", "之后", "再次申请"),
        }, ("精确门槛", "MENTOR_SECRET", "已经授予"), ("exam_not_passed", "ability_evidence_insufficient", "mentor_recognition_insufficient"), (), (MentorActionType.REFUSE_INHERITANCE,))

    @staticmethod
    def _grant(ctx: dict[str, Any]) -> MentorCommunicationPlan:
        grant = ctx["public_grant"]
        return _plan("inheritance_grant_1", "inheritance_grant", {
            "inheritance_granted": "确定性规则已经授予传承。",
            "granted_inheritance_name": f"授予的传承是{grant['inheritance_title']}。",
            "decision_owned_by_rules": "授予决定来自确定性规则，不由导师语言创建。",
            "granted_permission": f"已授予公开权限级别{grant['permission_level']}，且不重复写入。",
            "inheritance_does_not_replace_player_judgment": "传承只增加合法公开路线，不替弟子诊断或处置。",
        }, {
            "inheritance_granted": ("授予",), "granted_inheritance_name": (grant["inheritance_title"],),
            "decision_owned_by_rules": ("规则",), "granted_permission": ("权限",),
            "inheritance_does_not_replace_player_judgment": ("不替", "亲自"),
        }, ("MENTOR_SECRET", "隐藏门槛", "由我修改权限"), ("inheritance_granted",), (), (MentorActionType.OFFER_INHERITANCE,))


def _plan(plan_id, interaction, facts, terms, forbidden, reasons, refs, actions, hints=()):
    return MentorCommunicationPlan(plan_id=plan_id, interaction_type=interaction, required_public_point_ids=tuple(facts), required_public_facts=facts, point_validation_terms=terms, forbidden_topics=forbidden, allowed_reason_codes=reasons, allowed_reference_ids=refs, tone_profile="calm_explicit_mentor_v1", allowed_action_types=actions, allowed_hint_ids=hints)


def evaluate_mentor_action_v2(plan: MentorCommunicationPlan, action: MentorActionV2) -> CommunicationEvaluation:
    required=set(plan.required_public_point_ids); covered=set(action.covered_point_ids)
    unknown=tuple(sorted(covered-required)); missing=tuple(item for item in plan.required_public_point_ids if item not in covered)
    text=action.message.lower(); contradicted=[]; unsupported=[]
    for point in action.covered_point_ids:
        if point in required and not any(term.lower() in text for term in plan.point_validation_terms[point]): unsupported.append(point)
        if point in plan.point_contradiction_terms and any(term.lower() in text for term in plan.point_contradiction_terms[point]): contradicted.append(point)
    hits=tuple(term for term in plan.forbidden_topics if term.lower() in text)
    replacement=any(term in text for term in ("我已替你调查","我替你诊断","我替你处置","我已改分","我自行授予"))
    structured=not missing and not unknown
    consistent=not contradicted and not unsupported
    safe=not hits and not replacement
    return CommunicationEvaluation(structured_coverage_valid=structured,text_consistent=consistent,safe=safe,missing_point_ids=missing,unknown_point_ids=unknown,contradicted_point_ids=tuple(contradicted),unsupported_claimed_point_ids=tuple(unsupported),forbidden_topic_hits=hits,player_action_replacement=replacement,complete=structured and consistent and safe and action.action_type in plan.allowed_action_types)


def deterministic_fallback(plan: MentorCommunicationPlan) -> MentorActionV2:
    message="【确定性降级说明】"+" ".join(plan.required_public_facts[item] for item in plan.required_public_point_ids)
    return MentorActionV2(action_type=plan.allowed_action_types[0],message=message,covered_point_ids=plan.required_public_point_ids,hint_id=(plan.allowed_hint_ids[0] if plan.allowed_hint_ids else None))


def build_communication_request(plan: MentorCommunicationPlan, *, repair_missing: tuple[str, ...] = ()) -> LLMRequest:
    public={
        "communication_plan": plan.model_dump(mode="json"),
        "instruction": "逐项表达全部required_public_point_ids；只依据required_public_facts；covered_point_ids必须与正文实际覆盖一致。",
    }
    messages=[ChatMessage(role=ChatRole.SYSTEM,content=MENTOR_SYSTEM_PROMPT),ChatMessage(role=ChatRole.USER,content=__import__("json").dumps(public,ensure_ascii=False,sort_keys=True))]
    if repair_missing:
        messages.append(ChatMessage(role=ChatRole.USER,content="唯一一次公开契约修复：缺少point IDs="+",".join(repair_missing)+"。不得增加计划外事实，只输出MentorActionV2 JSON。"))
    schema={"title":"MentorActionV2","type":"object","additionalProperties":False,"required":["action_type","message","covered_point_ids"],"properties":{"action_type":{"type":"string","enum":[x.value for x in plan.allowed_action_types]},"message":{"type":"string","minLength":1},"covered_point_ids":{"type":"array","uniqueItems":True,"items":{"type":"string","enum":list(plan.required_public_point_ids)}},"hint_id":{"type":["string","null"],"enum":[*plan.allowed_hint_ids,None]}}}
    return LLMRequest(messages=tuple(messages),response_schema=schema)


class OfflineCommunicationOutcome(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_passed: bool
    attempts: int
    evaluation: CommunicationEvaluation
    delivered_action: MentorActionV2
    fallback_used: bool
    stop_category: PilotStopCategory | None = None


def run_offline_communication(plan: MentorCommunicationPlan, outputs: tuple[str, ...]) -> OfflineCommunicationOutcome:
    """Exercise parsing, one public repair, evaluation and fallback without I/O."""
    last_eval=None
    for attempt,content in enumerate(outputs[:2],start=1):
        try:
            action=MentorActionV2.model_validate_json(content)
        except Exception:
            continue
        if action.action_type not in plan.allowed_action_types or (action.hint_id is not None and action.hint_id not in plan.allowed_hint_ids):
            continue
        evaluation=evaluate_mentor_action_v2(plan,action); last_eval=evaluation
        if not evaluation.safe:
            return OfflineCommunicationOutcome(model_passed=False,attempts=attempt,evaluation=evaluation,delivered_action=deterministic_fallback(plan),fallback_used=True,stop_category=PilotStopCategory.SAFETY)
        if evaluation.complete:
            return OfflineCommunicationOutcome(model_passed=True,attempts=attempt,evaluation=evaluation,delivered_action=action,fallback_used=False)
    fallback=deterministic_fallback(plan)
    fallback_eval=evaluate_mentor_action_v2(plan,fallback)
    return OfflineCommunicationOutcome(model_passed=False,attempts=min(2,len(outputs)),evaluation=last_eval or fallback_eval,delivered_action=fallback,fallback_used=True,stop_category=PilotStopCategory.TEACHING_QUALITY)


def classify_transport_failure(code: str) -> PilotStopCategory:
    if code in {"timeout"}: return PilotStopCategory.TIMEOUT
    if code in {"budget_exceeded","budget_halted","usage_exceeds_reservation"}: return PilotStopCategory.BUDGET
    if code in {"configured_model_unavailable","response_model_mismatch","models_call_limit"}: return PilotStopCategory.PROVIDER_IDENTITY
    return PilotStopCategory.PROTOCOL


def should_stop(category: PilotStopCategory, *, continue_on_teaching_quality: bool) -> bool:
    return category is not PilotStopCategory.TEACHING_QUALITY or not continue_on_teaching_quality
