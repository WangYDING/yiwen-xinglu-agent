import json
from pathlib import Path

from xuanyi_npc.evaluation.cross_session_memory_exposure import (
    SUITE_ID,
    canonical_hash,
    load_manifest,
    run_scenario,
    run_suite,
)
from xuanyi_npc.memory import DeterministicFakeEmbedding
from xuanyi_npc.resources.runtime import materialized_clinic_resources


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "tools" / "experiments" / "data" / "evaluation" / "cross_session_memory_exposure_v1.json"


def _run(tmp_path, index):
    manifest = load_manifest(MANIFEST)
    with materialized_clinic_resources() as resources:
        return run_scenario(
            scenario=manifest.scenarios[index], state_dir=tmp_path / f"state_{index}",
            resources=resources, embedding_adapter=DeterministicFakeEmbedding(),
        )


def test_positive_commits_indexes_persists_and_reaches_agent_input(tmp_path):
    result = _run(tmp_path, 0)
    assert result.session_a_episode_id != result.session_b_episode_id
    assert result.expected_memory_ids
    assert result.retrieved_relevant_count == len(result.expected_memory_ids)
    assert result.relevant_selected is True
    assert result.agent_input_contains_memory_context is True
    assert result.same_repository_path is True
    assert result.infrastructure_status == "ok"


def test_current_session_exclusion_and_player_isolation_remain_enforced(tmp_path):
    result = _run(tmp_path, 0)
    assert result.current_session_leakage is False
    assert result.player_isolation_violation is False
    assert result.authority_violation is False


def test_irrelevant_memory_is_exposed_as_false_positive_but_never_accepted(tmp_path):
    result = _run(tmp_path, 1)
    assert result.irrelevant_retrieved >= 1
    assert result.false_positive_exposure is True
    assert result.memory_declared_used_count == 0
    assert result.memory_accepted_used_count == 0


def test_empty_history_has_zero_exposure(tmp_path):
    result = _run(tmp_path, 2)
    assert result.session_a_episode_id is None
    assert result.memory_candidate_count == 0
    assert result.memory_selected_count == 0
    assert result.memory_declared_used_count == 0
    assert result.memory_accepted_used_count == 0
    assert result.expected_empty_correct is True


def test_suite_writes_separate_sanitized_artifacts_and_one_repo_per_pair(tmp_path):
    with materialized_clinic_resources() as resources:
        results = run_suite(
            manifest_path=MANIFEST, output_root=tmp_path / "results", resources=resources,
            embedding_adapter_factory=DeterministicFakeEmbedding,
        )
    assert len(results) == 3
    root = tmp_path / "results" / SUITE_ID
    assert (root / "manifest.json").is_file()
    for result in results:
        scenario = root / "scenarios" / result.scenario_id
        assert (scenario / "state" / "memories.sqlite3").is_file()
        assert len(list(scenario.rglob("memories.sqlite3"))) == 1
        payload = json.loads((scenario / "artifact.json").read_text(encoding="utf-8"))
        assert "hidden_truth" not in payload
        assert "raw_prompt" not in payload


def test_manifest_identity_is_stable_and_evaluation_only():
    manifest = load_manifest(MANIFEST)
    assert manifest.evaluation_only is True
    assert [item.condition for item in manifest.scenarios] == [
        "positive_transfer", "irrelevant_memory_negative", "empty_history_control"
    ]
    assert canonical_hash(MANIFEST) == "555c40960bc21d6dea6294477129f860273ac334e57c7a00e1cd2cc63c15123a"


def test_suite_is_not_in_formal_catalog_or_e6_manifest():
    with materialized_clinic_resources() as resources:
        from xuanyi_npc.application.multicase import CaseCatalog
        assert CaseCatalog(resources.case_dir).get(SUITE_ID) is None
    frozen = json.loads((ROOT / "tools" / "experiments" / "data" / "evaluation" / "agent_task_benchmark_v1.json").read_text(encoding="utf-8"))
    assert frozen["benchmark_version"] == "agent_task_benchmark_v1"
    assert frozen["case_ids"] == [
        "old_paper_umbrella", "gray_hearth_inn", "lantern_alley_conflicting_testimony"
    ]
    assert frozen["memory_mode"] == "semantic" and frozen["reflection_mode"] == "enabled"


def test_harness_reuses_production_retrieval_and_projection_types():
    from xuanyi_npc.application.game_npc_memory import GameNPCMemoryProjectionPolicy
    from xuanyi_npc.application.memory_retrieval import BasicCosineMemoryRetriever
    from xuanyi_npc.evaluation import cross_session_memory_exposure as harness
    assert harness.BasicCosineMemoryRetriever is BasicCosineMemoryRetriever
    assert harness.GameNPCMemoryProjectionPolicy is GameNPCMemoryProjectionPolicy
