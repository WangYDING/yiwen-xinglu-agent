"""Deterministic model-context assembly and non-model-visible build records."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal

from xuanyi_npc.application.action_contract import (
    SafeActionRecoveryFeedback,
    project_public_diagnosis_actions,
    project_public_investigation_actions,
    project_public_treatment_actions,
)
from xuanyi_npc.domain.cooperation import GameNPCDecisionProposal
from xuanyi_npc.domain.planning_contract import GameNPCTurnProposal

from .llm import ChatMessage, ChatRole, LLMRequest, LLMResponse


GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS = 2048
A0_CONTEXT_STRATEGY_VERSION = "game_npc_a0_context_v1"
A1_CONTEXT_STRATEGY_VERSION = "game_npc_a1_context_v1"
FORMAT_REPAIR_STRATEGY_VERSION = "game_npc_format_repair_v1"
ACTION_CONTRACT_REPAIR_STRATEGY_VERSION = "game_npc_action_contract_repair_v1"


class GameNPCPlanningRequest(LLMRequest):
    """Preserve the existing A1-only output reservation on initial requests."""

    max_output_tokens: Literal[GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS] = (
        GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS
    )


@dataclass(frozen=True)
class ContextBlockRecord:
    """Exact character/byte lengths for one selected context block.

    These are exact string measurements.  They are deliberately not described
    as provider token counts.
    """

    name: str
    source: str
    source_version: str
    exact_character_count: int
    exact_utf8_byte_count: int
    selection: str = "included_unchanged"


@dataclass(frozen=True)
class ContextBuildTrace:
    """Audit record for a request build; never serialized into model context."""

    request_kind: str
    build_strategy_version: str
    prompt_version: str
    blocks: tuple[ContextBlockRecord, ...]
    message_count: int
    exact_message_character_count: int
    exact_message_utf8_byte_count: int
    exact_schema_character_count: int
    exact_schema_utf8_byte_count: int
    response_schema_sha256: str
    requested_max_output_tokens: int | None
    token_count_method: Literal["not_measured"] = "not_measured"


@dataclass(frozen=True)
class BuiltContext:
    request: LLMRequest
    trace: ContextBuildTrace


class ContextAssembler:
    """Build the current A0/A1 request shapes without policy or model calls."""

    @staticmethod
    def _record(name: str, source: str, version: str, content: str) -> ContextBlockRecord:
        return ContextBlockRecord(
            name=name,
            source=source,
            source_version=version,
            exact_character_count=len(content),
            exact_utf8_byte_count=len(content.encode("utf-8")),
        )

    @staticmethod
    def _trace(
        request: LLMRequest,
        *,
        request_kind: str,
        strategy: str,
        prompt_version: str,
        blocks: tuple[ContextBlockRecord, ...],
    ) -> ContextBuildTrace:
        message_text = "".join(message.content for message in request.messages)
        schema_text = json.dumps(
            request.response_schema,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return ContextBuildTrace(
            request_kind=request_kind,
            build_strategy_version=strategy,
            prompt_version=prompt_version,
            blocks=blocks,
            message_count=len(request.messages),
            exact_message_character_count=len(message_text),
            exact_message_utf8_byte_count=len(message_text.encode("utf-8")),
            exact_schema_character_count=len(schema_text),
            exact_schema_utf8_byte_count=len(schema_text.encode("utf-8")),
            response_schema_sha256=hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
            requested_max_output_tokens=getattr(request, "max_output_tokens", None),
        )

    @staticmethod
    def _recent_messages(value: Any, recent_message_limit: int) -> tuple[ChatMessage, ...]:
        return (
            value.recent_messages[-recent_message_limit:]
            if recent_message_limit
            else ()
        )

    def _action_parts(
        self,
        value: Any,
        *,
        system_prompt: str,
        prompt_version: str,
        recent_message_limit: int,
    ) -> tuple[tuple[ChatMessage, ...], tuple[ContextBlockRecord, ...]]:
        contribution = (
            value.player_contribution.model_dump_json(indent=2)
            if value.player_contribution
            else "null"
        )
        player_view = value.player_view.model_dump_json(indent=2)
        observation = value.case_observation.model_dump_json(indent=2)
        authority = value.authority_view.model_dump_json(indent=2)
        turn_header = (
            f"turn_id={value.turn_id}\n"
            f"本轮 action_id 必须为 npc_{value.turn_id}\n"
        )
        context = (
            turn_header
            + "authoritative_player_view:\n" + player_view + "\n"
            + "authoritative_observation:\n" + observation + "\n"
            + "player_contribution_untrusted:\n" + contribution + "\n"
            + "authority_view:\n" + authority
        )
        recent = self._recent_messages(value, recent_message_limit)
        recent_text = "".join(message.content for message in recent)
        messages = (
            ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
            *recent,
            ChatMessage(role=ChatRole.USER, content=context),
        )
        blocks = (
            self._record("stable_system_prompt", "GAME_NPC_M1_SYSTEM_PROMPT", prompt_version, system_prompt),
            self._record("recent_messages", "GameNPCAgentInput.recent_messages", "input", recent_text),
            self._record("turn_contract", "GameNPCAgentInput.turn_id", "input", turn_header),
            self._record("player_view", "GameNPCAgentInput.player_view", "input", player_view),
            self._record("case_observation", "GameNPCAgentInput.case_observation", "input", observation),
            self._record("player_contribution", "GameNPCAgentInput.player_contribution", "input", contribution),
            self._record("authority_view", "GameNPCAgentInput.authority_view", "input", authority),
        )
        return messages, blocks

    def build_action_request(
        self,
        value: Any,
        *,
        system_prompt: str,
        prompt_version: str,
        recent_message_limit: int,
    ) -> BuiltContext:
        messages, blocks = self._action_parts(
            value,
            system_prompt=system_prompt,
            prompt_version=prompt_version,
            recent_message_limit=recent_message_limit,
        )
        request = LLMRequest(
            messages=messages,
            response_schema=GameNPCDecisionProposal.model_json_schema(),
        )
        return BuiltContext(
            request=request,
            trace=self._trace(
                request,
                request_kind="a0_initial",
                strategy=A0_CONTEXT_STRATEGY_VERSION,
                prompt_version=prompt_version,
                blocks=blocks,
            ),
        )

    def build_planning_request(
        self,
        value: Any,
        *,
        system_prompt: str,
        prompt_version: str,
        recent_message_limit: int,
    ) -> BuiltContext:
        contribution = value.player_contribution.model_dump_json(indent=2) if value.player_contribution else "null"
        current_goal = value.current_goal.model_dump_json(indent=2) if value.current_goal else "null"
        current_plan = value.current_plan.model_dump_json(indent=2) if value.current_plan else "null"
        evaluation = value.last_plan_evaluation.model_dump_json(indent=2) if value.last_plan_evaluation else "null"
        feedback = value.last_environment_feedback or "null"
        memory_context = value.memory_context.model_dump_json(indent=2) if value.memory_context else "null"
        authority = value.authority_view.model_dump_json(indent=2)
        observation = value.case_observation.model_dump_json(indent=2)
        player_view = value.player_view.model_dump_json(indent=2)
        pending = value.pending_confirmation_id or "null"
        investigation_actions = tuple(
            item.model_dump(mode="json")
            for item in project_public_investigation_actions(value.case_observation)
        )
        diagnosis_actions = tuple(
            item.model_dump(mode="json")
            for item in project_public_diagnosis_actions(value.case_observation)
        )
        treatment_actions = tuple(
            item.model_dump(mode="json")
            for item in project_public_treatment_actions(value.case_observation)
        )
        public_action_space = json.dumps(
            (*investigation_actions, *diagnosis_actions, *treatment_actions),
            ensure_ascii=False,
            indent=2,
        )
        turn_header = f"turn_id={value.turn_id}\n本轮 action_id 必须为 npc_{value.turn_id}\n"
        contracts = (
            "PUBLIC_ACTION_CONTRACT: 若 decision 使用调查 Tool，只能选择 AVAILABLE_PUBLIC_ACTION_SPACE 中存在的 action；"
            "ToolCall arguments 必须逐字复制该 action 的 exact arguments。不得自造 ID、使用自然语言 target、"
            "使用 clue ID 替代 investigation_id、省略 required argument 或添加未声明 argument。\n"
            "PLAN_INVESTIGATION_CONTRACT: 若 PlanDraft step 对应调查 action，suggested_tool 必须复制上述同一个"
            " AVAILABLE_PUBLIC_ACTION_SPACE entry 的 tool_name，public_target_id 必须复制该 entry 的 investigation_id；"
            "不得交叉组合 tool/target，不得自造、使用自然语言、hidden/unavailable、clue 或 patient ID。"
            "非调查型 PlanStep 不得为了填充格式强行绑定 investigation target；PlanStep 仍只是 future intent，"
            "不是 ToolCallRequest。\n"
            "DIAGNOSIS_ACTION_CONTRACT: 当 current_goal 是 form_diagnosis、can_submit_diagnosis=true，"
            "且当前 active PlanStep 要求 submit_diagnosis 时，decision 应从 AVAILABLE_PUBLIC_ACTION_SPACE"
            "选择一个公开 diagnosis call 来推进 Goal；诊断候选与证据取舍仍由你自主判断。"
            "当本轮用 CREATE/REVISE 且 decision 调用 submit_diagnosis 时，draft.steps[0] 就是本轮结果中的"
            " active PlanStep，必须设置 intent=propose_diagnosis、capability=propose_diagnosis、"
            "suggested_tool=submit_diagnosis，且 public_target_id 必须等于同一 Decision 的 diagnosis_id；"
            "不能先放 analyze_evidence/discuss_with_player，再在后续步骤放诊断。"
            "若当前 Plan 不再合适，应合法 REVISE 或 BLOCK，而不是 KEEP 同一诊断步骤后仅 RESPOND。"
            "RESPOND 仍可用于普通交流、解释步骤，或尚不要求执行 diagnosis action 的步骤。\n"
            "TREATMENT_ACTION_CONTRACT: 当 current_goal 是 select_treatment/discuss_risk，"
            "若 PlanStep intent/capability 是 propose_treatment，必须从 AVAILABLE_PUBLIC_ACTION_SPACE"
            "选择 execute_treatment call；PlanStep suggested_tool/target 必须与该 call 的 tool_name/treatment_id一致。"
            "当本轮用 CREATE/REVISE 且 decision 调用 execute_treatment 时，draft.steps[0] 必须是与该"
            " Decision 同 treatment_id 的 propose_treatment 步骤。"
            "同 turn Decision 调用 execute_treatment 时必须使用同一个 treatment_id；处置选择仍由你自主判断。\n"
            "EXECUTABLE_ACTIVE_STEP_CONTRACT: 若 current_plan 的 active PlanStep 已同时绑定 suggested_tool"
            " 与 public_target_id，且 pending_confirmation_id=null，则 KEEP 当前 Goal/Plan 时 Decision 必须执行"
            "匹配的公开 tool call；若不应执行，必须合法 REVISE/ABANDON Plan 或 BLOCK/ABANDON Goal。"
            "普通 RESPOND 不能维持该 executable step。Runtime 不会替你选择或执行 action。\n"
        )
        context = (
            turn_header
            + "AUTHORITATIVE_WORLD_case_observation:\n" + observation + "\n"
            + "AUTHORITATIVE_WORLD_public_environment_feedback:\n" + feedback + "\n"
            + "AUTHORITATIVE_CONSTRAINTS_authority_view:\n" + authority + "\n"
            + "AGENT_INTENT_current_goal:\n" + current_goal + "\n"
            + "AGENT_INTENT_current_plan:\n" + current_plan + "\n"
            + "AGENT_INTENT_last_plan_evaluation:\n" + evaluation + "\n"
            + "AUTHORITATIVE_CONSTRAINTS_pending_confirmation_id:\n" + pending + "\n"
            + "HISTORICAL_NON_AUTHORITATIVE_CONTEXT_memory_context:\n" + memory_context + "\n"
            + "AUTHORITATIVE_PUBLIC_ACTION_SPACE_available_actions:\n" + public_action_space + "\n"
            + contracts
            + "PLAYER_BELIEF_player_contribution:\n" + contribution + "\n"
            + "authoritative_player_view:\n" + player_view
        )
        recent = self._recent_messages(value, recent_message_limit)
        recent_text = "".join(message.content for message in recent)
        request = GameNPCPlanningRequest(
            messages=(
                ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
                *recent,
                ChatMessage(role=ChatRole.USER, content=context),
            ),
            response_schema=GameNPCTurnProposal.model_json_schema(),
            max_output_tokens=GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS,
        )
        blocks = (
            self._record("stable_system_prompt", "GAME_NPC_M2_PLANNING_PROMPT", prompt_version, system_prompt),
            self._record("recent_messages", "GameNPCAgentInput.recent_messages", "input", recent_text),
            self._record("turn_contract", "GameNPCAgentInput.turn_id", "input", turn_header),
            self._record("case_observation", "GameNPCAgentInput.case_observation", "input", observation),
            self._record("environment_feedback", "GameNPCAgentInput.last_environment_feedback", "input", feedback),
            self._record("authority_view", "GameNPCAgentInput.authority_view", "input", authority),
            self._record("current_goal", "GameNPCAgentInput.current_goal", "input", current_goal),
            self._record("current_plan", "GameNPCAgentInput.current_plan", "input", current_plan),
            self._record("last_plan_evaluation", "GameNPCAgentInput.last_plan_evaluation", "input", evaluation),
            self._record("pending_confirmation_reference", "GameNPCAgentInput.pending_confirmation_id", "input", pending),
            self._record("memory_context", "GameNPCAgentInput.memory_context", "input", memory_context),
            self._record("public_action_space", "application.action_contract projections", "current", public_action_space),
            self._record("action_and_plan_contracts", "ContextAssembler.fixed_contracts", A1_CONTEXT_STRATEGY_VERSION, contracts),
            self._record("player_contribution", "GameNPCAgentInput.player_contribution", "input", contribution),
            self._record("player_view", "GameNPCAgentInput.player_view", "input", player_view),
        )
        return BuiltContext(
            request=request,
            trace=self._trace(
                request,
                request_kind="a1_initial",
                strategy=A1_CONTEXT_STRATEGY_VERSION,
                prompt_version=prompt_version,
                blocks=blocks,
            ),
        )

    def build_format_repair_request(
        self,
        original: LLMRequest,
        invalid: LLMResponse,
        error: Exception,
        value: Any,
        *,
        planning: bool,
        prompt_version: str,
    ) -> BuiltContext:
        if planning:
            feedback = (
                "上一 Goal/Plan/Decision proposal 未通过确定性策略。只依据公开上下文修复 JSON，不改变权限；"
                f"action_id 必须为 npc_{value.turn_id}。校验信息：{str(error)[:1000]}"
            )
            request_kind = "a1_format_repair"
        else:
            feedback = (
                "上一输出未通过结构化校验。只修复 JSON；"
                f"action_id 必须为 npc_{value.turn_id}。校验信息：{str(error)[:1000]}"
            )
            request_kind = "a0_format_repair"
        request = LLMRequest(
            messages=(
                *original.messages,
                ChatMessage(role=ChatRole.ASSISTANT, content=invalid.content),
                ChatMessage(role=ChatRole.USER, content=feedback),
            ),
            response_schema=original.response_schema,
        )
        blocks = (
            self._record("original_request_messages", "initial ContextBuild", "same_request", "".join(item.content for item in original.messages)),
            self._record("invalid_model_output", "LLMResponse.content", "attempt_1", invalid.content),
            self._record("validation_feedback", "bounded deterministic validation", "attempt_1", feedback),
        )
        return BuiltContext(
            request=request,
            trace=self._trace(
                request,
                request_kind=request_kind,
                strategy=FORMAT_REPAIR_STRATEGY_VERSION,
                prompt_version=prompt_version,
                blocks=blocks,
            ),
        )

    def build_action_contract_repair_request(
        self,
        value: Any,
        feedback: SafeActionRecoveryFeedback,
        *,
        system_prompt: str,
        prompt_version: str,
        recent_message_limit: int,
    ) -> BuiltContext:
        messages, base_blocks = self._action_parts(
            value,
            system_prompt=system_prompt,
            prompt_version=prompt_version,
            recent_message_limit=recent_message_limit,
        )
        repair_feedback = (
            "上一提案不符合公开行动契约。只依据安全反馈修复，不增加事实：\n"
            + feedback.model_dump_json(indent=2)
        )
        request = LLMRequest(
            messages=(
                *messages,
                ChatMessage(role=ChatRole.USER, content=repair_feedback),
            ),
            response_schema=GameNPCDecisionProposal.model_json_schema(),
        )
        blocks = (
            *base_blocks,
            self._record(
                "safe_action_recovery_feedback",
                "application.action_contract.SafeActionRecoveryFeedback",
                "current",
                repair_feedback,
            ),
        )
        return BuiltContext(
            request=request,
            trace=self._trace(
                request,
                request_kind="a0_action_contract_repair",
                strategy=ACTION_CONTRACT_REPAIR_STRATEGY_VERSION,
                prompt_version=prompt_version,
                blocks=blocks,
            ),
        )
