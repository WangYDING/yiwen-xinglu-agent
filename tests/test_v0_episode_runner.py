from datetime import datetime, timedelta, timezone

import pytest

from xuanyi_npc.agents import (
    DoctorAgent,
    DoctorAgentConfig,
    ScriptedFakeLLM,
)
from xuanyi_npc.application.v0_runner import V0EpisodeConfig, V0EpisodeRunner
from xuanyi_npc.application.v0_tools import (
    InvalidToolArgumentsError,
    V0ToolExecutor,
)
from xuanyi_npc.application import AgentContextFilter, BasicCosineMemoryRetriever
from xuanyi_npc.application.memory_context import MemoryQueryBuilder
from xuanyi_npc.memory import DeterministicFakeEmbedding
from xuanyi_npc.storage import SQLiteMemoryRepository
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    CaseSessionState,
    PlayerState,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.engine import CaseEventReplayer
from xuanyi_npc.evaluation import EpisodeStatus


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self.current += timedelta(minutes=1)
        return self.current


def tool_action_json(
    step_index: int,
    tool_name: ToolName,
    arguments: dict[str, object],
    dialogue: str = "依规执行此步。",
) -> str:
    return AgentAction(
        action_id=f"agent_step_{step_index:03d}",
        action_type=AgentActionType.USE_TOOL,
        dialogue=dialogue,
        tool_call=ToolCallRequest(name=tool_name, arguments=arguments),
        confidence=0.9,
    ).model_dump_json()


def respond_action_json(step_index: int) -> str:
    return AgentAction(
        action_id=f"agent_step_{step_index:03d}",
        action_type=AgentActionType.RESPOND,
        dialogue="先不动病例状态。",
        confidence=0.5,
    ).model_dump_json()


def initial_session(case: CaseDefinition, player: PlayerState, suffix: str) -> CaseSessionState:
    return CaseSessionState(
        session_id=f"session_{suffix}",
        case_id=case.case_id,
        player_id=player.player_id,
    )


def completed_case_script() -> list[str]:
    investigation_steps = (
        (ToolName.OBSERVE_PATIENT, "observe_scholar"),
        (ToolName.QUESTION_PATIENT, "ask_about_memory"),
        (ToolName.INSPECT_OBJECT, "inspect_umbrella"),
        (ToolName.OBSERVE_QI, "observe_contract_trace"),
        (ToolName.INSPECT_OBJECT, "search_book_chest"),
        (ToolName.QUESTION_PATIENT, "ask_about_promise"),
    )
    responses = [
        tool_action_json(
            index,
            tool_name,
            {"investigation_id": investigation_id},
        )
        for index, (tool_name, investigation_id) in enumerate(
            investigation_steps,
            start=1,
        )
    ]
    responses.append(
        tool_action_json(
            7,
            ToolName.SUBMIT_DIAGNOSIS,
            {
                "diagnosis_id": "rain_vow_breach",
                "evidence_clue_ids": [
                    "broken_promise",
                    "cold_window_draft",
                    "exam_fatigue",
                    "fading_shadow",
                    "forgotten_faces",
                    "hidden_wooden_token",
                    "umbrella_night_water",
                    "vow_knot_trace",
                ],
            },
        )
    )
    responses.append(
        tool_action_json(
            8,
            ToolName.EXECUTE_TREATMENT,
            {"treatment_id": "return_token_and_fulfill_vow"},
        )
    )
    return responses


