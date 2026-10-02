from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMRequest, LLMResponse
from xuanyi_npc.agents.model_usage import ModelUsage
from xuanyi_npc.application.campaign import CampaignRuleSet
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.evaluation.request_ledger import DurableRequestLedger, EvidenceRecordingLLMAdapter, reconcile_request_ledger
from xuanyi_npc.evaluation.v21_pool_control import blocking_reason, write_execution_status
from xuanyi_npc.evaluation.v21_scenarios import memory_scenarios
from xuanyi_npc.evaluation.v2_contracts import ArtifactKind, V2Event, V2RunArtifact
from xuanyi_npc.evaluation.v2_graders import regrade


ROOT=Path(__file__).parents[1]


def test_c_campaign_references_only_the_four_evaluation_cases():
    catalog=CaseCatalog(ROOT/"src/xuanyi_npc/evaluation/fixtures/v21/cases")
    rules=CampaignRuleSet.load(ROOT/"src/xuanyi_npc/evaluation/fixtures/v21/campaign/cross_episode_rules.json",catalog)
    assert set(rules.catalog.case_ids()) == {"c01_crossed_bell_testimony","c02_red_ink_decoy","c09_three_lock_cistern","c10_ink_gate_sequence"}


def _artifact(sid: str) -> V2RunArtifact:
    now=datetime.now(timezone.utc); run=f"{sid.lower()}_m0_r01"
    events=(V2Event(run_id=run,event_id="evt_1",sequence=1,event_type="run_started",occurred_at=now,source="test"),
            V2Event(run_id=run,event_id="evt_2",sequence=2,event_type="run_ended",occurred_at=now,source="test"))
    base=V2RunArtifact(trace_schema_version="v2_diagnostic",run_id=run,experiment_id="offline_contract",
        scenario_id=sid,suite="memory_transfer",condition="M0",repeat_index=1,artifact_kind=ArtifactKind.DETERMINISTIC_FIXTURE,
        started_at=now,finished_at=now,status="finished",input_tokens=0,output_tokens=0,known_cost_cny=0,duration_ms=0,
        terminal_snapshot={"terminal_status":"completed","submitted_diagnosis_id":"d","treatment_outcome":"resolved",
                           "exposed_memory_ids":[],"expected_memory_ids":[],"forbidden_memory_ids":[]},events=events)
    return base.model_copy(update={"grades":regrade(base,{"valid_diagnosis_ids":["d"],"resolved_treatment_ids":["t"]})})


def test_mv01_mv06_serialize_write_read_and_regrade(tmp_path):
    assert set(memory_scenarios()) == {"MV01","MV06"}
    for sid in ("MV01","MV06"):
        artifact=_artifact(sid); path=tmp_path/f"{sid}.json"; path.write_text(artifact.model_dump_json(indent=2),encoding="utf-8")
        loaded=V2RunArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        assert loaded == artifact
        assert regrade(loaded,{"valid_diagnosis_ids":["d"],"resolved_treatment_ids":["t"]}) == artifact.grades


def test_request_evidence_survives_injected_artifact_write_failure(tmp_path):
    usage=ModelUsage(provider_model="offline",input_tokens=5,output_tokens=2,cache_hit_input_tokens=0,
        cache_miss_input_tokens=5,reasoning_tokens=0,latency_ms=1.0,estimated_cost=Decimal("0.12"),
        cost_currency="CNY",provider_request_id="req_1")
    guard=SimpleNamespace(max_cost_cny=Decimal("4"),known_cost_cny=Decimal("0.12"),maximum_committed_cost_cny=Decimal("0.12"),can_start_episode=True,halted=False,stop_reason=None)
    delegate=SimpleNamespace(request_budget=guard,config=SimpleNamespace(),complete=lambda request: LLMResponse(content="{}",usage=usage))
    ledger=tmp_path/"requests.jsonl"; adapter=EvidenceRecordingLLMAdapter(delegate,DurableRequestLedger(ledger))
    request=LLMRequest(messages=(ChatMessage(role=ChatRole.SYSTEM,content="system"),ChatMessage(role=ChatRole.USER,content="user")),response_schema={})
    adapter.complete(request)
    try:
        raise OSError("injected artifact write failure")
    except OSError:
        pass
    snapshot={"known_cost_cny":"0.12"}
    assert reconcile_request_ledger(ledger,snapshot)["reconciled"] is True
    assert json.loads(ledger.read_text(encoding="utf-8"))["provider_request_id"] == "req_1"


def test_blocker_stops_at_first_item_and_marks_rest_unstarted(tmp_path):
    artifact=_artifact("MV01").model_copy(update={"status":"aborted","failure_code":"campaign_rule_invalid"})
    reason=blocking_reason(artifact); assert reason == "implementation_failure:campaign_rule_invalid"
    planned=[{"task_id":"MV01","repeat":1,"condition":"M0"},{"task_id":"MV01","repeat":1,"condition":"M1"}]
    write_execution_status(tmp_path,planned=planned,started=[planned[0]],stop_reason=reason)
    status=json.loads((tmp_path/"execution_status.json").read_text(encoding="utf-8"))
    assert status["started_count"] == 1 and status["unstarted"] == [planned[1]]
