from datetime import datetime, timezone
from decimal import Decimal

from xuanyi_npc.agents import (
    ChatMessage,
    ChatRole,
    DoctorAgent,
    DoctorAgentConfig,
    DoctorAgentInput,
    DoctorAgentInterface,
    FixedV0Curriculum,
    LLMAdapter,
    LLMAdapterError,
    ScriptedFakeLLM,
)
from xuanyi_npc.application import AgentContextFilter
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    CaseSessionState,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
)
from xuanyi_npc.engine import CaseEngine
from xuanyi_npc.evaluation import ModelUsage


def action_json(step_index: int, dialogue: str = "先察其形。") -> str:
    return AgentAction(
        action_id=f"agent_step_{step_index:03d}",
        action_type=AgentActionType.RESPOND,
        dialogue=dialogue,
        confidence=0.8,
    ).model_dump_json()


def agent_input(
    case: CaseDefinition,
    player: PlayerState,
    *,
    step_index: int = 1,
    recent_messages: tuple[ChatMessage, ...] = (),
) -> DoctorAgentInput:
    context_filter = AgentContextFilter()
    session = CaseSessionState(
        session_id="session_doctor_agent",
        case_id=case.case_id,
        player_id=player.player_id,
    )
    return DoctorAgentInput(
        step_index=step_index,
        player_view=context_filter.player_view(player),
        case_observation=context_filter.case_observation(case, player, session),
        recent_messages=recent_messages,
        fixed_lesson=FixedV0Curriculum().lesson_for_step(step_index),
    )


