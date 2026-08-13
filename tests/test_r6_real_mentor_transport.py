import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMRequest
from xuanyi_npc.domain.mentor import MentorAction
from xuanyi_npc.evaluation.episode import ModelUsage
from xuanyi_npc.evaluation.real_mentor_transport import (
    MAX_OUTPUT_TOKENS,
    MODEL_ID,
    MentorPilotBudget,
    MentorPilotTransportError,
    RealMentorDeepSeekTransport,
    load_mentor_pilot_pricing,
)
from xuanyi_npc.evaluation.real_mentor_runner import build_request, evaluate_content, validate_action


ROOT = Path(__file__).parents[1]
PRICING = load_mentor_pilot_pricing(ROOT / "src/xuanyi_npc/resources/pilot/deepseek_v4_flash_mentor_pricing_2026-08-13.json")


def request() -> LLMRequest:
    return LLMRequest(messages=(ChatMessage(role=ChatRole.SYSTEM, content="可信Mentor system prompt"), ChatMessage(role=ChatRole.USER, content='{"public_context":"只含公开教学事实"}')), response_schema=MentorAction.model_json_schema())


def usage(**overrides):
    values = dict(provider_model=MODEL_ID, input_tokens=100, output_tokens=50, cache_hit_input_tokens=40, cache_miss_input_tokens=60, reasoning_tokens=0, latency_ms=1.0, estimated_cost=Decimal("0"), cost_currency="CNY")
    values.update(overrides)
    return ModelUsage(**values)


def test_payload_is_mentor_only_and_fixed_provider_contract():
    payload = RealMentorDeepSeekTransport.build_payload(request())
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False and payload["max_tokens"] == MAX_OUTPUT_TOKENS
    assert "MentorAction" in text
    for forbidden in ("AgentAction", "diagnose_case", "submit_diagnosis", "use_case_tool", "MCP", "MENTOR_SECRET", "retrieved_memories"):
        assert forbidden not in text


def test_decimal_budget_ignores_environment_and_reserves_every_request(monkeypatch):
    monkeypatch.setenv("XUANYI_PILOT_MAX_COST_CNY", "1.00")
    guard = MentorPilotBudget(Decimal("0.05"), PRICING)
    amount = guard.reserve(RealMentorDeepSeekTransport.build_payload(request()))
    assert guard.limit == Decimal("0.05") and amount > 0
    cost = guard.settle(usage())
    assert cost == Decimal("0.0001608")
    assert guard.confirmed_cost == cost


def test_budget_rejection_has_zero_http_calls():
    called = 0
    def handler(_request):
        nonlocal called
        called += 1
        return httpx.Response(500)
    guard = MentorPilotBudget(Decimal("0.05"), PRICING)
    guard.confirmed_cost = Decimal("0.049999")
    transport = RealMentorDeepSeekTransport(SecretStr("placeholder"), guard, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MentorPilotTransportError, match="budget_exceeded"):
        transport.complete(request())
    assert called == 0


def test_missing_usage_halts_and_preserves_reserve():
    def handler(_request):
        return httpx.Response(200, json={"id":"provider-secret","model":MODEL_ID,"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]})
    guard = MentorPilotBudget(Decimal("0.05"), PRICING)
    transport = RealMentorDeepSeekTransport(SecretStr("placeholder"), guard, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MentorPilotTransportError, match="chat_schema_or_usage_invalid"):
        transport.complete(request())
    assert guard.halted and guard.unverified_reserve > 0


def test_models_missing_flash_stops_without_chat():
    calls=[]
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200,json={"object":"list","data":[{"id":"deepseek-v4-pro"}]})
    transport=RealMentorDeepSeekTransport(SecretStr("placeholder"),MentorPilotBudget(Decimal("0.05"),PRICING),client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MentorPilotTransportError,match="configured_model_unavailable"):
        transport.discover_flash()
    assert calls==["/models"] and transport.chat_calls==0


def test_response_model_mismatch_is_detected_after_usage_settlement():
    def handler(_request):
        return httpx.Response(200,json={"id":"provider-secret","model":"deepseek-v4-pro","choices":[{"finish_reason":"stop","message":{"content":"{}"}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"prompt_cache_hit_tokens":0,"prompt_cache_miss_tokens":1}})
    guard=MentorPilotBudget(Decimal("0.05"),PRICING)
    transport=RealMentorDeepSeekTransport(SecretStr("placeholder"),guard,client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MentorPilotTransportError,match="response_model_mismatch"):
        transport.complete(request())
    assert guard.confirmed_cost > 0


def fixture_item():
    return {"scenario_id":"mock","request_id":"mock_1","public_context":{"lesson":"公开课程"},"allowed_action_types":["speak"],"allowed_hint_ids":[],"expectation":{"accepted_action_types":["speak"],"required_concept_groups":[["弟子","学徒"],["亲自"]],"forbidden_terms":["正确答案","隐藏门槛"],"player_action_claims":["我已替你调查"]}}


def test_contract_repair_request_uses_same_public_context_and_public_code_only():
    item=fixture_item()
    first=build_request(item)
    repair=build_request(item,repair_code="action_type_not_allowed")
    assert first.messages[:2] == repair.messages[:2]
    assert "action_type_not_allowed" in repair.messages[-1].content
    assert "正确答案" not in repair.messages[-1].content


def test_schema_valid_content_errors_are_not_contract_repair_conditions():
    item=fixture_item()
    action=validate_action(item,'{"action_type":"speak","message":"正确答案是某项，我已替你调查。"}')
    result=evaluate_content(item,action)
    assert result["teaching_correct"] is False
    assert result["safe"] is False
    assert result["forbidden_leaks"] and result["mentor_replaced_player_action"]


def test_invalid_action_type_is_contract_failure():
    with pytest.raises(ValueError,match="action_type_not_allowed"):
        validate_action(fixture_item(),'{"action_type":"offer_inheritance","message":"已授予"}')


def test_timeout_halts_without_retry_and_preserves_reserve():
    calls=0
    def handler(_request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout")
    guard=MentorPilotBudget(Decimal("0.05"),PRICING)
    transport=RealMentorDeepSeekTransport(SecretStr("placeholder"),guard,client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MentorPilotTransportError,match="timeout"):
        transport.complete(request())
    assert calls == 1 and guard.halted and guard.unverified_reserve > 0
