import json
import re
import threading
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from xuanyi_npc.application.clinic_mentor import (
    ClinicMentorBudgetGuard,ClinicMentorMode,ClinicMentorRuntime,ClinicMentorRuntimeError,
)
from xuanyi_npc.application.mentor_communication import MentorActionV2
from xuanyi_npc.evaluation.episode import ModelUsage
from xuanyi_npc.evaluation.real_mentor_transport import load_mentor_pilot_pricing
from xuanyi_npc.clinic.server import ClinicHTTPServer, main as clinic_main
from tests.test_r5_clinic_http import request
from tests.test_r5_clinic_service import build_clinic

ROOT=Path(__file__).parents[1]
PRICING=load_mentor_pilot_pricing(ROOT/"src/xuanyi_npc/resources/pilot/deepseek_v4_flash_mentor_pricing_2026-08-13.json")

CONTEXTS={
"initial_lesson_hint_1":{"mentor_role":"玄医先生是导师，玩家是需要亲自行动的弟子","lesson":{"title":"证据齐备再定证","goal":"区分事实、推断与诱饵，并只依据已发现证据判断","case_title":"旧纸伞"},"player_request":"请给我一次提示，但不要告诉我诊断或处置答案。","allowed_hint_cards":[{"hint_id":"hint_1","text":"请检查当前仍未覆盖的公开调查类别；先补足事实，不急于定性。"}]},
"wrong_diagnosis_remediation_1":{"case_title":"旧纸伞","submitted_result":"玩家提交了合法但错误的诊断；辨证能力没有因此增加","public_improvement_area":"reason_diagnosis","deterministic_curriculum_decision":{"remediation_id":"remediate_diagnostic_reasoning_v1","title":"辨证改进补课","effect":"补课本身不直接增加能力"}},
"exam_failure_explanation_1":{"exam_result":{"passed":False,"total_score":55,"critical_failure":False,"improvement_areas":["reason_diagnosis"],"required_remediation_ids":["remediate_diagnostic_reasoning_v1"]},"deterministic_decision":"考试失败；补课完成前不能重考；分数与通过状态不可由导师修改"},
"inheritance_refusal_1":{"same_player_state":"before_requirements_met","deterministic_decision":"refused","public_reason_categories":["考试尚未通过","能力证明不足","师承认可不足"],"instruction":"只解释公开类别，不披露精确数值门槛；语言说明不构成权限"},
"inheritance_grant_1":{"same_player_state":"after_requirements_met","deterministic_decision":"granted_once","public_grant":{"inheritance_title":"溯契还因","permission_level":"inheritance","duplicate_grant":False},"instruction":"解释规则层已经授予；导师语言不创建或重复写入权限"}}


def usage():return ModelUsage(provider_model="deepseek-v4-flash",input_tokens=100,output_tokens=50,cache_hit_input_tokens=20,cache_miss_input_tokens=80,reasoning_tokens=0,latency_ms=5.0,estimated_cost=Decimal("0"),cost_currency="CNY",provider_request_id="local-only")

class Response:
    def __init__(self,content):self.content=content;self.usage=usage();self.raw_response={"ignored":"raw"}

class MockTransport:
    def __init__(self,root,scripts,budget=Decimal("0.05")):
        self.budget=ClinicMentorBudgetGuard(budget,PRICING);self.scripts=list(scripts);self.calls=[]
    def complete(self,request):
        self.calls.append(request);payload={"request":request.model_dump(mode="json")};self.budget.reserve(payload)
        value=self.scripts.pop(0)
        if isinstance(value,Exception):self.budget.halt_unverified();raise value
        self.budget.settle(usage());return Response(value)

def complete(runtime,request_id):
    plan=runtime.planner.build(request_id,CONTEXTS[request_id])
    return MentorActionV2(action_type=plan.allowed_action_types[0],message=" ".join(plan.required_public_facts.values()),covered_point_ids=plan.required_public_point_ids,hint_id=(plan.allowed_hint_ids[0] if plan.allowed_hint_ids else None)).model_dump_json()

def snapshot_state(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*.json") if p.name not in {"clinic_mentor_budget.json"}}

def test_off_and_fake_never_initialize_or_call_transport(tmp_path):
    off=ClinicMentorRuntime(ClinicMentorMode.OFF,tmp_path/"off")
    fake=ClinicMentorRuntime(ClinicMentorMode.FAKE,tmp_path/"fake")
    assert off.transport is fake.transport is None
    assert off.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]).fallback_used
    assert fake.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]).fallback_used

