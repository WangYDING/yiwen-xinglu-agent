"""Zero-provider-call preflight for a frozen V2.1 slim plan."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from xuanyi_npc.agents import ScriptedFakeLLM, SimpleActionGameNPCAgent
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.application.campaign import CampaignRuleSet
from xuanyi_npc.evaluation.v2_regression_preflight import _bge_runtime_probe
from xuanyi_npc.evaluation.v2_scenarios import _reachable_investigations
from xuanyi_npc.evaluation.v21_schedule import build_execution_order, track_sequence, validate_execution_order


ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "src/xuanyi_npc/evaluation/fixtures/v21/cases"


def run(plan_path: Path) -> dict:
    plan = json.loads(plan_path.read_text(encoding="utf-8")); errors=[]
    for relative, expected in plan["runtime_hashes"].items():
        path = ROOT / relative
        actual = sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != expected: errors.append(f"runtime hash mismatch: {relative}")
    order = plan["execution_order"]
    tracks=tuple(plan.get("tracks", {"G":{},"C":{},"M":{}}).keys())
    schedule_errors = validate_execution_order(order,tracks=tracks)
    errors.extend(f"schedule: {item}" for item in schedule_errors)
    expected_count=sum(item.get("episodes",{"G":18,"C":24,"M":12}[track]) for track,item in plan.get("tracks", {"G":{},"C":{},"M":{}}).items())
    if len(order) != expected_count: errors.append(f"expected {expected_count} episodes, found {len(order)}")
    counts = {track:sum(item["track"] == track for item in order) for track in tracks}
    expected_counts={track:plan.get("tracks",{}).get(track,{}).get("episodes",{"G":18,"C":24,"M":12}[track]) for track in tracks}
    if counts != expected_counts: errors.append(f"track counts mismatch: {counts}")
    entrypoint_sequences={}
    if not schedule_errors:
        for track in tracks:
            expanded=track_sequence(plan,track)
            frozen=[item for item in order if item["track"] == track]
            entrypoint_sequences[track]={"entries":len(expanded),"matches_frozen":expanded == frozen}
            if expanded != frozen: errors.append(f"entrypoint sequence mismatch: {track}")
    if plan["budget"]["hard_caps"]["total"] != sum(plan["budget"]["hard_caps"][k] for k in tracks):
        errors.append("hard budget pool sum mismatch")
    if hasattr(SimpleActionGameNPCAgent(ScriptedFakeLLM([])), "propose_turn"):
        errors.append("A0 unexpectedly exposes propose_turn")
    skills={key:100 for key in ("observe_form","ask_cause","inspect_evidence","inspect_object","observe_qi","reason_diagnosis","apply_treatment","ethical_practice")}
    reachability={}; catalog=CaseCatalog(CASES)
    try:
        CampaignRuleSet.load(ROOT/"src/xuanyi_npc/evaluation/fixtures/v21/campaign/cross_episode_rules.json",catalog)
    except Exception as exc:
        errors.append(f"C campaign/fixture compatibility failed: {type(exc).__name__}: {exc}")
    for case_id in ("c01_crossed_bell_testimony","c02_red_ink_decoy","c09_three_lock_cistern","c10_ink_gate_sequence"):
        case=catalog.get(case_id); investigations, clues=_reachable_investigations(case, skills)
        resolved=[item.treatment_id for item in case.treatments.values() if item.outcome.value == "resolved" and set(item.required_clue_ids).issubset(clues)]
        ok=len(investigations)==len(case.investigations) and len(resolved)==1
        reachability[case_id]={"reachable":ok,"investigations":list(investigations),"clues":list(clues),"resolved_treatment_count":len(resolved)}
        if not ok: errors.append(f"unreachable fixture: {case_id}")
    result_root=ROOT / "evaluation_results/v21" / plan["experiment_id"]
    if result_root.exists(): errors.append(f"immutable output already exists: {result_root}")
    bge=None
    if not errors:
        try: bge=_bge_runtime_probe()
        except Exception as exc: errors.append(f"BGE probe failed: {type(exc).__name__}: {exc}")
    return {"status":"READY" if not errors else "FAIL","paid_model_calls":0,"errors":errors,
            "episode_counts":counts,"reachability":reachability,"bge_preflight":bge,
            "schedule_validation":{"canonical_entries":len(build_execution_order(tracks)),"errors":schedule_errors,
                                   "entrypoints":entrypoint_sequences},
            "a0_shared_runtime_branch":not hasattr(SimpleActionGameNPCAgent(ScriptedFakeLLM([])), "propose_turn"),
            "budget":plan["budget"]}


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--plan",type=Path,required=True); parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv); result=run(args.plan); payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output: args.output.write_text(payload,encoding="utf-8")
    print(payload,end=""); return 0 if result["status"]=="READY" else 2


if __name__ == "__main__": raise SystemExit(main())
