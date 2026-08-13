import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

import xuanyi_npc.evaluation.real_mentor_v3_runner as runner
from xuanyi_npc.application.mentor_communication import MentorActionV2
from xuanyi_npc.evaluation.episode import ModelUsage
from xuanyi_npc.evaluation.real_mentor_transport import MentorPilotBudget, MentorPilotTransportError


ROOT=Path(__file__).parents[1]


def verified(**_): return runner.verify_frozen_identity(require_clean_worktree=False)


def complete(plan):
    return MentorActionV2(action_type=plan.allowed_action_types[0],message=" ".join(plan.required_public_facts.values()),covered_point_ids=plan.required_public_point_ids,hint_id=(plan.allowed_hint_ids[0] if plan.allowed_hint_ids else None)).model_dump_json()


class MockTransport:
    scripts=[];instances=[]
    def __init__(self,key,budget,**kwargs):
        self.budget=budget;self.models_calls=0;self.chat_calls=0;self.index=0;self.raw_requests=[];self.__class__.instances.append(self)
    def discover_flash(self): self.models_calls+=1;return ("deepseek-v4-flash",)
    def complete(self,request):
        self.raw_requests.append(request);self.chat_calls+=1
        payload={"request":request.model_dump(mode="json")};self.budget.reserve(payload)
        scripted=self.scripts[self.index];self.index+=1
        if isinstance(scripted,Exception):
            self.budget.halt_unverified();raise scripted
        usage=ModelUsage(provider_model="deepseek-v4-flash",input_tokens=100,output_tokens=50,cache_hit_input_tokens=20,cache_miss_input_tokens=80,reasoning_tokens=0,latency_ms=10.0,estimated_cost=Decimal("0"),cost_currency="CNY",provider_request_id="ignored-provider-id")
        self.budget.settle(usage)
        return runner.V3TransportResponse(scripted,usage,{"id":"ignored-provider-id","content":scripted})
    def close(self): pass


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    MockTransport.instances=[];MockTransport.scripts=[]
    monkeypatch.setattr(runner,"dotenv_values",lambda *a,**k:{"DEEPSEEK_API_KEY":"placeholder"})


def run(tmp_path,scripts):
    MockTransport.scripts=list(scripts)
    code=runner.run_v3(output=tmp_path,budget=Decimal("0.05"),transport_factory=MockTransport,identity_verifier=verified)
    return code,json.loads((tmp_path/"sanitized_result.json").read_text(encoding="utf-8")),MockTransport.instances[-1]


def plans(): return verified()["plans"]


def test_five_scenarios_first_pass_and_requests_are_v3_pure(tmp_path):
    ps=plans();code,result,transport=run(tmp_path,[complete(x) for x in ps])
    assert code==0 and result["base_chat_calls"]==5 and result["repair_chat_calls"]==0
    assert all(x["scenario_outcome"]=="model_passed_first" and not x["fallback_used"] for x in result["records"])
    for request,plan in zip(transport.raw_requests,ps):
        text=request.model_dump_json()
        assert "MentorActionV2" in text and plan.plan_id in text and "covered_point_ids" in text
        for forbidden in ("AgentAction","diagnose_case","submit_diagnosis","MCP工具","DOCTOR_SYSTEM_PROMPT"):
            assert forbidden not in text


def test_one_public_repair_succeeds_and_others_continue(tmp_path):
    ps=plans();bad=MentorActionV2(action_type=ps[0].allowed_action_types[0],message=ps[0].required_public_facts[ps[0].required_public_point_ids[0]],covered_point_ids=(ps[0].required_public_point_ids[0],),hint_id=ps[0].allowed_hint_ids[0]).model_dump_json()
    scripts=[bad,complete(ps[0]),*(complete(x) for x in ps[1:])]
    _,result,transport=run(tmp_path,scripts)
    assert result["repair_chat_calls"]==1 and result["total_chat_calls"]==6
    assert result["records"][0]["scenario_outcome"]=="model_passed_after_repair"
    assert "缺少point IDs" in transport.raw_requests[1].messages[-1].content


