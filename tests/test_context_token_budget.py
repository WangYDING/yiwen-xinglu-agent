from dataclasses import replace
import json

import httpx
import pytest

from xuanyi_npc.agents import DeepSeekAdapterConfig, DeepSeekChatAdapter, ScriptedFakeLLM
from xuanyi_npc.agents.context import ContextAssembler
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMRequest, LLMResponse
from xuanyi_npc.agents.token_budget import ContextBudgetExceeded, ModelContextProfile, prepare_request, _tokenizer
from .context_baseline_support import planning_input
from .test_m3_game_npc_memory_context import memory_context, memory_item


def adapter(**kwargs):
    return DeepSeekChatAdapter(DeepSeekAdapterConfig(api_key="offline-test", **kwargs))


def total(trace):
    return trace.content_tokens + trace.framing_estimate + trace.output_tokens + trace.safety_margin


def test_final_schema_framing_and_output_are_counted_at_exact_boundary():
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    request = agent._planning_request(planning_input())
    with adapter() as provider:
        prepared = prepare_request(request, provider._chat_payload, ModelContextProfile())
        tokenizer, identity = _tokenizer()
        bare = sum(len(tokenizer.encode(m.content, add_special_tokens=False).ids) for m in request.messages)
        assert prepared.trace.content_tokens > bare
        assert prepared.trace.tokenizer_sha256 == identity
        assert prepared.trace.output_tokens == 2048
        boundary = replace(ModelContextProfile(), context_window=total(prepared.trace))
        exact = prepare_request(request.model_copy(update={"context_variants": ()}), provider._chat_payload, boundary)
        assert exact.payload == prepared.payload
        with pytest.raises(ContextBudgetExceeded):
            prepare_request(request.model_copy(update={"context_variants": ()}), provider._chat_payload, replace(boundary, context_window=boundary.context_window - 1))


def test_oversized_required_schema_never_sends_or_reserves_money():
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda req: sent.append(req)))
    with DeepSeekChatAdapter(DeepSeekAdapterConfig(api_key="offline-test", context_window=64), client=client) as provider:
        request = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(planning_input())
        with pytest.raises(ContextBudgetExceeded) as error:
            provider.complete(request)
        assert error.value.code == "context_budget_exceeded"
        assert not sent
        assert provider.request_budget.maximum_committed_cost_cny == 0
        assert provider.last_context_budget() is not None
    client.close()


def test_selection_keeps_pairs_contracts_and_immutable_public_state():
    value = planning_input()
    memory = memory_context(memory_item("memory_low", "低相关经验"), memory_item("memory_high", "高相关经验"))
    low, high = memory.memories
    memory = memory.model_copy(update={"memories": (low.model_copy(update={"relevance_score": 0.1}), high.model_copy(update={"relevance_score": 0.9}))})
    history = (ChatMessage(role=ChatRole.USER, content="OLD_USER " * 3000), ChatMessage(role=ChatRole.ASSISTANT, content="OLD_ASSISTANT " * 3000))
    value = value.model_copy(update={"memory_context": memory, "recent_messages": history})
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    request = agent._planning_request(value)
    before = value.model_dump_json()
    with adapter() as provider:
        minimal = request.context_variants[-1]
        measure = prepare_request(request.model_copy(update={"messages": minimal.messages, "context_variants": ()}), provider._chat_payload, ModelContextProfile(context_window=200_000))
        profile = ModelContextProfile(context_window=total(measure.trace))
        result = prepare_request(request, provider._chat_payload, profile)
        assert result.trace.selection == minimal.reason
        assert result.trace.retained_memory_ids == ()
        assert [m["role"] for m in result.payload["messages"]] == ["system", "user"]
        text = result.payload["messages"][-1]["content"]
        assert "OLD_USER" not in text and "OLD_ASSISTANT" not in text
        assert "EXECUTABLE_ACTIVE_STEP_CONTRACT" in text
        assert value.current_plan.model_dump_json(indent=2) in text
        assert value.case_observation.model_dump_json(indent=2) in text
        assert "HISTORICAL_NON_AUTHORITATIVE_CONTEXT_memory_context" in text
        assert prepare_request(request, provider._chat_payload, profile) == result
        assert value.model_dump_json() == before
        one = next(v for v in request.context_variants if v.reason.startswith("memory_remaining:1"))
        assert one.retained_memory_ids == ("memory_high",)


