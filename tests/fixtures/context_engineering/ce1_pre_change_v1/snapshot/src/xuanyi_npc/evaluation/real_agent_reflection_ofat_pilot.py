"""Paid, matched, sequential E12 Reflection OFAT pilot runner."""

from __future__ import annotations

import argparse
import hashlib
import json
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

from .cross_session_memory_exposure import canonical_hash
from .real_agent_memory_exposure_pilot import CapturingRealAgent
from .reflection_ofat import run_condition


PILOT_ID = "cross_session_reflection_ofat_real_agent_pilot_v1"
CONTROL = Path("tools/experiments/data/evaluation/cross_session_reflection_ofat_control_v1.json")
ABLATION = Path("tools/experiments/data/evaluation/cross_session_reflection_ofat_ablation_v1.json")
CONFIG = Path("tools/experiments/data/evaluation/cross_session_reflection_ofat_real_agent_pilot_v1.json")


class RecordingAdapter:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.requests = []
        self.usages = []

    def complete(self, request):
        self.requests.append(request)
        response = self.delegate.complete(request)
        if response.usage is not None:
            self.usages.append(response.usage)
        return response


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _runtime_hashes(root: Path) -> dict[str, str]:
    frozen = json.loads((root / "evaluation_results/agent_task_benchmark_post_e5_recruitment_3x3/agent_task_benchmark_v1/manifest.json").read_text(encoding="utf-8"))
    values = {}
    for relative, expected in frozen["runtime_hashes"].items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"production runtime hash changed: {relative}")
        values[relative] = actual
    return values


def run_paid_pilot(*, output_root: Path, control_path: Path, ablation_path: Path, config_path: Path):
    root_dir = Path(__file__).resolve().parents[3]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runtime_hashes = _runtime_hashes(root_dir)
    artifact_root = output_root / PILOT_ID
    artifact_root.mkdir(parents=True, exist_ok=False)
    _write_new(artifact_root / "manifest.json", {
        "pilot_id": PILOT_ID, "artifact_kind": "real_agent_paid_pilot",
        "control_hash": canonical_hash(control_path),
        "ablation_hash": canonical_hash(ablation_path),
        "pilot_config_hash": canonical_hash(config_path),
        "hard_budget_cny": config["hard_budget_cny"],
        "runtime_hashes": runtime_hashes,
        "sequential_order": ["control", "ablation"],
    })
    base = DeepSeekAdapterConfig.from_env()
    if base.model != config["model"]:
        raise RuntimeError("provider model does not match frozen E12 config")
    adapter = DeepSeekChatAdapter(DeepSeekAdapterConfig.model_validate({
        **base.model_dump(), "max_output_tokens": config["max_output_tokens"],
        "pilot_max_cost_cny": Decimal(config["hard_budget_cny"]),
    }))
    adapter.require_configured_model()
    model_dir = root_dir / "runtime_models/bge-m3-142964af7e05"
    model_manifest = root_dir / "tools/experiments/model_manifests/bge_m3_142964af7e05_dense_fp32_verified.json"
    space_id = bge_m3_embedding_space_id(device=config["memory_device"], max_input_length=512)
    embedding = BgeM3LocalEmbeddingAdapter(config=BgeM3LocalEmbeddingConfig(
        model_directory=model_dir, manifest_path=model_manifest,
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device=config["memory_device"], max_input_length=512, batch_size=8,
        embedding_space_id=space_id,
    ))
    artifacts = []
    try:
        embedding.load()
        with materialized_clinic_resources() as resources:
            reflection_adapter = RecordingAdapter(adapter)
            control_agent = CapturingRealAgent(GameNPCAgent(adapter))
            control = run_condition(
                condition_path=control_path, state_dir=artifact_root / "control/state",
                resources=resources, embedding_adapter=embedding,
                session_b_agent=control_agent, reflection_adapter=reflection_adapter,
            )
            artifacts.append(control)
            _write_new(artifact_root / "control/artifact.json", control.model_dump(mode="json"))
            derived = set(control.reflection_derived_memory_ids)
            control_pass = (
                control.reflection_trigger_count == 1
                and control.reflection_generation_count >= 1
                and bool(derived)
                and control.reflection_indexed_count == len(derived)
                and derived.issubset(control.reflection_derived_candidate_ids)
                and derived.issubset(control.reflection_derived_selected_ids)
                and derived.issubset(control.agent_input_memory_ids)
                and control.infrastructure_failures == 0
            )
            if control_pass:
                ablation_agent = CapturingRealAgent(GameNPCAgent(adapter))
                ablation = run_condition(
                    condition_path=ablation_path, state_dir=artifact_root / "ablation/state",
                    resources=resources, embedding_adapter=embedding,
                    session_b_agent=ablation_agent,
                )
                artifacts.append(ablation)
                _write_new(artifact_root / "ablation/artifact.json", ablation.model_dump(mode="json"))
    finally:
        adapter.close()
    _write_new(artifact_root / "aggregate.json", {
        "pilot_id": PILOT_ID,
        "conditions_run": [item.condition for item in artifacts],
        "paid_provider_requests": sum(item.provider_requests for item in artifacts),
        "total_input_tokens": sum(item.input_tokens for item in artifacts),
        "total_output_tokens": sum(item.output_tokens for item in artifacts),
        "total_estimated_cost_cny": sum(item.estimated_cost_cny for item in artifacts),
    })
    return tuple(artifacts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid-agent", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("evaluation_results"))
    args = parser.parse_args(argv)
    if not args.confirm_paid_agent:
        parser.error("--confirm-paid-agent is required")
    run_paid_pilot(
        output_root=args.output_root, control_path=CONTROL,
        ablation_path=ABLATION, config_path=CONFIG,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
