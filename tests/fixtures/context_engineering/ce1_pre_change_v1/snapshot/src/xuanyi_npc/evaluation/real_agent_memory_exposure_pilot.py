"""Paid, sequential E10 gate over the E9 exposure harness."""

from __future__ import annotations

import argparse
import json
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path

from xuanyi_npc.agents.deepseek import DeepSeekAdapterConfig, DeepSeekChatAdapter
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.memory import (
    BGE_M3_VERIFIED_MANIFEST_SHA256,
    BgeM3LocalEmbeddingAdapter,
    BgeM3LocalEmbeddingConfig,
    bge_m3_embedding_space_id,
)
from xuanyi_npc.resources.runtime import materialized_clinic_resources

from .cross_session_memory_exposure import canonical_hash, load_manifest, run_scenario


PILOT_ID = "cross_session_memory_exposure_real_agent_pilot_v1"
DEFAULT_MANIFEST = Path("tools/experiments/data/evaluation/cross_session_memory_exposure_v1.json")
DEFAULT_CONFIG = Path("tools/experiments/data/evaluation/cross_session_memory_exposure_real_agent_pilot_v1.json")


class CapturingRealAgent:
    def __init__(self, delegate: GameNPCAgent) -> None:
        self.delegate = delegate
        self.inputs = []

    def propose_turn(self, value):
        self.inputs.append(value)
        return self.delegate.propose_turn(value)

    def repair_action_contract(self, *args, **kwargs):
        return self.delegate.repair_action_contract(*args, **kwargs)

    def action_contract_fallback(self, *args, **kwargs):
        return self.delegate.action_contract_fallback(*args, **kwargs)

    def last_planning_execution(self):
        return self.delegate.last_planning_execution()


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def run_paid_pilot(*, output_root: Path, manifest_path: Path, config_path: Path) -> tuple:
    manifest = load_manifest(manifest_path)
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    root = output_root / PILOT_ID
    root.mkdir(parents=True, exist_ok=False)
    _write_new(root / "manifest.json", {
        "pilot_id": PILOT_ID, "artifact_kind": "real_agent_paid_pilot",
        "manifest_sha256": canonical_hash(manifest_path),
        "config_sha256": canonical_hash(config_path),
        "hard_budget_cny": config_data["hard_budget_cny"],
        "sequential_gate": [item.scenario_id for item in manifest.scenarios],
    })
    base = DeepSeekAdapterConfig.from_env()
    if base.model != config_data["model"]:
        raise RuntimeError("configured provider model does not match frozen pilot config")
    provider_config = DeepSeekAdapterConfig.model_validate({
        **base.model_dump(), "max_output_tokens": config_data["max_output_tokens"],
        "pilot_max_cost_cny": Decimal(config_data["hard_budget_cny"]),
    })
    adapter = DeepSeekChatAdapter(provider_config)
    adapter.require_configured_model()
    repository_root = Path(__file__).resolve().parents[3]
    model_dir = repository_root / "runtime_models" / "bge-m3-142964af7e05"
    model_manifest = repository_root / "tools/experiments/model_manifests/bge_m3_142964af7e05_dense_fp32_verified.json"
    space_id = bge_m3_embedding_space_id(device=config_data["memory_device"], max_input_length=512)
    embedding = BgeM3LocalEmbeddingAdapter(config=BgeM3LocalEmbeddingConfig(
        model_directory=model_dir, manifest_path=model_manifest,
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device=config_data["memory_device"], max_input_length=512, batch_size=8,
        embedding_space_id=space_id,
    ))
    artifacts = []
    try:
        embedding.load()
        with ExitStack() as stack:
            resources = stack.enter_context(materialized_clinic_resources())
            for index, scenario in enumerate(manifest.scenarios, start=1):
                real_agent = CapturingRealAgent(GameNPCAgent(adapter))
                artifact = run_scenario(
                    scenario=scenario, state_dir=root / "state" / scenario.scenario_id,
                    resources=resources, embedding_adapter=embedding, agent=real_agent,
                )
                artifacts.append(artifact)
                _write_new(root / "scenarios" / scenario.scenario_id / "artifact.json", artifact.model_dump(mode="json"))
                if index == 1:
                    positive_pass = (
                        bool(artifact.expected_memory_ids)
                        and artifact.retrieved_relevant_count == len(artifact.expected_memory_ids)
                        and artifact.relevant_selected
                        and artifact.agent_input_contains_memory_context
                    )
                    if not positive_pass:
                        break
                elif index == 2 and (artifact.memory_accepted_used_count or artifact.authority_violation):
                    break
    finally:
        adapter.close()
    _write_new(root / "aggregate.json", {
        "pilot_id": PILOT_ID, "paid_runs": len(artifacts),
        "total_input_tokens": sum(item.input_tokens for item in artifacts),
        "total_output_tokens": sum(item.output_tokens for item in artifacts),
        "total_estimated_cost_cny": sum(item.estimated_cost_cny for item in artifacts),
        "scenario_ids": [item.scenario_id for item in artifacts],
    })
    return tuple(artifacts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid-agent", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("evaluation_results"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    if not args.confirm_paid_agent:
        parser.error("--confirm-paid-agent is required")
    run_paid_pilot(output_root=args.output_root, manifest_path=args.manifest, config_path=args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
