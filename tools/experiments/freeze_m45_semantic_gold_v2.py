"""Build M4.5 semantic Gold v2 from the unchanged v1 public inputs.

This migration is contract-only. It never imports or loads the local BGE adapter
and never reads a Pilot result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xuanyi_npc.evaluation.semantic_memory_contracts import (
    SafetyExcludedCandidate,
    SafetyExclusionReason,
    SemanticGoldManifest,
    SemanticGoldManifestV2,
    SemanticGoldSuiteExpectation,
    SemanticGoldSuiteExpectationV2,
    SemanticGoldSuiteInput,
    SemanticScenarioExpectationV2,
)
from xuanyi_npc.memory.canonical import sha256_hex


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "evaluation"
INPUT_PATH = DATA / "m45_semantic_gold_inputs.json"
V1_EXPECTATION_PATH = DATA / "m45_semantic_gold_expectations.json"
V1_MANIFEST_PATH = DATA / "m45_semantic_gold_manifest.json"
V2_EXPECTATION_PATH = DATA / "m45_semantic_gold_expectations_v2.json"
V2_MANIFEST_PATH = DATA / "m45_semantic_gold_manifest_v2.json"


SAFETY_EXCLUSIONS: dict[
    str,
    tuple[tuple[str, SafetyExclusionReason], ...],
] = {
    "semantic_current_episode_exclusion_001": (
        ("cand_current_episode_exclusion_1", SafetyExclusionReason.CURRENT_EPISODE),
    ),
    "semantic_player_isolation_001": (
        ("cand_player_isolation_1", SafetyExclusionReason.CROSS_PLAYER),
    ),
    "semantic_invalidation_001": (
        ("cand_invalidation_1", SafetyExclusionReason.INVALIDATED),
    ),
    "semantic_hard_delete_001": (
        ("cand_hard_delete_1", SafetyExclusionReason.HARD_DELETED),
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    payload = value.model_dump(mode="json")  # type: ignore[attr-defined]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    suite = SemanticGoldSuiteInput.model_validate_json(
        INPUT_PATH.read_text(encoding="utf-8")
    )
    v1_expectations = SemanticGoldSuiteExpectation.model_validate_json(
        V1_EXPECTATION_PATH.read_text(encoding="utf-8")
    )
    v1_manifest = SemanticGoldManifest.model_validate_json(
        V1_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    relevant_by_scenario = {
        item.scenario_id: item.relevant_candidate_ids
        for item in v1_expectations.scenarios
    }
    v2_expectations = SemanticGoldSuiteExpectationV2(
        suite_id=suite.suite_id,
        source_input_schema_version=suite.schema_version,
        scenarios=tuple(
            SemanticScenarioExpectationV2(
                scenario_id=scenario.scenario_id,
                relevant_candidate_ids=relevant_by_scenario[scenario.scenario_id],
                semantic_negative_candidate_ids=tuple(
                    candidate.candidate_id
                    for candidate in scenario.candidates
                    if candidate.candidate_id
                    not in {
                        *relevant_by_scenario[scenario.scenario_id],
                        *(
                            candidate_id
                            for candidate_id, _ in SAFETY_EXCLUSIONS.get(
                                scenario.scenario_id,
                                (),
                            )
                        ),
                    }
                ),
                safety_excluded_candidates=tuple(
                    SafetyExcludedCandidate(candidate_id=candidate_id, reason=reason)
                    for candidate_id, reason in SAFETY_EXCLUSIONS.get(
                        scenario.scenario_id,
                        (),
                    )
                ),
                expected_empty=not relevant_by_scenario[scenario.scenario_id],
            )
            for scenario in suite.scenarios
        ),
    )
    _write_json(V2_EXPECTATION_PATH, v2_expectations)
    v2_manifest = SemanticGoldManifestV2(
        schema_version="m45_semantic_gold_manifest_v2",
        semantic_gold_contract_version="semantic_gold_contract_v2",
        suite_id=suite.suite_id,
        unchanged_v1_input_path="data/evaluation/m45_semantic_gold_inputs.json",
        scenario_input_sha256=_sha256(INPUT_PATH),
        gold_expectation_v2_sha256=_sha256(V2_EXPECTATION_PATH),
        preregistered_config_sha256=sha256_hex(v1_manifest.preregistered_config),
        preregistered_config=v1_manifest.preregistered_config,
        source_v1_expectation_sha256=_sha256(V1_EXPECTATION_PATH),
        source_v1_manifest_sha256=_sha256(V1_MANIFEST_PATH),
        v1_freeze_commit="e81331255945e3baba34a0525b3c2f338321d841",
        v1_stop_commit="41a5bdf254d964b35993809a86a01b75141d1381",
        v1_failure_checkpoint_sha256=(
            "6b7e35cd8a8f712061fa0576e7b6352f061c1494e8455008eb75893b6c7c1ba5"
        ),
        migration_version="semantic_gold_v1_to_v2_partition_only",
        model_metrics_read_or_generated=False,
        scenario_count=15,
        query_count=15,
        candidates_per_scenario=4,
        candidate_count=60,
        unique_public_text_count=75,
    )
    _write_json(V2_MANIFEST_PATH, v2_manifest)
    print(
        json.dumps(
            {
                "unchanged_input_sha256": v2_manifest.scenario_input_sha256,
                "expectations_v2_sha256": v2_manifest.gold_expectation_v2_sha256,
                "manifest_v2_sha256": _sha256(V2_MANIFEST_PATH),
                "config_sha256": v2_manifest.preregistered_config_sha256,
                "model_metrics_read_or_generated": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