def test_quality_failure_uses_fallback_and_grant_is_observed(tmp_path):
    ps=plans();idx=3;p=ps[idx]
    bad=MentorActionV2(action_type=p.allowed_action_types[0],message=p.required_public_facts[p.required_public_point_ids[0]],covered_point_ids=(p.required_public_point_ids[0],)).model_dump_json()
    scripts=[complete(x) for x in ps[:idx]]+[bad,bad,complete(ps[4])]
    _,result,_=run(tmp_path,scripts)
    refusal=result["records"][3]
    assert refusal["scenario_outcome"]=="teaching_failed" and refusal["fallback_used"] and refusal["continue_allowed"]
    assert refusal["run_stop_reason"] is None
    assert result["records"][4]["scenario_outcome"]=="model_passed_first"


@pytest.mark.parametrize("unsafe",("精确门槛是23","正确答案是A","我已替你调查","{\"action_type\":\"AgentAction\"}","调用病例工具"))
def test_safety_failure_stops_without_fallback_and_marks_remaining_not_observed(tmp_path,unsafe):
    ps=plans();_,result,transport=run(tmp_path,[complete(ps[0]),unsafe])
    assert result["run_stop_reason"]=="safety_stop"
    failed=result["records"][1];assert failed["scenario_outcome"]=="safety_failed" and not failed["fallback_used"]
    assert all(x["scenario_outcome"]=="not_observed" for x in result["records"][2:])
    assert transport.chat_calls==2


@pytest.mark.parametrize("first,expected",(("not-json","contract_stop"),(json.dumps({"action_type":"speak"}),"contract_stop")))
def test_non_json_or_wrong_schema_repairs_once_then_contract_stops(tmp_path,first,expected):
    _,result,transport=run(tmp_path,[first,first])
    assert result["run_stop_reason"]==expected and transport.chat_calls==2


def test_unknown_point_repairs_then_contract_stops(tmp_path):
    p=plans()[0];bad=json.loads(complete(p));bad["covered_point_ids"].append("unknown_point")
    _,result,_=run(tmp_path,[json.dumps(bad),json.dumps(bad)])
    assert result["run_stop_reason"]=="contract_stop"


@pytest.mark.parametrize("error,reason",((MentorPilotTransportError("response_model_mismatch"),"provider_identity_stop"),(MentorPilotTransportError("chat_schema_or_usage_invalid"),"protocol_stop"),(MentorPilotTransportError("timeout"),"timeout_stop")))
def test_provider_identity_usage_and_timeout_stop(tmp_path,error,reason):
    _,result,transport=run(tmp_path,[error])
    assert result["run_stop_reason"]==reason and transport.chat_calls==1


def test_dry_run_summary_has_frozen_identity_without_prompt_or_secret():
    summary=runner.dry_run_summary();text=json.dumps(summary,ensure_ascii=False)
    assert summary["transport_calls"]==0 and len(summary["scenarios"])==5
    assert summary["model"]=="deepseek-v4-flash" and summary["budget_cny"]=="0.05"
    assert "API Key" not in text and "完整Prompt" not in text and "required_public_facts" not in text


def test_identity_failure_happens_before_transport(tmp_path):
    def reject(**_): raise ValueError("v3_frozen_identity_mismatch")
    with pytest.raises(ValueError,match="v3_frozen_identity_mismatch"):
        runner.run_v3(output=tmp_path,budget=Decimal("0.05"),transport_factory=MockTransport,identity_verifier=reject)
    assert not MockTransport.instances


def test_environment_budget_cannot_expand_frozen_limit(monkeypatch):
    monkeypatch.setenv("XUANYI_PILOT_MAX_COST_CNY","1.00")
    verified_data=verified()
    assert Decimal(verified_data["v3"]["config"]["budget_cny"])==Decimal("0.05")
    assert MentorPilotBudget(Decimal("0.05"),verified_data["pricing"]).limit==Decimal("0.05")


def test_insufficient_budget_guard_rejects_before_http_transport_call():
    verified_data=verified();guard=MentorPilotBudget(Decimal("0.05"),verified_data["pricing"])
    guard.confirmed_cost=Decimal("0.049999")
    payload={"large_public_request":"x"*1000}
    with pytest.raises(MentorPilotTransportError,match="budget_exceeded"):
        guard.reserve(payload)
    assert guard.active_reserve is None
