from pathlib import Path

import pytest

from xuanyi_npc.evaluation.v2_contracts import V2RunArtifact
from xuanyi_npc.evaluation.v21_usage_correction import correct_artifact_usage, load_request_ledger


ROOT=Path(__file__).parents[1]
RUN=ROOT/"evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/architecture_comparison/runs/c09_a0_r02/artifact.json"
LEDGER=ROOT/"evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/architecture_comparison/request_ledger.jsonl"


@pytest.mark.skipif(not RUN.exists() or not LEDGER.exists(),reason="authorized real-run evidence is not present")
def test_real_c09_request_ids_recover_usage_without_pool_cost_inference():
    original=V2RunArtifact.model_validate_json(RUN.read_text(encoding="utf-8"))
    corrected,audit=correct_artifact_usage(original,load_request_ledger(LEDGER))
    assert original.known_cost_cny is None
    assert audit["request_count"] == audit["unique_request_ids"] == 32
    assert audit["corrected_request_ids"] == ["0c002c9d-405a-490c-880b-681f508cc014"]
    assert corrected.input_tokens == 68516
    assert corrected.output_tokens == 9108
    assert corrected.known_cost_cny == pytest.approx(0.11757216)
    assert corrected.failure_code == "max_turns_exceeded"
