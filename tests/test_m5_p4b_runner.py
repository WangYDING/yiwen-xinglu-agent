from __future__ import annotations

import json
from collections import deque
from decimal import Decimal
from pathlib import Path

import pytest

from xuanyi_npc.agents import (
    DeepSeekModelDiscovery,
    LLMRequest,
    LLMResponse,
    build_reference_fake_agent,
)
from xuanyi_npc.agents.llm import ChatMessage, ChatRole
from xuanyi_npc.domain import AgentAction, CaseSessionStatus
from xuanyi_npc.evaluation import EpisodeStatus
from xuanyi_npc.evaluation.m5_p4b_runner import (
    AuditedLLMAdapter,
    M5P4bCampaignRunner,
    P4B_BUDGET_CNY,
    P4bRunStatus,
    build_service,
    main,
    prepare_deterministic_history,
)


class OfflineBudget:
    max_cost_cny = P4B_BUDGET_CNY
    known_cost_cny = Decimal("0")
    maximum_committed_cost_cny = Decimal("0")
    can_start_episode = True


class OfflineScriptedAdapter:
    def __init__(self, responses: tuple[str, ...]) -> None:
        self.responses = deque(responses)
        self.requests: list[LLMRequest] = []
        self.request_budget = OfflineBudget()

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self.responses.popleft())


def reference_responses(service, *case_ids: str) -> tuple[str, ...]:
    values: list[str] = []
    for case_id in case_ids:
        case = service.case_catalog.get(case_id)
        assert case is not None
        _, fake = build_reference_fake_agent(case)
        values.extend(fake._responses)
    return tuple(values)


def discovery() -> DeepSeekModelDiscovery:
    return DeepSeekModelDiscovery(
        configured_model="deepseek-v4-flash",
        available_models=("deepseek-v4-flash",),
        configured_model_available=True,
    )


def test_free_history_is_completed_and_replayable_before_provider_use(
    tmp_path: Path,
) -> None:
    service = build_service(tmp_path / "state")
    player_id, old = prepare_deterministic_history(service)
    campaign = service.state_store.load_campaign(player_id)

    assert old.episode_result.status is EpisodeStatus.COMPLETED
    assert old.episode_result.final_session.score == 100
    assert old.episode_result.final_session.selected_treatment_id == (
        "return_token_and_fulfill_vow"
    )
    assert "contract_provenance_check" in campaign.unlocked_knowledge_ids
    assert tuple(event.sequence for event in campaign.event_history) == (1,)


def test_campaign_runner_executes_each_paid_case_once_and_in_order(
    tmp_path: Path,
) -> None:
    service = build_service(tmp_path / "state")
    player_id, old = prepare_deterministic_history(service)
    adapter = OfflineScriptedAdapter(
        reference_responses(service, "gray_hearth_inn", "moon_well_echo")
    )
    result = M5P4bCampaignRunner(
        service=service,
        adapter=adapter,  # type: ignore[arg-type]
        discovery=discovery(),
        execution_commit="1" * 40,
        run_id="offline_p4b",
        player_id=player_id,
        old_paper=old,
    ).run(tmp_path / "results" / "result.json")

    assert result.status is P4bRunStatus.COMPLETED
    assert result.chat_request_count == 16
    assert result.gray_hearth is not None
    assert result.moon_well is not None
    assert result.gray_hearth.episode_result.final_session.score == 100
    assert result.moon_well.episode_result.final_session.score == 100
    assert result.gray_context is not None
    assert "contract_provenance_check" in result.gray_context.unlocked_knowledge_ids
    assert result.moon_context is not None
    assert "handoff_sequence_check" in result.moon_context.unlocked_knowledge_ids
    campaign = service.state_store.load_campaign(player_id)
    assert tuple(event.sequence for event in campaign.event_history) == (1, 2, 3)
    assert len(service.state_store.list_case_sessions()) == 3
    assert result.old_paper_replay_consistent
    assert result.gray_episode_replay_consistent
    assert result.gray_campaign_replay_consistent
    assert result.moon_episode_replay_consistent
    assert result.moon_campaign_replay_consistent
    assert all(not item.semantic_memory_markers_found for item in result.request_audits)