def test_fake_llm_runs_complete_v0_episode_through_rule_engine(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(completed_case_script())
    doctor = DoctorAgent(fake, DoctorAgentConfig(recent_message_limit=4))
    runner = V0EpisodeRunner(
        doctor,
        clock=StepClock(),
        config=V0EpisodeConfig(max_steps=8),
    )
    initial = initial_session(
        case_definition,
        qualified_player_state,
        "v0_complete",
    )

    episode = runner.run(
        "episode_v0_complete",
        case_definition,
        qualified_player_state,
        initial,
        "请按固定课程带我完成此病例。",
    )

    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.final_session.score == 100
    assert episode.final_session.revision == 8
    assert len(episode.steps) == 8
    assert len(episode.events) == 8
    assert all(step.accepted for step in episode.steps)
    assert CaseEventReplayer().replay(initial, episode.events) == episode.final_session
    assert initial.revision == 0
    assert fake.remaining_responses == 0
    assert len(fake.requests) == 8
    assert all(len(request.messages) <= 6 for request in fake.requests)
    first_prompt = "\n".join(
        message.content for message in fake.requests[0].messages
    )
    diagnosis_prompt = "\n".join(
        message.content for message in fake.requests[6].messages
    )
    assert '"can_submit_diagnosis": false' in first_prompt
    assert '"can_submit_diagnosis": true' in diagnosis_prompt


def test_v0_complete_episode_never_touches_any_v1_memory_boundary(
    monkeypatch: pytest.MonkeyPatch,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("V0 crossed a V1 memory boundary")

    monkeypatch.setattr(AgentContextFilter, "memory_scope", forbidden)
    monkeypatch.setattr(BasicCosineMemoryRetriever, "retrieve", forbidden)
    monkeypatch.setattr(BasicCosineMemoryRetriever, "retrieve_scoped", forbidden)
    monkeypatch.setattr(MemoryQueryBuilder, "build", forbidden)
    monkeypatch.setattr(DeterministicFakeEmbedding, "embed", forbidden)
    monkeypatch.setattr(SQLiteMemoryRepository, "list_memories", forbidden)
    fake = ScriptedFakeLLM(completed_case_script())
    runner = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=StepClock(),
        config=V0EpisodeConfig(max_steps=8),
    )
    initial = initial_session(
        case_definition,
        qualified_player_state,
        "v0_memory_zero_calls",
    )

    episode = runner.run(
        "episode_v0_memory_zero_calls",
        case_definition,
        qualified_player_state,
        initial,
        "继续固定课程。",
    )

    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.final_session.score == 100


def test_rule_rejection_is_recorded_without_state_change_or_hidden_error_detail(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(
        [
            tool_action_json(
                1,
                ToolName.OBSERVE_QI,
                {"investigation_id": "observe_scholar"},
                dialogue="尝试当前行动。",
            ),
            respond_action_json(2),
        ]
    )
    initial = initial_session(
        case_definition,
        qualified_player_state,
        "v0_rejection",
    )
    runner = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=StepClock(),
        config=V0EpisodeConfig(max_steps=2),
    )

    episode = runner.run(
        "episode_v0_rejection",
        case_definition,
        qualified_player_state,
        initial,
        "继续教学。",
    )

    assert episode.status is EpisodeStatus.MAX_STEPS_REACHED
    assert episode.final_session == initial
    assert episode.events == ()
    assert episode.steps[0].accepted is False
    assert episode.steps[0].error_code == "action_mismatch"
    assert episode.steps[1].accepted is True
    second_request_text = "\n".join(
        message.content for message in fake.requests[1].messages
    )
    assert "工具请求被确定性规则层拒绝" in second_request_text
    assert "tool name does not match" not in second_request_text


def test_fixed_v0_rejects_diagnosis_before_visible_investigations(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(
        [
            tool_action_json(
                1,
                ToolName.SUBMIT_DIAGNOSIS,
                {
                    "diagnosis_id": "evil_spirit_attack",
                    "evidence_clue_ids": ["broken_promise"],
                },
            )
        ]
    )
    initial = initial_session(
        case_definition,
        qualified_player_state,
        "v0_evidence_rejection",
    )

    episode = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=StepClock(),
        config=V0EpisodeConfig(max_steps=1),
    ).run(
        "episode_v0_evidence_rejection",
        case_definition,
        qualified_player_state,
        initial,
        "请诊断。",
    )

    assert episode.steps[0].accepted is False
    assert episode.steps[0].error_code == "diagnosis_not_ready"
    assert episode.final_session == initial
    assert episode.events == ()


def test_unknown_diagnosis_gets_sanitized_rejection_without_state_change(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(
        [
            tool_action_json(
                1,
                ToolName.SUBMIT_DIAGNOSIS,
                {
                    "diagnosis_id": "invented_diagnosis",
                    "evidence_clue_ids": [],
                },
            ),
            respond_action_json(2),
        ]
    )
    initial = initial_session(
        case_definition,
        qualified_player_state,
        "v0_unknown_diagnosis",
    )

    episode = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=StepClock(),
        config=V0EpisodeConfig(max_steps=2),
    ).run(
        "episode_v0_unknown_diagnosis",
        case_definition,
        qualified_player_state,
        initial,
        "请判断病因。",
    )

    assert episode.steps[0].accepted is False
    assert episode.steps[0].error_code == "unknown_diagnosis"
    assert episode.final_session == initial
    assert episode.events == ()
    second_request_text = "\n".join(
        message.content for message in fake.requests[1].messages
    )
    assert "工具请求被确定性规则层拒绝" in second_request_text
    assert "unknown diagnosis candidate" not in second_request_text


def test_tool_arguments_reject_unknown_fields_before_engine_execution(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    session = initial_session(
        case_definition,
        qualified_player_state,
        "v0_bad_arguments",
    )
    action = AgentAction(
        action_id="agent_step_001",
        action_type=AgentActionType.USE_TOOL,
        dialogue="尝试附加未声明参数。",
        tool_call=ToolCallRequest(
            name=ToolName.OBSERVE_PATIENT,
            arguments={
                "investigation_id": "observe_scholar",
                "target_id": "forged_target",
            },
        ),
        confidence=0.8,
    )

    with pytest.raises(InvalidToolArgumentsError):
        V0ToolExecutor().execute(
            action,
            case_definition,
            qualified_player_state,
            session,
            datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc),
        )

    assert session.revision == 0
    assert session.action_history == ()


def test_two_invalid_outputs_per_step_stop_at_max_steps_with_fallbacks(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    fake = ScriptedFakeLLM(["bad-1", "bad-2", "bad-3", "bad-4"])
    initial = initial_session(
        case_definition,
        qualified_player_state,
        "v0_fallback_limit",
    )

    episode = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=StepClock(),
        config=V0EpisodeConfig(max_steps=2),
    ).run(
        "episode_v0_fallback_limit",
        case_definition,
        qualified_player_state,
        initial,
        "继续。",
    )

    assert episode.status is EpisodeStatus.MAX_STEPS_REACHED
    assert len(episode.steps) == 2
    assert all(step.used_fallback for step in episode.steps)
    assert all(step.llm_attempts == 2 for step in episode.steps)
    assert len(fake.requests) == 4
    assert episode.final_session == initial
