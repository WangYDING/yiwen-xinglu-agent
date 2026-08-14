from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from xuanyi_npc.agents import AgentRepairKind, DoctorAgent, ScriptedFakeLLM
from xuanyi_npc.application.action_contract import (
    PublicActionContractError,
    PublicActionContractValidator,
    build_safe_action_feedback,
)
from xuanyi_npc.application.gameplay_modes import (
    GameplayMode,
    GameplayModeConfig,
    ModeAwareEpisodeRunner,
    ModeRunInput,
)
from xuanyi_npc.application.multicase import (
    CreatePlayerInput,
    StartEpisodeInput,
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.evaluation import EpisodeStatus
from xuanyi_npc.evaluation.m5_p4b_runner import build_service


ROOT = Path(__file__).parents[1]
CASE_IDS = ("old_paper_umbrella", "gray_hearth_inn", "moon_well_echo")
P4B_SHA256 = "EFDC6B37692CAA117B352DD199B52AAFF20D765945E5C8FB585994453B712C2B"


def action_json(
    *,
    tool: ToolName,
    arguments: dict[str, object],
    action_id: str = "agent_step_001",
) -> str:
    return AgentAction(
        action_id=action_id,
        action_type=AgentActionType.USE_TOOL,
        dialogue="只依据公开选项执行。",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=0.8,
    ).model_dump_json()


def opened_case(root: Path, case_id: str):
    service = build_service(root)
    created = service.create_player(CreatePlayerInput(display_name="契约测试玩家"))
    assert created.ok and created.player_id is not None
    opened = service.start_episode(
        StartEpisodeInput(player_id=created.player_id, case_id=case_id)
    )
    assert opened.ok and opened.session_id is not None and opened.observation is not None
    return service, created.player_id, opened


def test_outer_agent_action_schema_keeps_generic_arguments_for_provider_contract() -> None:
    action = AgentAction.model_validate_json(
        action_json(
            tool=ToolName.QUESTION_PATIENT,
            arguments={"target_id": "cook_shen"},
        )
    )

    assert action.tool_call is not None
    assert action.tool_call.arguments == {"target_id": "cook_shen"}


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_target_id_is_repaired_through_one_shared_contract_for_all_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    service, player_id, opened = opened_case(tmp_path / case_id, case_id)
    option = next(
        item
        for item in opened.observation.available_investigations
        if item.action_type is CaseActionType.QUESTION_PATIENT
    )
    fake = ScriptedFakeLLM(
        (
            action_json(
                tool=ToolName.QUESTION_PATIENT,
                arguments={"target_id": option.target_id},
            ),
            action_json(
                tool=ToolName.QUESTION_PATIENT,
                arguments={"investigation_id": option.investigation_id},
            ),
        )
    )
    submitted: list[AgentAction] = []
    original = service.submit_action_with_receipt

    def capture(request):
        submitted.append(request.action)
        return original(request)

    monkeypatch.setattr(service, "submit_action_with_receipt", capture)
    result = ModeAwareEpisodeRunner(
        service=service,
        doctor_agent=DoctorAgent(fake),
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=1),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id=case_id,
            session_id=opened.session_id,
        )
    )

    step = result.episode_result.steps[0]
    assert step.accepted is True
    assert step.event_sequences == (1,)
    assert step.llm_attempts == 2
    assert step.repair_kind is AgentRepairKind.ACTION_CONTRACT_REPAIR
    assert len(fake.requests) == 2
    assert len(submitted) == 1
    assert submitted[0].tool_call is not None
    assert submitted[0].tool_call.arguments == {
        "investigation_id": option.investigation_id
    }
    assert result.episode_result.final_session.revision == 1


def test_diagnosis_not_ready_repair_uses_only_refreshed_public_options(
    tmp_path: Path,
) -> None:
    service, player_id, opened = opened_case(
        tmp_path / "diagnosis",
        "gray_hearth_inn",
    )
    observation = opened.observation
    diagnosis_id = observation.diagnosis_candidates[0].diagnosis_id
    option = observation.available_investigations[0]
    expected_tool = {
        CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
        CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
        CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
        CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
        CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
    }[option.action_type]
    fake = ScriptedFakeLLM(
        (
            action_json(
                tool=ToolName.SUBMIT_DIAGNOSIS,
                arguments={"diagnosis_id": diagnosis_id, "evidence_clue_ids": []},
            ),
            action_json(
                tool=expected_tool,
                arguments={"investigation_id": option.investigation_id},
            ),
        )
    )
    result = ModeAwareEpisodeRunner(
        service=service,
        doctor_agent=DoctorAgent(fake),
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=1),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id="gray_hearth_inn",
            session_id=opened.session_id,
        )
    )

    assert result.episode_result.steps[0].accepted is True
    assert result.episode_result.steps[0].repair_kind is (
        AgentRepairKind.ACTION_CONTRACT_REPAIR
    )
    repair_text = fake.requests[1].messages[-1].content
    assert '"error_code": "diagnosis_not_ready"' in repair_text
    assert '"can_submit_diagnosis": false' in repair_text
    assert '"tool_name"' in repair_text
    assert '"investigation_id"' in repair_text
    assert "口头描述不等于提交诊断" in repair_text
    for forbidden in (
        "root_cause",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "score",
        "retrieved_memories",
        "memory_id",
    ):
        assert forbidden not in repair_text