def test_doctor_agent_uses_only_filtered_read_only_context(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM([action_json(1)])
    doctor = DoctorAgent(fake)

    assert isinstance(fake, LLMAdapter)
    assert isinstance(doctor, DoctorAgentInterface)

    decision = doctor.decide(
        agent_input(case_definition, qualified_player_state)
    )

    assert decision.action.action_id == "agent_step_001"
    assert decision.llm_attempts == 1
    assert decision.used_fallback is False
    assert len(fake.requests) == 1
    serialized_prompt = "\n".join(
        message.content for message in fake.requests[0].messages
    )
    assert case_definition.root_cause not in serialized_prompt
    assert "root_cause" not in serialized_prompt
    assert "causal_chain" not in serialized_prompt
    assert "hidden_information" not in serialized_prompt
    assert "valid_diagnosis_ids" not in serialized_prompt
    assert "diagnosis_correct" not in serialized_prompt
    assert "key_clue_points" not in serialized_prompt
    assert '"outcome"' not in serialized_prompt
    assert "resolved" not in serialized_prompt
    assert "suppressed" not in serialized_prompt
    assert "worsened" not in serialized_prompt
    assert "broken_promise" not in serialized_prompt
    assert "rain_vow_breach" in serialized_prompt
    assert "evil_spirit_attack" in serialized_prompt
    assert "exam_exhaustion" in serialized_prompt
    assert fake.requests[0].response_schema == AgentAction.model_json_schema()


def test_doctor_agent_only_sends_most_recent_messages(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    recent = tuple(
        ChatMessage(role=ChatRole.USER, content=f"对话_{index}")
        for index in range(1, 6)
    )
    fake = ScriptedFakeLLM([action_json(1)])
    doctor = DoctorAgent(fake, DoctorAgentConfig(recent_message_limit=2))

    doctor.decide(
        agent_input(
            case_definition,
            qualified_player_state,
            recent_messages=recent,
        )
    )

    request = fake.requests[0]
    assert len(request.messages) == 4
    contents = [message.content for message in request.messages]
    assert "对话_3" not in contents
    assert "对话_4" in contents
    assert "对话_5" in contents


def test_prompt_exposes_treatment_semantics_without_hidden_results(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    context_filter = AgentContextFilter()
    engine = CaseEngine()
    session = CaseSessionState(
        session_id="session_treatment_prompt",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )
    investigation = next(
        item
        for item in case_definition.investigations
        if item.investigation_id == "inspect_umbrella"
    )
    occurred_at = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
    session = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        InvestigationCommand(
            investigation_id=investigation.investigation_id,
            action_type=investigation.action_type,
            target_id=investigation.target_id,
            occurred_at=occurred_at,
        ),
    ).session
    session = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        SubmitDiagnosisCommand(
            diagnosis_id="evil_spirit_attack",
            occurred_at=occurred_at,
        ),
    ).session
    fake = ScriptedFakeLLM([action_json(1)])

    DoctorAgent(fake).decide(
        DoctorAgentInput(
            step_index=1,
            player_view=context_filter.player_view(qualified_player_state),
            case_observation=context_filter.case_observation(
                case_definition,
                qualified_player_state,
                session,
            ),
            fixed_lesson=FixedV0Curriculum().lesson_for_step(1),
        )
    )

    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    for treatment_id in ("burn_old_umbrella", "seal_old_umbrella"):
        treatment = case_definition.treatments[treatment_id]
        assert treatment.public_description in prompt
        assert treatment.description not in prompt
    assert '"outcome"' not in prompt
    assert "required_clue_ids" not in prompt
    assert "unsafe_treatment_penalty" not in prompt


def test_invalid_format_is_repaired_once(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(["not-json", action_json(1, "修复后再观察。")])
    doctor = DoctorAgent(fake)

    decision = doctor.decide(
        agent_input(case_definition, qualified_player_state)
    )

    assert decision.action.dialogue == "修复后再观察。"
    assert decision.llm_attempts == 2
    assert decision.used_fallback is False
    assert len(fake.requests) == 2
    assert "只修复 JSON 格式和字段" in fake.requests[1].messages[-1].content


def test_two_invalid_formats_use_deterministic_non_mutating_fallback(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(["not-json", '{"also":"invalid"}', action_json(1)])
    doctor = DoctorAgent(fake)

    decision = doctor.decide(
        agent_input(case_definition, qualified_player_state)
    )

    assert decision.action == AgentAction(
        action_id="agent_step_001",
        action_type=AgentActionType.RESPOND,
        dialogue="此刻先停一步，只据已知线索再作判断。",
        confidence=0.0,
    )
    assert decision.llm_attempts == 2
    assert decision.used_fallback is True
    assert len(fake.requests) == 2
    assert fake.remaining_responses == 1


def test_adapter_failure_uses_fallback_without_unbounded_retry(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM([RuntimeError("provider unavailable"), action_json(1)])
    doctor = DoctorAgent(fake)

    decision = doctor.decide(
        agent_input(case_definition, qualified_player_state)
    )

    assert decision.used_fallback is True
    assert decision.llm_attempts == 1
    assert len(fake.requests) == 1
    assert fake.remaining_responses == 1


def test_charged_adapter_failure_preserves_returned_usage(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    measured = ModelUsage(
        provider_model="deepseek-v4-flash",
        input_tokens=100,
        output_tokens=20,
        cache_hit_input_tokens=0,
        cache_miss_input_tokens=100,
        reasoning_tokens=0,
        latency_ms=10.0,
        estimated_cost=Decimal("0.00014"),
        cost_currency="CNY",
        provider_request_id="request_truncated",
    )
    fake = ScriptedFakeLLM(
        [LLMAdapterError("charged response rejected", usage=measured)]
    )

    decision = DoctorAgent(fake).decide(
        agent_input(case_definition, qualified_player_state)
    )

    assert decision.used_fallback is True
    assert decision.llm_attempts == 1
    assert decision.usages == (measured,)


def test_wrong_episode_action_id_also_gets_one_repair(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    wrong_id = AgentAction(
        action_id="agent_step_999",
        action_type=AgentActionType.RESPOND,
        dialogue="错误编号。",
        confidence=0.5,
    ).model_dump_json()
    fake = ScriptedFakeLLM([wrong_id, action_json(1)])

    decision = DoctorAgent(fake).decide(
        agent_input(case_definition, qualified_player_state)
    )

    assert decision.action.action_id == "agent_step_001"
    assert decision.llm_attempts == 2


def test_fixed_curriculum_depends_only_on_step_number() -> None:
    curriculum = FixedV0Curriculum()

    assert curriculum.lesson_for_step(1).startswith("第一课")
    assert curriculum.lesson_for_step(2).startswith("第二课")
    assert curriculum.lesson_for_step(99).startswith("第五课")