def test_five_deepseek_interactions_use_plans_v2_actions_and_cover_5_points(tmp_path):
    runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,MockTransport(tmp_path,[]))
    runtime.transport.scripts=[complete(runtime,x) for x in CONTEXTS]
    for request_id,context in CONTEXTS.items():
        result=runtime.express(request_id,context)
        assert result.model_passed and not result.fallback_used and result.covered_point_count==result.required_point_count==5
    assert len(runtime.transport.calls)==5
    assert all("MentorActionV2" in x.model_dump_json() and "AgentAction" not in x.model_dump_json() for x in runtime.transport.calls)

def test_fake_and_mock_real_change_only_expression_and_metrics(tmp_path):
    fake=build_clinic(tmp_path/"fake");player=fake.create_player("同态弟子").player_summary.player_id
    before=snapshot_state(tmp_path/"fake");fake_result=ClinicMentorRuntime(ClinicMentorMode.FAKE,tmp_path/"fake").express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]);after=snapshot_state(tmp_path/"fake")
    assert before==after
    real_root=tmp_path/"real";real=build_clinic(real_root);real_player=real.create_player("同态弟子").player_summary.player_id
    transport=MockTransport(real_root,[]);runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,real_root,transport);transport.scripts=[complete(runtime,"initial_lesson_hint_1")]
    before=snapshot_state(real_root);result=runtime.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]);after=snapshot_state(real_root)
    assert before==after and result.model_passed and fake_result.message!=result.message

def test_one_repair_has_one_extra_call_and_no_game_event(tmp_path):
    transport=MockTransport(tmp_path,[]);runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport);p=runtime.planner.build("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"])
    bad=MentorActionV2(action_type=p.allowed_action_types[0],message=p.required_public_facts[p.required_public_point_ids[0]],covered_point_ids=(p.required_public_point_ids[0],),hint_id="hint_1").model_dump_json();transport.scripts=[bad,complete(runtime,"initial_lesson_hint_1")]
    result=runtime.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"])
    assert result.model_passed and result.attempts==2 and len(transport.calls)==2 and runtime.budget_state.repair_count==1

def test_quality_failure_fallback_does_not_freeze_next_request(tmp_path):
    transport=MockTransport(tmp_path,[]);runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport);p=runtime.planner.build("inheritance_refusal_1",CONTEXTS["inheritance_refusal_1"])
    bad=MentorActionV2(action_type=p.allowed_action_types[0],message="暂不授予",covered_point_ids=(p.required_public_point_ids[0],)).model_dump_json();transport.scripts=[bad,bad,complete(runtime,"inheritance_grant_1")]
    failed=runtime.express("inheritance_refusal_1",CONTEXTS["inheritance_refusal_1"]);granted=runtime.express("inheritance_grant_1",CONTEXTS["inheritance_grant_1"])
    assert failed.fallback_used and not failed.model_passed and not runtime.budget_state.frozen and granted.model_passed

@pytest.mark.parametrize("unsafe",("精确门槛是23","正确答案是A","我已替你调查","AgentAction","调用病例工具"))
def test_safety_freezes_then_future_requests_use_fallback_without_network(tmp_path,unsafe):
    transport=MockTransport(tmp_path,[unsafe]);runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport)
    first=runtime.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]);calls=len(transport.calls)
    second=runtime.express("exam_failure_explanation_1",CONTEXTS["exam_failure_explanation_1"])
    assert first.stop_category=="safety_stop" and first.fallback_used and runtime.budget_state.frozen
    assert second.fallback_used and second.notice and len(transport.calls)==calls

@pytest.mark.parametrize("error,reason",((ClinicMentorRuntimeError("chat_schema_or_usage_invalid"),"protocol_stop"),(ClinicMentorRuntimeError("timeout"),"timeout_stop"),(ClinicMentorRuntimeError("response_model_mismatch"),"provider_identity_stop"),(ClinicMentorRuntimeError("budget_exceeded"),"budget_stop")))
def test_provider_and_budget_failures_freeze(error,reason,tmp_path):
    runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,MockTransport(tmp_path,[error]))
    result=runtime.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"])
    assert result.stop_category==reason and runtime.budget_state.frozen

