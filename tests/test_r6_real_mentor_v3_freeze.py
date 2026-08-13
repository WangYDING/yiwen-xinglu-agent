import hashlib,json
from pathlib import Path

from xuanyi_npc.agents.mentor import MENTOR_SYSTEM_PROMPT
from xuanyi_npc.application.mentor_communication import MentorActionV2,MentorCommunicationPlanner,build_communication_request
from xuanyi_npc.evaluation.real_mentor_runner import canonical_hash

ROOT=Path(__file__).parents[1]
V2P=ROOT/"src/xuanyi_npc/resources/acceptance/r6_real_mentor_pilot_v2.json"
V3P=ROOT/"src/xuanyi_npc/resources/acceptance/r6_real_mentor_pilot_v3.json"
SOURCE=ROOT/"src/xuanyi_npc/application/mentor_communication.py"

def components():
    v2=json.loads(V2P.read_text(encoding="utf-8")); v3=json.loads(V3P.read_text(encoding="utf-8")); planner=MentorCommunicationPlanner()
    inputs=[{"scenario_id":x["scenario_id"],"request_id":x["request_id"],"public_context":x["public_context"],"allowed_action_types":x["allowed_action_types"],"allowed_hint_ids":x["allowed_hint_ids"]} for x in v2["requests"]]
    expected=[{"request_id":x["request_id"],"expectation":x["expectation"]} for x in v2["requests"]]
    plans=[planner.build(x["request_id"],x["public_context"]).model_dump(mode="json") for x in v2["requests"]]
    config={"config":v3["config"],"stop_policy":v3["stop_policy"],"admission":v3["admission"]}
    prompt=[build_communication_request(planner.build(x["request_id"],x["public_context"])).model_dump(mode="json") for x in v2["requests"]]
    schema=MentorActionV2.model_json_schema()
    return v2,v3,inputs,expected,plans,config,prompt,schema

def test_v3_identity_policy_and_all_hashes_are_frozen():
    v2,v3,inputs,expected,plans,config,prompt,schema=components()
    assert v3["status"]=="pre_frozen_not_authorized_not_run"
    assert v3["config"]["model"]=="deepseek-v4-flash" and v3["config"]["budget_cny"]=="0.05"
    assert len(v3["request_sources"])==5 and all(x["authoritative_state"]=="same_as_v2" for x in v3["request_sources"])
    assert v3["stop_policy"]["continue_after"]==["teaching_quality_stop"]
    assert v3["frozen_hashes"]=={
      "inputs_sha256":canonical_hash(inputs),"expectations_sha256":canonical_hash(expected),"config_sha256":canonical_hash(config),
      "communication_plans_sha256":canonical_hash(plans),"prompt_sha256":canonical_hash(prompt),"mentor_action_schema_sha256":canonical_hash(schema),
      "evaluator_source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest()}

def test_v2_and_product_acceptance_blobs_remain_unchanged():
    import subprocess
    assert subprocess.check_output(["git","hash-object",str(V2P)],text=True).strip()=="3974f6f954a87ccd00ecf1a4e8cde7c8e75c3b11"
    product=ROOT/"src/xuanyi_npc/resources/acceptance/product_acceptance_v1.json"
    assert subprocess.check_output(["git","hash-object",str(product)],text=True).strip()=="1206429ae097a0a091da871b57e9a3ad43fb3269"
