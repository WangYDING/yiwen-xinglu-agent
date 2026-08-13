import json
from copy import deepcopy
from pathlib import Path

import pytest

from xuanyi_npc.application.mentor_communication import (
    MentorActionV2, MentorCommunicationPlanner, PilotStopCategory,
    build_communication_request, deterministic_fallback, evaluate_mentor_action_v2,
    run_offline_communication, should_stop,
)
from xuanyi_npc.domain.mentor import MentorAction


ROOT=Path(__file__).parents[1]
V2=json.loads((ROOT/"src/xuanyi_npc/resources/acceptance/r6_real_mentor_pilot_v2.json").read_text(encoding="utf-8"))
ITEMS={x["request_id"]:x for x in V2["requests"]}
PLANNER=MentorCommunicationPlanner()


def plan(request_id): return PLANNER.build(request_id,deepcopy(ITEMS[request_id]["public_context"]))
def complete_action(p):
    return MentorActionV2(action_type=p.allowed_action_types[0],message=" ".join(p.required_public_facts.values()),covered_point_ids=p.required_public_point_ids,hint_id=(p.allowed_hint_ids[0] if p.allowed_hint_ids else None))


@pytest.mark.parametrize("request_id",tuple(ITEMS))
def test_five_plans_are_deterministic_complete_public_and_first_mock_passes(request_id):
    first=plan(request_id); second=plan(request_id)
    assert first == second
    assert set(first.required_public_point_ids)==set(first.required_public_facts)
    assert all("MENTOR_SECRET" not in value for value in first.required_public_facts.values())
    outcome=run_offline_communication(first,(complete_action(first).model_dump_json(),))
    assert outcome.model_passed and not outcome.fallback_used and outcome.evaluation.complete


def test_missing_one_or_many_points_repairs_once_then_falls_back():
    p=plan("wrong_diagnosis_remediation_1")
    one=complete_action(p).model_copy(update={"covered_point_ids":p.required_public_point_ids[:-1],"message":" ".join(list(p.required_public_facts.values())[:-1])})
    many=complete_action(p).model_copy(update={"covered_point_ids":p.required_public_point_ids[:1],"message":p.required_public_facts[p.required_public_point_ids[0]]})
    fixed=complete_action(p)
    assert run_offline_communication(p,(one.model_dump_json(),fixed.model_dump_json())).model_passed
    failed=run_offline_communication(p,(one.model_dump_json(),many.model_dump_json()))
    assert not failed.model_passed and failed.fallback_used and failed.stop_category is PilotStopCategory.TEACHING_QUALITY
    assert evaluate_mentor_action_v2(p,failed.delivered_action).complete


def test_unknown_point_is_rejected_by_versioned_schema_and_evaluator():
    p=plan("exam_failure_explanation_1")
    action=complete_action(p).model_copy(update={"covered_point_ids":(*p.required_public_point_ids,"unknown_point")})
    evaluation=evaluate_mentor_action_v2(p,action)
    assert evaluation.unknown_point_ids==("unknown_point",) and not evaluation.complete
    schema=json.dumps(build_communication_request(p).response_schema,ensure_ascii=False)
    assert "unknown_point" not in schema


def test_claimed_coverage_with_contradictory_or_empty_text_fails_consistency():
    p=plan("inheritance_refusal_1")
    action=complete_action(p).model_copy(update={"message":"当前暂不授予传承。"})
    result=evaluate_mentor_action_v2(p,action)
    assert result.unsupported_claimed_point_ids and not result.text_consistent


@pytest.mark.parametrize("message",("精确门槛是23。","我已替你调查并完成处置。"))
def test_hidden_leak_or_player_takeover_is_safety_stop(message):
    p=plan("inheritance_refusal_1") if "门槛" in message else plan("initial_lesson_hint_1")
    action=complete_action(p).model_copy(update={"message":message})
    outcome=run_offline_communication(p,(action.model_dump_json(),))
    assert outcome.stop_category is PilotStopCategory.SAFETY
    assert should_stop(outcome.stop_category,continue_on_teaching_quality=True)


def test_quality_failure_continues_and_grant_can_still_be_observed():
    outcomes=[]
    for request_id in ITEMS:
        p=plan(request_id)
        output=(MentorActionV2(action_type=p.allowed_action_types[0],message="不完整说明",covered_point_ids=(p.required_public_point_ids[0],),hint_id=(p.allowed_hint_ids[0] if p.allowed_hint_ids else None)) if request_id=="inheritance_refusal_1" else complete_action(p))
        result=run_offline_communication(p,(output.model_dump_json(),output.model_dump_json()))
        outcomes.append((request_id,result))
        if result.stop_category and should_stop(result.stop_category,continue_on_teaching_quality=True): break
    assert outcomes[-1][0]=="inheritance_grant_1" and outcomes[-1][1].model_passed
    assert any(x.stop_category is PilotStopCategory.TEACHING_QUALITY for _,x in outcomes)


def test_fallback_is_complete_and_does_not_mutate_authoritative_input():
    before=deepcopy(ITEMS["exam_failure_explanation_1"]["public_context"]); p=plan("exam_failure_explanation_1")
    fallback=deterministic_fallback(p)
    assert fallback.message.startswith("【确定性降级说明】")
    assert evaluate_mentor_action_v2(p,fallback).complete
    assert ITEMS["exam_failure_explanation_1"]["public_context"]==before


def test_historical_mentor_action_schema_remains_unchanged():
    fields=set(MentorAction.model_fields)
    assert "covered_point_ids" not in fields
    assert set(MentorActionV2.model_fields)=={"action_type","message","covered_point_ids","hint_id"}


def test_doctor_agent_implementation_is_byte_identical_to_v2_result_head():
    payload=(ROOT/"src/xuanyi_npc/agents/doctor.py").read_bytes()
    import hashlib
    blob=hashlib.sha1(f"blob {len(payload)}\0".encode()+payload).hexdigest()
    assert blob=="37a78eb7fd870bfe81eeb584e17f0832dee28e90"


def test_request_contains_plan_and_only_public_missing_ids_on_repair():
    p=plan("wrong_diagnosis_remediation_1")
    req=build_communication_request(p,repair_missing=("future_case_performance_proves_improvement",))
    assert "required_public_facts" in req.messages[1].content
    assert "future_case_performance_proves_improvement" in req.messages[-1].content
    assert "正确诊断" not in req.messages[-1].content
