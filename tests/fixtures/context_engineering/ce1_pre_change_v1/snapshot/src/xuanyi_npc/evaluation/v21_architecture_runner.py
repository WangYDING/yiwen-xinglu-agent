"""Paid V2.1 slim architecture comparison. Run only from a frozen plan."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from decimal import Decimal
import json
import os
from pathlib import Path
import random

from dotenv import load_dotenv

from xuanyi_npc.agents import DeepSeekAdapterConfig, DeepSeekChatAdapter, GameNPCAgent, SimpleActionGameNPCAgent
from xuanyi_npc.evaluation.costing import load_deepseek_pilot_pricing
from xuanyi_npc.evaluation.v2_runner import RealTaskExecutor, _write_artifact, aggregate, provider_budget_snapshot
from xuanyi_npc.evaluation.v2_contracts import ArtifactKind
from xuanyi_npc.evaluation.request_ledger import DurableRequestLedger, EvidenceRecordingLLMAdapter, reconcile_request_ledger
from xuanyi_npc.evaluation.v21_pool_control import blocking_reason, write_execution_status


ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = ROOT / "src/xuanyi_npc/evaluation/fixtures/v21/cases"
CAMPAIGN = ROOT / "src/xuanyi_npc/evaluation/fixtures/v21/campaign/cross_episode_rules.json"
PRICE = ROOT / "src/xuanyi_npc/resources/pilot/deepseek_flash_price_snapshot_2026-09-18.json"
TASKS = {
    "C01": "c01_crossed_bell_testimony", "C02": "c02_red_ink_decoy",
    "C09": "c09_three_lock_cistern", "C10": "c10_ink_gate_sequence",
}


def _oracle(case_id: str) -> dict:
    raw = json.loads((CASE_ROOT / f"{case_id}.json").read_text(encoding="utf-8"))
    resolved = [key for key, value in raw["treatments"].items() if value["outcome"] == "resolved"]
    return {"valid_diagnosis_ids": raw["valid_diagnosis_ids"], "resolved_treatment_ids": resolved}


def run(args) -> int:
    offline_agents = getattr(args, "offline_agents", None)
    if (not offline_agents and not args.confirm_paid_agent) or args.budget_cny <= 0:
        raise ValueError("requires --confirm-paid-agent and positive --budget-cny")
    load_dotenv(ROOT / ".env")
    os.environ["DEEPSEEK_MODEL"] = args.model
    out = args.output_root / args.experiment_id / "architecture_comparison"
    out.mkdir(parents=True, exist_ok=False)
    frozen_sequence=getattr(args,"execution_sequence",None)
    if frozen_sequence is None:
        pairs=[(task,repeat) for task in TASKS for repeat in (1,2,3)]
        random.Random(20260920).shuffle(pairs)
        sequence=[]
        for task,repeat in pairs:
            conditions=["A0","A1"]; random.Random(f"{task}:{repeat}:20260920").shuffle(conditions)
            sequence.extend((task,repeat,condition) for condition in conditions)
    else:
        sequence=[(entry["task_id"],int(entry["repeat"]),entry["condition"]) for entry in frozen_sequence]
        if any(task not in TASKS or condition not in {"A0","A1"} for task,_,condition in sequence):
            raise ValueError("invalid frozen C execution sequence")
    artifacts = []; started=[]; stop_reason=None
    adapter = None
    try:
        with ExitStack() as stack:
            if offline_agents:
                agents = offline_agents; adapter = getattr(args, "offline_adapter")
            else:
                base = DeepSeekAdapterConfig.from_env()
                config = base.model_copy(update={"model": args.model, "max_output_tokens": 2048,
                                                  "pilot_max_cost_cny": Decimal(str(args.budget_cny))})
                base_adapter = DeepSeekChatAdapter(config, pricing=load_deepseek_pilot_pricing(PRICE))
                base_adapter.require_configured_model(); stack.callback(base_adapter.close)
                adapter = EvidenceRecordingLLMAdapter(base_adapter, DurableRequestLedger(out/"request_ledger.jsonl"))
                agents = {"A0": SimpleActionGameNPCAgent(adapter), "A1": GameNPCAgent(adapter)}
            resources = type("Resources", (), {"case_dir": CASE_ROOT, "campaign_rules": CAMPAIGN})()
            for task,repeat,condition in sequence:
                scenario = {"id": task, "base_case_id": TASKS[task], "profile": "cooperative",
                            "stimulus": "请与我共同查明公开证据之间的关系，按合法步骤完成诊断与处置。"}
                executor = RealTaskExecutor(agent=agents[condition], adapter=adapter, resources=resources,
                                            max_turns=16, experiment_id=args.experiment_id, condition=condition,
                                            per_episode_budget_cny=0.25, deadline_seconds=300)
                artifact = executor.execute(scenario, _oracle(TASKS[task]), repeat)
                try:
                    _write_artifact(out, artifact)
                except Exception as exc:
                    stop_reason=f"artifact_persistence_failed:{type(exc).__name__}"
                    break
                artifacts.append(artifact); started.append({"task_id":task,"repeat":repeat,"condition":condition})
                stop_reason=blocking_reason(artifact)
                if stop_reason: break
                if not adapter.request_budget.can_start_episode:
                    stop_reason=adapter.request_budget.stop_reason or "pool_budget_halt"
                    break
    except Exception as exc:
        stop_reason=f"pool_initialization_or_execution_failure:{type(exc).__name__}"
    finally:
        if adapter is not None:
            budget=provider_budget_snapshot(adapter)
            (out / "provider_budget.json").write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ledger=out/"request_ledger.jsonl"
            if ledger.exists():
                (out/"request_ledger_reconciliation.json").write_text(json.dumps(reconcile_request_ledger(ledger,budget),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    planned=[{"task_id":task,"repeat":repeat,"condition":condition} for task,repeat,condition in sequence]
    write_execution_status(out,planned=planned,started=started,stop_reason=stop_reason)
    result = aggregate(args.experiment_id, ArtifactKind.REAL_MODEL_TRIAL, len(planned), artifacts)
    (out / "aggregate.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed" if len(artifacts) == 24 else "budget_halted",
                      "planned": 24, "started": len(artifacts), "artifact_root": str(out)}, ensure_ascii=False))
    return 0 if len(artifacts) == len(planned) else 3


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--budget-cny", type=float, required=True)
    parser.add_argument("--confirm-paid-agent", action="store_true")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--output-root", type=Path, default=Path("evaluation_results/v21"))
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