def test_gray_incomplete_stops_before_moon_starts(tmp_path: Path) -> None:
    service = build_service(tmp_path / "state")
    player_id, old = prepare_deterministic_history(service)
    adapter = OfflineScriptedAdapter(
        tuple(
            AgentAction(
                action_id=f"agent_step_{index:03d}",
                action_type="respond",
                dialogue="仅作说明，不提交工具。",
                tool_call=None,
                confidence=0.5,
            ).model_dump_json()
            for index in range(1, 9)
        )
    )
    result = M5P4bCampaignRunner(
        service=service,
        adapter=adapter,  # type: ignore[arg-type]
        discovery=discovery(),
        execution_commit="2" * 40,
        run_id="offline_gray_stop",
        player_id=player_id,
        old_paper=old,
    ).run(tmp_path / "results" / "result.json")

    assert result.status is P4bRunStatus.STOPPED_AFTER_GRAY
    assert result.moon_well is None
    assert result.chat_request_count == 8
    sessions = service.state_store.list_case_sessions()
    assert len(sessions) == 2
    assert all(item.case_id != "moon_well_echo" for item in sessions)
    assert sessions[-1].status is CaseSessionStatus.ACTIVE


def test_request_audit_blocks_semantic_memory_before_delegate_call() -> None:
    delegate = OfflineScriptedAdapter(("unused",))
    audited = AuditedLLMAdapter(delegate)
    request = LLMRequest(
        messages=(
            ChatMessage(role=ChatRole.SYSTEM, content="输出 JSON。"),
            ChatMessage(role=ChatRole.USER, content="retrieved_memories 必须被阻止。"),
        ),
        response_schema=AgentAction.model_json_schema(),
    )

    with pytest.raises(RuntimeError, match="semantic memory marker"):
        audited.complete(request)
    assert delegate.requests == []
    assert audited.audits[0].semantic_memory_markers_found == (
        "retrieved_memories",
    )


def test_missing_paid_confirmation_stops_before_configuration_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("network/configuration must not be reached")

    monkeypatch.setattr(
        "xuanyi_npc.evaluation.m5_p4b_runner.build_authorized_deepseek_v0_agent",
        forbidden,
    )
    code = main(
        (
            "--run-id",
            "offline_gate",
            "--freeze-commit",
            "3" * 40,
            "--state-dir",
            str(tmp_path / "state"),
            "--output",
            str(tmp_path / "results" / "out.json"),
            "--budget-cny",
            "0.05",
        )
    )
    assert code == 2
    assert calls == 0


def test_runner_source_contains_no_new_case_answer_ids() -> None:
    source = Path(
        "src/xuanyi_npc/evaluation/m5_p4b_runner.py"
    ).read_text(encoding="utf-8")
    assert "displaced_hearth_contract" not in source
    assert "restore_token_and_clear_flue" not in source
    assert "misbound_message_handoff" not in source
    assert "verify_recipient_and_deliver" not in source


def test_serialized_result_contains_no_provider_request_id_or_prompt(
    tmp_path: Path,
) -> None:
    service = build_service(tmp_path / "state")
    player_id, old = prepare_deterministic_history(service)
    adapter = OfflineScriptedAdapter(tuple(
        AgentAction(
            action_id=f"agent_step_{index:03d}",
            action_type="respond",
            dialogue="公开说明。",
            tool_call=None,
            confidence=0.5,
        ).model_dump_json()
        for index in range(1, 9)
    ))
    output = tmp_path / "results" / "result.json"
    M5P4bCampaignRunner(
        service=service,
        adapter=adapter,  # type: ignore[arg-type]
        discovery=discovery(),
        execution_commit="4" * 40,
        run_id="offline_serialization",
        player_id=player_id,
        old_paper=old,
    ).run(output)
    serialized = output.read_text(encoding="utf-8")
    parsed = json.loads(serialized)
    assert "provider_request_id" not in serialized
    assert "messages" not in serialized
    assert parsed["semantic_shadow"] == "off"