def test_second_contract_error_falls_back_without_third_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, player_id, opened = opened_case(tmp_path / "bounded", "gray_hearth_inn")
    option = next(
        item
        for item in opened.observation.available_investigations
        if item.action_type is CaseActionType.QUESTION_PATIENT
    )
    wrong = action_json(
        tool=ToolName.QUESTION_PATIENT,
        arguments={"target_id": option.target_id},
    )
    fake = ScriptedFakeLLM((wrong, wrong, wrong))
    service_calls = 0

    def forbidden_submit(request):
        del request
        nonlocal service_calls
        service_calls += 1
        raise AssertionError("invalid contract must not reach the state service")

    monkeypatch.setattr(service, "submit_action_with_receipt", forbidden_submit)
    result = ModeAwareEpisodeRunner(
        service=service,
        doctor_agent=DoctorAgent(fake),
        config=GameplayModeConfig(gameplay_mode=GameplayMode.FAKE, max_steps=1),
    ).run(
        ModeRunInput(
            player_id=player_id,
            case_id="gray_hearth_inn",
            session_id=opened.session_id,
        )
    )

    step = result.episode_result.steps[0]
    assert step.accepted is False
    assert step.error_code == "invalid_tool_arguments"
    assert step.used_fallback is True
    assert step.repair_kind is AgentRepairKind.ACTION_CONTRACT_REPAIR
    assert len(fake.requests) == 2
    assert fake.remaining_responses == 1
    assert service_calls == 0
    assert result.episode_result.events == ()
    assert result.episode_result.final_session.revision == 0
    assert result.public_result.ok is False
    assert result.public_result.error_code == "invalid_tool_arguments"
    assert result.campaign_event_sequences == ()


def test_unknown_mismatch_extra_and_wrong_evidence_fail_before_state_write(
    tmp_path: Path,
) -> None:
    service, _, opened = opened_case(tmp_path / "invalid", "old_paper_umbrella")
    observation = opened.observation
    option = observation.available_investigations[0]
    validator = PublicActionContractValidator()
    invalid = (
        (
            action_json(
                tool=ToolName.OBSERVE_PATIENT,
                arguments={"investigation_id": "unknown_public_option"},
            ),
            "unknown_investigation",
        ),
        (
            action_json(
                tool=ToolName.OBSERVE_QI,
                arguments={"investigation_id": option.investigation_id},
            ),
            "action_mismatch",
        ),
        (
            action_json(
                tool=ToolName.OBSERVE_PATIENT,
                arguments={
                    "investigation_id": option.investigation_id,
                    "target_id": option.target_id,
                },
            ),
            "invalid_tool_arguments",
        ),
        (
            action_json(
                tool=ToolName.SUBMIT_DIAGNOSIS,
                arguments={
                    "diagnosis_id": observation.diagnosis_candidates[0].diagnosis_id,
                    "evidence_clue_ids": ["hidden_unseen_clue"],
                },
            ),
            "diagnosis_not_ready",
        ),
        (
            action_json(
                tool=ToolName.EXECUTE_TREATMENT,
                arguments={"treatment_id": "unknown_public_treatment"},
            ),
            "unknown_treatment",
        ),
    )
    before = tuple(
        (path.name, path.read_bytes())
        for path in sorted((tmp_path / "invalid").rglob("*.json"))
    )
    for serialized, expected_code in invalid:
        with pytest.raises(PublicActionContractError) as captured:
            validator.validate(AgentAction.model_validate_json(serialized), observation)
        assert captured.value.code == expected_code
    ready_observation = observation.model_copy(
        update={"can_submit_diagnosis": True}
    )
    wrong_evidence = AgentAction.model_validate_json(
        action_json(
            tool=ToolName.SUBMIT_DIAGNOSIS,
            arguments={
                "diagnosis_id": observation.diagnosis_candidates[0].diagnosis_id,
                "evidence_clue_ids": ["hidden_unseen_clue"],
            },
        )
    )
    with pytest.raises(PublicActionContractError) as captured:
        validator.validate(wrong_evidence, ready_observation)
    assert captured.value.code == "evidence_not_discovered"
    after = tuple(
        (path.name, path.read_bytes())
        for path in sorted((tmp_path / "invalid").rglob("*.json"))
    )
    assert before == after
    assert service.state_store.load_case_session(opened.session_id).revision == 0


def test_safe_feedback_is_strict_public_data(tmp_path: Path) -> None:
    service, _, opened = opened_case(
        tmp_path / "feedback",
        "moon_well_echo",
    )
    feedback = build_safe_action_feedback(
        "diagnosis_not_ready",
        opened.observation,
    )
    serialized = feedback.model_dump_json()
    assert feedback.can_submit_diagnosis is False
    assert all(item.tool_name.value for item in feedback.available_investigations)
    assert "口头描述不等于提交诊断" in serialized
    for forbidden in (
        "root_cause",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "causal_chain",
        "retrieved_memories",
        "embedding_space_id",
    ):
        assert forbidden not in serialized


def test_contract_implementation_has_no_case_specific_branches() -> None:
    source = (ROOT / "src/xuanyi_npc/application/action_contract.py").read_text(
        encoding="utf-8"
    )
    for case_id in CASE_IDS:
        assert case_id not in source


def test_p4b_history_report_and_optional_raw_result_keep_original_sha() -> None:
    report = (
        ROOT / "docs/archive/M5_P4B_DEEPSEEK_CAMPAIGN_PILOT_20260811.md"
    ).read_text(encoding="utf-8")
    assert P4B_SHA256 in report
    raw = ROOT / "results/m5_p4b_campaign_20260811.json"
    if raw.exists():
        assert hashlib.sha256(raw.read_bytes()).hexdigest().upper() == P4B_SHA256
