import hashlib
import json
from pathlib import Path

from xuanyi_npc.evaluation.real_mentor_runner import canonical_hash


ROOT=Path(__file__).parents[1]
PATH=ROOT/"src/xuanyi_npc/resources/acceptance/r6_real_mentor_pilot_v2.json"


def load(): return json.loads(PATH.read_text(encoding="utf-8"))


def components(data):
    inputs=[{"scenario_id":x["scenario_id"],"request_id":x["request_id"],"public_context":x["public_context"],"allowed_action_types":x["allowed_action_types"],"allowed_hint_ids":x["allowed_hint_ids"]} for x in data["requests"]]
    expectations=[{"request_id":x["request_id"],"expectation":x["expectation"]} for x in data["requests"]]
    config={"config":data["config"],"admission":data["admission"],"stop_conditions":data["stop_conditions"]}
    return inputs,expectations,config


def test_v2_exact_identity_counts_and_hashes():
    data=load(); inputs,expected,config=components(data)
    assert data["pilot_id"]=="r6_real_mentor_pilot_v2"
    assert data["config"]["model"]=="deepseek-v4-flash"
    assert data["config"]["thinking"]=="disabled"
    assert data["config"]["budget_cny"]=="0.05"
    assert data["config"]["base_request_limit"]==len(data["requests"])==5
    assert [x["scenario_id"] for x in data["requests"]].count("inheritance_refusal_and_grant")==2
    assert data["frozen_hashes"]=={"inputs_sha256":canonical_hash(inputs),"expectations_sha256":canonical_hash(expected),"config_sha256":canonical_hash(config)}


def test_v1_is_preserved_and_product_acceptance_blob_is_unchanged():
    assert (ROOT/"src/xuanyi_npc/resources/acceptance/real_mentor_pilot_v1.json").exists()
    payload=(ROOT/"src/xuanyi_npc/resources/acceptance/product_acceptance_v1.json").read_bytes()
    git_blob=hashlib.sha1(f"blob {len(payload)}\0".encode()+payload).hexdigest()
    assert git_blob=="1206429ae097a0a091da871b57e9a3ad43fb3269"
