"""Execute one frozen V2.1 budget pool after an explicit paid-run flag."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from xuanyi_npc.evaluation import v2_memory_pairs, v2_runner, v21_architecture_runner
from xuanyi_npc.evaluation.v21_schedule import track_sequence
from xuanyi_npc.evaluation.v21_offline_substitute import OfflineBudgetAdapter, OfflineOracleActionAgent, OfflineOraclePlanningAgent


ROOT = Path(__file__).resolve().parents[3]
CHILD = {"G":"real_model_trials", "C":"architecture_comparison", "M":"real_model_memory_pairs"}


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--track",choices=("G","C","M"),required=True); parser.add_argument("--confirm-paid-agent",action="store_true")
    parser.add_argument("--offline-preflight",action="store_true")
    parser.add_argument("--output-root",type=Path)
    args=parser.parse_args(argv)
    if not args.offline_preflight and not args.confirm_paid_agent: raise ValueError("explicit --confirm-paid-agent is required")
    plan=json.loads(args.plan.read_text(encoding="utf-8"))
    sequence=track_sequence(plan,args.track)
    errors=[]
    for relative, expected in plan["runtime_hashes"].items():
        path=ROOT/relative; actual=sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != expected: errors.append(relative)
    if errors: raise RuntimeError(f"frozen runtime drift: {errors}")
    experiment_id=plan["experiment_id"]; cap=plan["budget"]["hard_caps"][args.track]
    output_root=args.output_root or ROOT/("evaluation_results/v21_preflight" if args.offline_preflight else "evaluation_results/v21")
    target=output_root/experiment_id/CHILD[args.track]
    if target.exists(): raise FileExistsError(f"immutable output already exists: {target}")
    common={"experiment_id":experiment_id,"budget_cny":cap,"confirm_paid_agent":True,"output_root":output_root}
    if args.track == "G":
        return v2_runner.run_real(SimpleNamespace(**common,phase="full",model=plan["model"]["name"],max_turns=16,
            seed=20260920,exclude_artifact_root=None,scenario_id=["T01","T07","T09","T16","T17","T23"],repeats=3,
            per_episode_budget_cny=0.25,deadline_seconds=300,execution_sequence=sequence))
    if args.track == "C":
        extra={}
        if args.offline_preflight:
            adapter=OfflineBudgetAdapter(cap); case_root=v21_architecture_runner.CASE_ROOT
            extra={"offline_adapter":adapter,"offline_agents":{"A0":OfflineOracleActionAgent(case_root,adapter),"A1":OfflineOraclePlanningAgent(case_root,adapter)}}
        return v21_architecture_runner.run(SimpleNamespace(**common,model=plan["model"]["name"],execution_sequence=sequence,**extra))
    extra={}
    if args.offline_preflight:
        adapter=OfflineBudgetAdapter(cap)
        extra={"offline_adapter":adapter,"offline_agent":OfflineOraclePlanningAgent(ROOT/"src/xuanyi_npc/resources/cases",adapter)}
    return v2_memory_pairs.run(SimpleNamespace(**common,scenario_id=["MV01","MV06"],repeat=[1,2,3],condition=["M0","M1"],
        per_episode_budget_cny=0.3333,deadline_seconds=300,execution_sequence=sequence,**extra))


if __name__ == "__main__": raise SystemExit(main())
