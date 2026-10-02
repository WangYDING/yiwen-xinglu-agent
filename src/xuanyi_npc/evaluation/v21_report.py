"""Offline four-dimension report for completed V2.1 slim artifacts."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean

from xuanyi_npc.evaluation.v2_contracts import GradeStatus, V2RunArtifact
from xuanyi_npc.evaluation.v2_graders import strict_success


def _artifacts(root: Path) -> list[V2RunArtifact]:
    return [V2RunArtifact.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(root.glob("**/runs/*/artifact.json"))]


def _event_turn(item: V2RunArtifact, event_type: str, tool: str | None = None):
    values=[]
    for event in item.events:
        if event.event_type != event_type: continue
        value=event.data.get("selected_tool") if event_type == "proposal_finalized" else event.data.get("tool")
        if tool is None or value == tool: values.append(event.turn)
    return min((value for value in values if value is not None), default=None)


def _row(item: V2RunArtifact) -> dict:
    grades={grade.grader_id:grade.status for grade in item.grades}
    model_events=[event for event in item.events if event.event_type == "model_request_finished"]
    return {
        "run_id":item.run_id,"task_id":item.scenario_id,"condition":item.condition or "A1",
        "status":item.status,"failure_code":item.failure_code,
        "task_success":grades.get("task_outcome") is GradeStatus.PASS,
        "strict_success":strict_success(item.grades),
        "authorization":grades.get("authorization", GradeStatus.UNKNOWN).value,
        "fallbacks":sum(event.data.get("used_fallback") is True for event in item.events if event.event_type == "proposal_finalized"),
        "contract_errors":sum(bool(event.data.get("validation",{}).get("initial_error_code")) for event in item.events if event.event_type == "proposal_finalized"),
        "first_diagnosis_proposal_turn":_event_turn(item,"proposal_finalized","submit_diagnosis"),
        "first_diagnosis_commit_turn":_event_turn(item,"world_committed","submit_diagnosis"),
        "first_treatment_proposal_turn":_event_turn(item,"proposal_finalized","execute_treatment"),
        "first_treatment_commit_turn":_event_turn(item,"world_committed","execute_treatment"),
        "usage_complete":item.input_tokens is not None and item.output_tokens is not None and all(event.data.get("usage_status") == "KNOWN" for event in model_events),
        "cost_cny":item.known_cost_cny,
        "rejection_events":sum(event.event_type == "confirmation_invalidated" for event in item.events),
        "confirmation_events":sum(event.event_type == "confirmation_received" for event in item.events),
    }


def _condition_summary(rows: list[dict]) -> dict:
    result={}
    for condition in sorted({row["condition"] for row in rows}):
        group=[row for row in rows if row["condition"] == condition]
        known=[r["cost_cny"] for r in group if r["cost_cny"] is not None]
        result[condition]={"n":len(group),"task_success_rate":sum(r["task_success"] for r in group)/len(group),
                           "strict_success_rate":sum(r["strict_success"] for r in group)/len(group),
                           "contract_errors":sum(r["contract_errors"] for r in group),
                           "fallbacks":sum(r["fallbacks"] for r in group),
                           "mean_cost_cny":mean(known) if known else None}
    return result


def _paired(rows: list[dict], left: str, right: str, tasks: set[str]) -> dict:
    grouped=defaultdict(dict)
    for row in rows:
        if row["task_id"] in tasks and row["condition"] in {left,right}:
            repeat=int(row["run_id"].rsplit("_r",1)[-1]); grouped[(row["task_id"],repeat)][row["condition"]]=row
    pairs=[value for value in grouped.values() if set(value)=={left,right}]
    def delta(key): return mean((int(pair[right][key])-int(pair[left][key])) for pair in pairs) if pairs else None
    costs=[pair[right]["cost_cny"]-pair[left]["cost_cny"] for pair in pairs if pair[right]["cost_cny"] is not None and pair[left]["cost_cny"] is not None]
    return {"pairs":len(pairs),f"{right}_minus_{left}_task_success":delta("task_success"),
            f"{right}_minus_{left}_strict_success":delta("strict_success"),
            f"{right}_minus_{left}_cost_cny":mean(costs) if costs else None}


def build(root: Path) -> dict:
    rows=[_row(item) for item in _artifacts(root)]; t16=[row for row in rows if row["task_id"]=="T16"]
    return {
        "schema_version":"v2.1_slim_report_v1","artifact_count":len(rows),
        "reliability":{"finished":sum(r["status"]=="finished" for r in rows),"aborted":sum(r["status"]=="aborted" for r in rows),"contract_errors":sum(r["contract_errors"] for r in rows),"fallbacks":sum(r["fallbacks"] for r in rows)},
        "safety":{"authorization_failures":sum(r["authorization"]=="FAIL" for r in rows),"authorization_unknown":sum(r["authorization"]=="UNKNOWN" for r in rows)},
        "task_completion":{"successes":sum(r["task_success"] for r in rows),"strict_successes":sum(r["strict_success"] for r in rows)},
        "observability":{"usage_complete":sum(r["usage_complete"] for r in rows),"usage_total":len(rows)},
        "conditions":_condition_summary(rows),
        "paired_differences":{"A1_minus_A0":_paired(rows,"A0","A1",{"C01","C02","C09","C10"}),"M1_minus_M0":_paired(rows,"M0","M1",{"MV01","MV06"})},
        "t16_reject_reproposal_confirmation":{"runs":len(t16),"complete_chains":sum(r["rejection_events"]>=1 and r["confirmation_events"]>=2 and r["task_success"] for r in t16)},
        "runs":rows,
        "claim_boundary":"Exploratory first round; no claim of broad generalization, Reflection efficacy, or release readiness."
    }


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--artifact-root",type=Path,required=True); parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv); report=build(args.artifact_root); args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"completed","artifact_count":report["artifact_count"],"output":str(args.output)},ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
