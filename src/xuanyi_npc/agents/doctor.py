"""Safe Prompt-Only V0 DoctorAgent with bounded repair and fallback."""

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import ConfigDict, Field, StrictBool, StrictInt, ValidationError

from xuanyi_npc.application.views import CaseObservation, PlayerView
from xuanyi_npc.domain import AgentAction, AgentActionType
from xuanyi_npc.domain.base import DomainModel, NonEmptyText
from xuanyi_npc.evaluation import ModelUsage

from .llm import (
    ChatMessage,
    ChatRole,
    LLMAdapter,
    LLMAdapterError,
    LLMRequest,
    LLMResponse,
)


V0_SYSTEM_PROMPT = """你是架空道家志怪世界中的道医师父。你只依据提供的可见信息行动。
病例真相、未发现线索、隐藏门槛和合法答案不会提供给你；不得猜测或声称已经读取它们。
你只能输出一个符合 JSON Schema 的 AgentAction。你可以说话，或请求一个工具；不能直接修改病例、能力、关系、权限、技能或永久记忆。
工具参数约定：调查类工具只提交 investigation_id；submit_diagnosis 只能提交 diagnosis_candidates 中列出的 diagnosis_id，并只引用已发现的 evidence_clue_ids；execute_treatment 只提交当前可见的 treatment_id；两个 get_* 工具不带参数。
只使用当前观察中列出的公开候选、调查、处置与已发现证据。候选词表不表示正确答案，所有请求仍会由确定性规则层复核。所有医术与处置均为架空内容。"""


FIXED_V0_LESSONS = (
    "第一课：先察公开症状，只从当前可见调查中选择行动。",
    "第二课：再问经历，区分当事人陈述与已经验证的线索。",
    "第三课：检查相关物件，不把相邻现象直接当作根因。",
    "第四课：复核线索之间的联系，证据不足时继续调查。",
    "第五课：只引用已经发现的证据提出诊断，再选择当前可见处置。",
)