def test_budget_persists_across_process_runtime_and_is_shared_but_contexts_isolated(tmp_path):
    transport=MockTransport(tmp_path,[]);first=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport);transport.scripts=[complete(first,"initial_lesson_hint_1")]
    first.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]);cost=first.budget_state.confirmed_cost;run_id=first.budget_state.run_id
    second_transport=MockTransport(tmp_path,[]);second=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,second_transport)
    assert second.budget_state.confirmed_cost==cost and second.budget_state.run_id==run_id
    assert second.status["remaining_budget"]==str(Decimal("0.05")-cost)

def test_logs_are_sanitized_and_do_not_store_prompt_response_or_provider_id(tmp_path):
    transport=MockTransport(tmp_path,[]);runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport);transport.scripts=[complete(runtime,"initial_lesson_hint_1")]
    runtime.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"]);text=runtime.metrics_path.read_text(encoding="utf-8")
    for forbidden in ("provider_request_id","local-only","required_public_facts","DEEPSEEK_API_KEY","弟子，为师"):
        assert forbidden not in text


def test_two_players_share_budget_but_context_is_never_crossed(tmp_path):
    clinic=build_clinic(tmp_path);a=clinic.create_player("甲").player_summary.player_id;b=clinic.create_player("乙").player_summary.player_id
    transport=MockTransport(tmp_path,[]);runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport);clinic.mentor_runtime=runtime
    transport.scripts=[complete(runtime,"initial_lesson_hint_1"),complete(runtime,"initial_lesson_hint_1")]
    clinic.mentor_expression(a,"initial_lesson_hint_1");clinic.mentor_expression(b,"initial_lesson_hint_1")
    assert runtime.budget_state.request_count==2
    assert clinic.store.load_player(a).display_name=="甲" and clinic.store.load_player(b).display_name=="乙"
    for request in transport.calls:
        text=request.model_dump_json()
        assert '"甲"' not in text and '"乙"' not in text


def test_fake_and_off_import_path_does_not_load_paid_transport(tmp_path,monkeypatch):
    import subprocess,sys
    code="import sys;from xuanyi_npc.application.clinic_mentor import ClinicMentorRuntime,ClinicMentorMode;from pathlib import Path;ClinicMentorRuntime(ClinicMentorMode.FAKE,Path(r'"+str(tmp_path).replace('\\','\\\\')+"'));print('xuanyi_npc.evaluation.real_mentor_transport' in sys.modules)"
    assert subprocess.check_output([sys.executable,"-c",code],text=True).strip()=="False"


@pytest.mark.parametrize("argv",(
    ["--mentor-mode","deepseek","--budget-cny","0.05","--dry-run"],
    ["--mentor-mode","deepseek","--budget-cny","0","--dry-run"],
    ["--mentor-mode","deepseek","--budget-cny","0.051","--dry-run"],
))
def test_dry_run_and_invalid_budgets_never_import_paid_transport(argv):
    import sys
    sys.modules.pop("xuanyi_npc.evaluation.real_mentor_transport",None)
    expected=0 if argv[3]=="0.05" else 2
    assert clinic_main(argv)==expected
    assert "xuanyi_npc.evaluation.real_mentor_transport" not in sys.modules


def test_mock_real_expression_is_rendered_over_http_with_public_status(tmp_path):
    service=build_clinic(tmp_path);transport=MockTransport(tmp_path,[])
    runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport);service.mentor_runtime=runtime
    transport.scripts=[complete(runtime,"initial_lesson_hint_1")]
    server=ClinicHTTPServer(("127.0.0.1",0),service);thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        port=server.server_address[1];_,_,start=request(port,"GET","/")
        token=re.search(r'name="operation_id" value="([^"]+)',start).group(1)
        _,headers,_=request(port,"POST","/players",{"display_name":"表达弟子","operation_id":token})
        _,_,home=request(port,"GET",headers["Location"])
        assert "真实DeepSeek" in home and "已用费用" in home and "covered_point_ids" not in home
        _,_,teaching=request(port,"GET",headers["Location"].replace("/clinic","/teaching"))
        token=re.search(r'action="/mentor/explain".*?name="operation_id" value="([^"]+)',teaching).group(1)
        _,headers,_=request(port,"POST","/mentor/explain",{"player_id":service.list_players()[0].player_id,"request_id":"initial_lesson_hint_1","operation_id":token})
        _,_,page=request(port,"GET",headers["Location"])
        assert "导师说明" in page and "证据" in page and len(transport.calls)==1
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