def test_repair_increment_is_rebudgeted_with_explicit_output_limit():
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    value = planning_input()
    initial = agent._planning_request(value).model_copy(update={"context_variants": ()})
    repair = agent._format_planning_repair_request(initial, LLMResponse(content="invalid " * 1000), ValueError("invalid"), value)
    assert repair.max_output_tokens == initial.max_output_tokens == 2048
    with adapter() as provider:
        first = prepare_request(initial, provider._chat_payload, ModelContextProfile())
        with pytest.raises(ContextBudgetExceeded):
            prepare_request(repair, provider._chat_payload, ModelContextProfile(context_window=total(first.trace)))
        second = prepare_request(repair, provider._chat_payload, ModelContextProfile())
        assert second.trace.content_tokens > first.trace.content_tokens
        assert second.trace.framing_estimate > first.trace.framing_estimate


def test_large_input_can_reach_token_budget_and_history_is_not_split():
    history = (ChatMessage(role=ChatRole.USER, content="用户" * 12000), ChatMessage(role=ChatRole.ASSISTANT, content="答复"))
    messages = (ChatMessage(role=ChatRole.SYSTEM, content="规则"), *history, ChatMessage(role=ChatRole.USER, content="当前请求"))
    variants = ContextAssembler._variants(messages)
    request = LLMRequest(messages=messages, response_schema={"type": "object"}, max_output_tokens=512, context_variants=variants)
    with adapter(context_window=2048) as provider:
        result = prepare_request(request, provider._chat_payload, ModelContextProfile(context_window=2048))
        assert len(result.payload["messages"]) == 2
        assert result.trace.selection == "history_pairs_removed:1"


def test_provider_sends_the_exact_measured_payload():
    captured = []
    def respond(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200, json={"id": "test", "model": "deepseek-v4-flash", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 10}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with DeepSeekChatAdapter(DeepSeekAdapterConfig(api_key="offline-test"), client=client) as provider:
            request = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(planning_input())
            expected = prepare_request(request, provider._chat_payload, ModelContextProfile())
            provider.complete(request)
            assert captured == [expected.payload]
            assert provider.last_context_budget() == expected.trace


def test_runtime_budget_failure_is_public_feedback_without_world_mutation(tmp_path):
    from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
    from .test_m2_cooperative_runtime_planning import opened_case, contribution
    service, player_id, opened = opened_case(tmp_path)
    before = service.state_store.load_case_session(opened.session_id)
    with adapter(context_window=64) as provider:
        agent = GameNPCAgent(provider)
        runtime = CooperativeRuntime(service=service, agent=agent)
        runtime.handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id, "budget_first")))
        stored = service.state_store.load_cooperative_agent_state(opened.session_id)
        feedback = stored.last_decision_feedback
        assert feedback.stage == "budget"
        assert feedback.reason_code == "context_budget_exceeded"
        assert service.state_store.load_case_session(opened.session_id) == before
        attempt = agent.last_planning_execution().attempt_telemetry[0]
        assert attempt.context_budget["output_tokens"] == 2048
        assert attempt.failure_code == "context_budget_exceeded"
        runtime.handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id, "budget_second")))
        assert agent.last_planning_input().last_decision_feedback == feedback
        assert "PUBLIC_DECISION_FEEDBACK_not_authorization" in agent._planning_request(agent.last_planning_input()).messages[-1].content
        assert service.state_store.load_case_session(opened.session_id) == before


def test_budget_removed_memory_cannot_be_claimed(case_definition, qualified_player_state):
    from types import SimpleNamespace
    from xuanyi_npc.domain.planning_contract import MemoryUsageProposal
    from .test_m3_game_npc_memory_context import npc_input, proposal_for
    value = npc_input(case_definition, qualified_player_state, memory_context=memory_context(memory_item("removed", "历史经验")))
    proposal = proposal_for(value, memory_usage=MemoryUsageProposal(used_memory_ids=("removed",), influence_types=("plan_priority",), affected_plan=True, public_effect_summary="声称依据已删除经验。"))
    fake = ScriptedFakeLLM([])
    fake.last_context_budget = lambda: SimpleNamespace(retained_memory_ids=())
    with pytest.raises(ValueError, match="selected memory"):
        GameNPCAgent(fake)._validate_memory_usage(proposal, value)


def test_untrusted_marker_does_not_change_memory_boundaries():
    value = planning_input()
    marker = "HISTORICAL_NON_AUTHORITATIVE_CONTEXT_memory_context:\n"
    observation = value.case_observation.model_copy(update={"synopsis": marker + "untrusted marker"})
    value = value.model_copy(update={"case_observation": observation, "memory_context": memory_context(memory_item("safe_memory", "公开经验"))})
    request = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(value)
    for variant in request.context_variants:
        assert observation.model_dump_json(indent=2) in variant.messages[-1].content
