"""Build the immutable V2.1 slim first-round plan without provider calls."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from xuanyi_npc.evaluation.v21_schedule import build_execution_order


ROOT = Path(__file__).resolve().parents[3]
DESIGN = ROOT / "docs/evaluation/v2_design/revision_20260920"
CATALOG = DESIGN / "slim_first_round_catalog.json"
RUNTIME_FILES = (
    "src/xuanyi_npc/agents/game_npc.py",
    "src/xuanyi_npc/agents/simple_action.py",
    "src/xuanyi_npc/application/cooperative_runtime.py",
    "src/xuanyi_npc/application/action_contract.py",
    "src/xuanyi_npc/application/npc_authority.py",
    "src/xuanyi_npc/evaluation/v2_runner.py",
    "src/xuanyi_npc/evaluation/v2_memory_pairs.py",
    "src/xuanyi_npc/evaluation/v21_architecture_runner.py",
    "src/xuanyi_npc/evaluation/v21_execute.py",
    "src/xuanyi_npc/evaluation/v21_schedule.py",
    "src/xuanyi_npc/evaluation/v21_preflight.py",
    "src/xuanyi_npc/evaluation/v21_report.py",
    "src/xuanyi_npc/evaluation/v21_scenarios.py",
    "src/xuanyi_npc/evaluation/v21_pool_control.py",
    "src/xuanyi_npc/evaluation/v21_offline_substitute.py",
    "src/xuanyi_npc/evaluation/request_ledger.py",
    "src/xuanyi_npc/evaluation/v2_contracts.py",
    "src/xuanyi_npc/evaluation/v2_graders.py",
    "docs/evaluation/v2_design/revision_20260920/slim_first_round_catalog.json",
    "src/xuanyi_npc/resources/pilot/deepseek_flash_price_snapshot_2026-09-18.json",
)
CASE_FILES = tuple(
    f"src/xuanyi_npc/evaluation/fixtures/v21/cases/{name}.json"
    for name in (
        "c01_crossed_bell_testimony", "c02_red_ink_decoy",
        "c09_three_lock_cistern", "c10_ink_gate_sequence",
    )
)


def file_hash(relative: str) -> str:
    return sha256((ROOT / relative).read_bytes()).hexdigest()


def execution_order() -> list[dict]:
    """Compatibility alias used by existing offline tests."""
    return build_execution_order()


def build(experiment_id: str, plan_relative_path: str, *, scope: str = "full") -> dict:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = None
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    campaign="src/xuanyi_npc/evaluation/fixtures/v21/campaign/cross_episode_rules.json"
    hashes = {path: file_hash(path) for path in (*RUNTIME_FILES, *CASE_FILES, campaign)}
    cm_only=scope == "cm"; order = build_execution_order(("C","M") if cm_only else ("G","C","M"))
    tracks={"C":{"episodes":24,"conditions":["A0","A1"]},
            "M":{"episodes":12,"conditions":["M0","M1"],"reflection":False}}
    if not cm_only: tracks={"G":{"episodes":18,"conditions":["A1"]},**tracks}
    expected={"C":3.70,"M":2.50,"total":6.20} if cm_only else {"G":3.30,"C":3.70,"M":2.50,"total":9.50}
    caps={"C":6.00,"M":4.00,"total":10.00} if cm_only else {"G":4.50,"C":6.00,"M":4.00,"total":14.50}
    return {
        "schema_version":"v2.1_slim_frozen_plan_v2", "status":"FROZEN_AWAITING_PAID_AUTHORIZATION",
        "experiment_id":experiment_id, "created_date":"2026-09-20", "git_commit":commit,
        "model":{"provider":"deepseek","name":"deepseek-flash","temperature":0.0,
                 "max_output_tokens":2048,"max_repairs_per_request":1,"max_turns":16},
        "tracks":tracks,
        "planned_target_episodes":36 if cm_only else 54,
        "budget":{"currency":"CNY","non_transferable":True,
                  "expected":expected,
                  "hard_caps":caps,
                  "price_snapshot":file_hash("src/xuanyi_npc/resources/pilot/deepseek_flash_price_snapshot_2026-09-18.json")},
        "catalog_hash":sha256(CATALOG.read_bytes()).hexdigest(), "runtime_hashes":hashes,
        "execution_order":order,
        "stop_rules":["runtime_hash_drift","permission_or_commit_gate_failure","trace_or_usage_gap","pool_budget_halt"],
        "retry_policy":"no_selective_reruns", "paid_execution_authorized":False,
        "commands":({} if cm_only else {"G":f"python -m xuanyi_npc.evaluation.v21_execute --plan {plan_relative_path} --track G --confirm-paid-agent"}) | {
            "C":f"python -m xuanyi_npc.evaluation.v21_execute --plan {plan_relative_path} --track C --confirm-paid-agent",
            "M":f"python -m xuanyi_npc.evaluation.v21_execute --plan {plan_relative_path} --track M --confirm-paid-agent"
        },
        "catalog_summary":catalog["summary"]
    }


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--scope",choices=("full","cm"),default="full")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists(): raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    relative=args.output.resolve().relative_to(ROOT.resolve()).as_posix()
    args.output.write_text(json.dumps(build(args.experiment_id, relative,scope=args.scope), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__": raise SystemExit(main())