class DoctorAgentConfig(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recent_message_limit: Annotated[StrictInt, Field(ge=1, le=20)] = 6
    format_repair_attempts: Literal[1] = 1
    prompt_version: Literal["v0.2.0"] = "v0.2.0"


class DoctorAgentInput(DomainModel):
    """The complete read-only input visible to V0 for one decision."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    step_index: Annotated[StrictInt, Field(ge=1, le=100)]
    player_view: PlayerView
    case_observation: CaseObservation
    recent_messages: tuple[ChatMessage, ...] = Field(default_factory=tuple)
    fixed_lesson: NonEmptyText


class AgentDecision(DomainModel):
    """Validated Agent proposal plus reliability metadata for Episode recording."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: AgentAction
    llm_attempts: Annotated[StrictInt, Field(ge=1, le=2)]
    used_fallback: StrictBool
    usages: tuple[ModelUsage, ...] = Field(default_factory=tuple)


@runtime_checkable
class DoctorAgentInterface(Protocol):
    """Application-facing port implemented by DoctorAgent."""

    config: DoctorAgentConfig

    def decide(self, agent_input: DoctorAgentInput) -> AgentDecision:
        """Propose one validated action from read-only input."""


class FixedV0Curriculum:
    """Select lessons by step number only; no player-performance adaptation."""

    def lesson_for_step(self, step_index: int) -> str:
        if step_index < 1:
            raise ValueError("step_index must be at least 1")
        position = min(step_index - 1, len(FIXED_V0_LESSONS) - 1)
        return FIXED_V0_LESSONS[position]


class DoctorAgent:
    """Call an injected LLM, validate AgentAction, retry once, then degrade safely."""

    def __init__(
        self,
        adapter: LLMAdapter,
        config: DoctorAgentConfig | None = None,
    ) -> None:
        self.adapter = adapter
        self.config = config or DoctorAgentConfig()

    def decide(self, agent_input: DoctorAgentInput) -> AgentDecision:
        request = self._build_request(agent_input)
        responses: list[LLMResponse] = []

        try:
            first_response = self.adapter.complete(request)
        except Exception as exc:
            return self._fallback(
                agent_input.step_index,
                1,
                responses,
                self._usage_from_error(exc),
            )
        responses.append(first_response)

        try:
            action = self._parse_action(first_response, agent_input.step_index)
        except (ValidationError, ValueError) as exc:
            repair_request = self._build_repair_request(
                request,
                first_response,
                exc,
                agent_input.step_index,
            )
            try:
                repaired_response = self.adapter.complete(repair_request)
            except Exception as exc:
                return self._fallback(
                    agent_input.step_index,
                    2,
                    responses,
                    self._usage_from_error(exc),
                )
            responses.append(repaired_response)
            try:
                action = self._parse_action(repaired_response, agent_input.step_index)
            except (ValidationError, ValueError):
                return self._fallback(agent_input.step_index, 2, responses)
            return AgentDecision(
                action=action,
                llm_attempts=2,
                used_fallback=False,
                usages=self._usages(responses),
            )

        return AgentDecision(
            action=action,
            llm_attempts=1,
            used_fallback=False,
            usages=self._usages(responses),
        )

    def _build_request(self, agent_input: DoctorAgentInput) -> LLMRequest:
        expected_action_id = self._expected_action_id(agent_input.step_index)
        current_context = (
            f"固定课程（不得自适应改序）：{agent_input.fixed_lesson}\n"
            f"本步 action_id 必须为：{expected_action_id}\n"
            "玩家只读视图：\n"
            f"{agent_input.player_view.model_dump_json(indent=2)}\n"
            "病例只读观察：\n"
            f"{agent_input.case_observation.model_dump_json(indent=2)}\n"
            "请提出下一步结构化行动。"
        )
        recent = agent_input.recent_messages[-self.config.recent_message_limit :]
        return LLMRequest(
            messages=(
                ChatMessage(role=ChatRole.SYSTEM, content=V0_SYSTEM_PROMPT),
                *recent,
                ChatMessage(role=ChatRole.USER, content=current_context),
            ),
            response_schema=AgentAction.model_json_schema(),
        )

    @staticmethod
    def _build_repair_request(
        original: LLMRequest,
        invalid_response: LLMResponse,
        error: Exception,
        step_index: int,
    ) -> LLMRequest:
        repair_message = (
            "上一个输出未通过 AgentAction 校验。只修复 JSON 格式和字段，不增加任何"
            "不可见事实，也不要解释。"
            f"本步 action_id 必须为 {DoctorAgent._expected_action_id(step_index)}。"
            f"校验信息：{str(error)[:2000]}"
        )
        return LLMRequest(
            messages=(
                *original.messages,
                ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=invalid_response.content,
                ),
                ChatMessage(role=ChatRole.USER, content=repair_message),
            ),
            response_schema=original.response_schema,
        )

    @staticmethod
    def _parse_action(response: LLMResponse, step_index: int) -> AgentAction:
        action = AgentAction.model_validate_json(response.content)
        expected_action_id = DoctorAgent._expected_action_id(step_index)
        if action.action_id != expected_action_id:
            raise ValueError(f"action_id must be {expected_action_id}")
        return action

    @staticmethod
    def _expected_action_id(step_index: int) -> str:
        return f"agent_step_{step_index:03d}"

    @staticmethod
    def _fallback(
        step_index: int,
        llm_attempts: int,
        responses: list[LLMResponse],
        error_usages: tuple[ModelUsage, ...] = (),
    ) -> AgentDecision:
        return AgentDecision(
            action=AgentAction(
                action_id=DoctorAgent._expected_action_id(step_index),
                action_type=AgentActionType.RESPOND,
                dialogue="此刻先停一步，只据已知线索再作判断。",
                confidence=0.0,
            ),
            llm_attempts=llm_attempts,
            used_fallback=True,
            usages=(*DoctorAgent._usages(responses), *error_usages),
        )

    @staticmethod
    def _usages(responses: list[LLMResponse]) -> tuple[ModelUsage, ...]:
        return tuple(
            response.usage for response in responses if response.usage is not None
        )

    @staticmethod
    def _usage_from_error(error: Exception) -> tuple[ModelUsage, ...]:
        if isinstance(error, LLMAdapterError) and error.usage is not None:
            return (error.usage,)
        return ()
