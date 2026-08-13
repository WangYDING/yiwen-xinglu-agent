"""Execution assembly for the frozen R6 real mentor Pilot v3."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from dotenv import dotenv_values
from pydantic import SecretStr

from xuanyi_npc.application.mentor_communication import (
    MentorActionV2, MentorCommunicationPlanner, PilotStopCategory,
    build_communication_request, deterministic_fallback, evaluate_mentor_action_v2,
    classify_transport_failure,
)
from xuanyi_npc.resources.runtime import read_runtime_text

from .real_mentor_runner import canonical_hash
from .real_mentor_transport import (
    AUTHORIZED_BUDGET_CNY, MODEL_ID, MentorPilotBudget, MentorPilotTransportError,
    RealMentorDeepSeekTransport, load_mentor_pilot_pricing,
)


V3_RESOURCE="acceptance/r6_real_mentor_pilot_v3.json"
V3_INPUT_RESOURCE="acceptance/r6_real_mentor_pilot_v3_inputs.json"
V3_EXPECTATION_RESOURCE="acceptance/r6_real_mentor_pilot_v3_expectations.json"
PRICING_RESOURCE="pilot/deepseek_v4_flash_mentor_pricing_2026-08-13.json"
V3_BLOB="e090cf36528858f1d37b7fdc2eea68b3acd03547"


def _load():
    return json.loads(read_runtime_text(V3_INPUT_RESOURCE)),json.loads(read_runtime_text(V3_EXPECTATION_RESOURCE)),json.loads(read_runtime_text(V3_RESOURCE))


def frozen_components():
    snapshot,expectation_snapshot,v3=_load(); planner=MentorCommunicationPlanner()
    inputs=snapshot["requests"]
    plans=[planner.build(x["request_id"],x["public_context"]) for x in inputs]
    config={"config":v3["config"],"stop_policy":v3["stop_policy"],"admission":v3["admission"]}
    prompts=[build_communication_request(plan).model_dump(mode="json") for plan in plans]
    return snapshot,expectation_snapshot,v3,inputs,plans,config,prompts


def verify_frozen_identity(*, require_clean_worktree: bool) -> dict[str,Any]:
    snapshot,expectation_snapshot,v3,inputs,plans,config,prompts=frozen_components()
    source=Path(__file__).parents[1]/"application/mentor_communication.py"
    hashes={
      "inputs_sha256":canonical_hash(inputs),"expectations_sha256":canonical_hash(expectation_snapshot["expectations"]),"config_sha256":canonical_hash(config),
      "communication_plans_sha256":canonical_hash([x.model_dump(mode="json") for x in plans]),"prompt_sha256":canonical_hash(prompts),
      "mentor_action_schema_sha256":canonical_hash(MentorActionV2.model_json_schema()),"evaluator_source_sha256":hashlib.sha256(source.read_bytes()).hexdigest()}
    if hashes != v3["frozen_hashes"]: raise ValueError("v3_frozen_identity_mismatch")
    manifest_path=Path(__file__).parents[1]/"resources/acceptance/r6_real_mentor_pilot_v3.json"
    blob=subprocess.check_output(["git","hash-object",str(manifest_path)],text=True).strip()
    if blob != V3_BLOB: raise ValueError("v3_manifest_blob_mismatch")
    if len(plans)!=5 or v3["config"]["base_request_limit"]!=5: raise ValueError("v3_request_count_mismatch")
    if v3["config"]["model"]!=MODEL_ID or v3["config"]["thinking"]!="disabled" or Decimal(v3["config"]["budget_cny"])!=AUTHORIZED_BUDGET_CNY: raise ValueError("v3_provider_config_mismatch")
    pricing=load_mentor_pilot_pricing(Path(__file__).parents[1]/"resources"/PRICING_RESOURCE)
    if pricing.snapshot_id != v3["config"]["pricing_snapshot_id"]: raise ValueError("v3_pricing_mismatch")
    if require_clean_worktree and subprocess.check_output(["git","status","--porcelain=v1"],text=True).strip(): raise ValueError("worktree_not_clean")
    return {"v3":v3,"plans":plans,"hashes":hashes,"pricing":pricing}


def dry_run_summary() -> dict[str,Any]:
    verified=verify_frozen_identity(require_clean_worktree=False); v3=verified["v3"]
    return {"pilot_id":v3["pilot_id"],"status":"dry_run_no_network","model":v3["config"]["model"],"thinking":v3["config"]["thinking"],"budget_cny":v3["config"]["budget_cny"],"pricing_snapshot_id":v3["config"]["pricing_snapshot_id"],"scenarios":[{"request_id":x.plan_id,"communication_plan_id":x.plan_id,"required_point_count":len(x.required_public_point_ids)} for x in verified["plans"]],"prompt_sha256":verified["hashes"]["prompt_sha256"],"schema_sha256":verified["hashes"]["mentor_action_schema_sha256"],"evaluator_sha256":verified["hashes"]["evaluator_source_sha256"],"stop_policy":v3["stop_policy"],"maximum_base_requests":5,"maximum_repair_requests":5,"transport_calls":0}


@dataclass(frozen=True)
class V3TransportResponse:
    content: str
    usage: Any
    raw_response: dict[str,Any]


def _usage_dict(usage,cost):
    return {"model":usage.provider_model,"input_tokens":usage.input_tokens,"output_tokens":usage.output_tokens,"cache_hit_input_tokens":usage.cache_hit_input_tokens,"cache_miss_input_tokens":usage.cache_miss_input_tokens,"latency_ms":round(usage.latency_ms,3),"cost_cny":str(cost)}


def _safety_failure(evaluation) -> bool:
    return not evaluation.safe


def _raw_safety_violation(content: str) -> bool:
    lowered=content.lower()
    return any(term.lower() in lowered for term in ("AgentAction","diagnose_case","submit_diagnosis","execute_treatment","病例工具","MCP工具","MENTOR_SECRET","精确门槛","正确答案","标准答案","我已替你调查","我替你诊断","我替你处置","我绕过规则","我自行授予"))


def run_v3(*,output:Path,budget:Decimal,transport_factory:Callable=RealMentorDeepSeekTransport,identity_verifier:Callable[...,dict[str,Any]]=verify_frozen_identity) -> int:
    if budget!=AUTHORIZED_BUDGET_CNY: return 2
    verified=identity_verifier(require_clean_worktree=True);v3=verified["v3"];plans=verified["plans"]
    key=(dotenv_values(Path.cwd()/".env",encoding="utf-8",interpolate=False).get("DEEPSEEK_API_KEY") or "").strip()
    if not key: return 2
    output.mkdir(parents=True,exist_ok=True);guard=MentorPilotBudget(budget,verified["pricing"]);transport=transport_factory(SecretStr(key),guard,timeout_seconds=v3["config"]["timeout_seconds"])
    records=[];raw_records=[];run_stop_reason=None;repair_calls=0
    try:
        transport.discover_flash()
        for plan in plans:
            attempts=0;final_action=None;final_eval=None;response=None;parse_failure=False
            missing=()
            while attempts<2:
                attempts+=1
                try:
                    response=transport.complete(build_communication_request(plan,repair_missing=missing))
                    if _raw_safety_violation(response.content):
                        run_stop_reason=PilotStopCategory.SAFETY.value;break
                    action=MentorActionV2.model_validate_json(response.content)
                except MentorPilotTransportError as exc:
                    run_stop_reason=classify_transport_failure(exc.code).value;break
                except Exception:
                    parse_failure=True
                    missing=plan.required_public_point_ids
                    if attempts==1: repair_calls+=1;continue
                    run_stop_reason=PilotStopCategory.CONTRACT.value;break
                if run_stop_reason: break
                evaluation=evaluate_mentor_action_v2(plan,action);final_action=action;final_eval=evaluation
                if _safety_failure(evaluation): run_stop_reason=PilotStopCategory.SAFETY.value;break
                contract_invalid=(bool(evaluation.unknown_point_ids) or action.action_type not in plan.allowed_action_types or (action.hint_id is not None and action.hint_id not in plan.allowed_hint_ids))
                if contract_invalid:
                    missing=plan.required_public_point_ids
                    if attempts==1: repair_calls+=1;continue
                    run_stop_reason=PilotStopCategory.CONTRACT.value;break
                if evaluation.complete: break
                missing=tuple(dict.fromkeys((*evaluation.missing_point_ids,*evaluation.unsupported_claimed_point_ids,*evaluation.contradicted_point_ids)))
                if attempts==1: repair_calls+=1;continue
                break
            if run_stop_reason:
                records.append({"request_id":plan.plan_id,"scenario_outcome":"safety_failed" if run_stop_reason=="safety_stop" else "stopped","fallback_used":False,"continue_allowed":False,"run_stop_reason":run_stop_reason,"attempts":attempts});break
            cost=guard.confirmed_cost-sum((Decimal(x["usage"]["cost_cny"]) for x in records if x.get("usage")),Decimal("0"))
            if final_eval is not None and final_eval.complete:
                outcome="model_passed_first" if attempts==1 else "model_passed_after_repair";fallback=False;delivered=final_action
            else:
                outcome="teaching_failed";fallback=True;delivered=deterministic_fallback(plan)
            records.append({"request_id":plan.plan_id,"scenario_outcome":outcome,"fallback_used":fallback,"continue_allowed":True,"run_stop_reason":None,"attempts":attempts,"covered_point_ids":list(final_action.covered_point_ids) if final_action else [],"required_point_ids":list(plan.required_public_point_ids),"structured_coverage_valid":bool(final_eval and final_eval.structured_coverage_valid),"text_consistent":bool(final_eval and final_eval.text_consistent),"safe":bool(final_eval and final_eval.safe),"delivered_action":delivered.model_dump(mode="json"),"usage":_usage_dict(response.usage,cost)})
            raw_records.append({"request_id":plan.plan_id,"response":response.raw_response})
    except MentorPilotTransportError as exc: run_stop_reason=classify_transport_failure(exc.code).value
    finally: transport.close()
    seen={x["request_id"] for x in records}
    for plan in plans:
        if plan.plan_id not in seen: records.append({"request_id":plan.plan_id,"scenario_outcome":"not_observed","fallback_used":False,"continue_allowed":False,"run_stop_reason":run_stop_reason})
    raw={"pilot_id":v3["pilot_id"],"responses":raw_records};raw_path=output/"raw_result.json";raw_path.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding="utf-8");raw_sha=hashlib.sha256(raw_path.read_bytes()).hexdigest()
    result={"pilot_id":v3["pilot_id"],"model":MODEL_ID,"thinking":"disabled","models_calls":transport.models_calls,"base_chat_calls":sum(1 for x in records if x["scenario_outcome"]!="not_observed"),"repair_chat_calls":repair_calls,"total_chat_calls":transport.chat_calls,"authorized_budget_cny":"0.05","effective_budget_cny":str(guard.limit),"confirmed_cost_cny":str(guard.confirmed_cost),"unverified_reserve_cny":str(guard.unverified_reserve),"maximum_committed_cost_cny":str(guard.maximum_committed_cost),"run_stop_reason":run_stop_reason,"records":records,"raw_result_sha256":raw_sha,"boundaries":{"bge_calls":0,"embedding_calls":0,"human_contacts":0,"remote_operations":0}}
    (output/"sanitized_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":"completed" if run_stop_reason is None else "stopped","run_stop_reason":run_stop_reason,"models_calls":transport.models_calls,"chat_calls":transport.chat_calls,"cost_cny":str(guard.confirmed_cost),"raw_sha256":raw_sha},ensure_ascii=False))
    return 0 if run_stop_reason is None else 4
