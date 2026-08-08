from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.evaluation.semantic_memory_contracts import (
    REQUIRED_SEMANTIC_SCENARIOS,
    SemanticGoldManifest,
    SemanticGoldSuiteInput,
)
from xuanyi_npc.evaluation.semantic_memory_runner import (
    DEFAULT_INPUT,
    DEFAULT_MANIFEST,
    classification_metrics,
    load_semantic_gold,
    materialize_frozen_texts,
    ranking_metrics,
    select_empty_threshold,
    _prepare_repository,
    _query_text,
)
from xuanyi_npc.memory.embeddings import DeterministicFakeEmbedding, MemoryRetrievalConfig


def test_frozen_semantic_gold_has_exact_scale_and_order() -> None:
    suite, expectations, manifest = load_semantic_gold()

    assert tuple(item.scenario_id for item in suite.scenarios) == REQUIRED_SEMANTIC_SCENARIOS
    assert tuple(item.scenario_id for item in expectations.scenarios) == REQUIRED_SEMANTIC_SCENARIOS
    assert len(suite.scenarios) == 15
    assert sum(len(item.candidates) for item in suite.scenarios) == 60
    assert len(materialize_frozen_texts(suite)) == 75
    assert manifest.scenario_count == 15
    assert manifest.candidate_count == 60
    assert manifest.unique_public_text_count == 75


def test_semantic_gold_contracts_forbid_unknown_fields() -> None:
    payload = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        SemanticGoldSuiteInput.model_validate(payload)

    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    with pytest.raises(ValidationError):
        SemanticGoldManifest.model_validate(manifest)


def test_gold_expectations_are_separate_from_model_visible_inputs() -> None:
    input_text = DEFAULT_INPUT.read_text(encoding="utf-8")
    assert "relevant_candidate_ids" not in input_text
    assert "forbidden_candidate_ids" not in input_text
    assert "expected_empty" not in input_text


def test_frozen_texts_are_public_unique_and_hide_internal_sentinels() -> None:
    suite, _, _ = load_semantic_gold()
    texts = materialize_frozen_texts(suite)
    serialized = json.dumps(texts, ensure_ascii=False)

    assert len(texts) == len(set(texts.values())) == 75
    assert all(len(value) <= 4096 for value in texts.values())
    for fragment in (
        "root_cause",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "correct_treatment",
        "hidden_prerequisite",
        "score_breakdown",
    ):
        assert fragment not in serialized


def test_wrong_diagnosis_remains_submission_provenance() -> None:
    suite, _, _ = load_semantic_gold()
    texts = materialize_frozen_texts(suite)
    value = texts["cand_wrong_diagnosis_provenance_1"]

    assert "玩家提交过公开假设" in value
    assert "雾鸦侵梦" in value
    assert "诊断正确" not in value
    assert "真实病因" not in value


def test_long_and_short_text_boundaries_are_distinct() -> None:
    suite, _, manifest = load_semantic_gold()
    texts = materialize_frozen_texts(suite)

    assert texts["cand_short_text_1"] == "守约。"
    assert 3000 < len(texts["query_long_text"]) <= manifest.preregistered_config.max_input_characters
    assert manifest.preregistered_config.max_length_tokens == 512
    assert manifest.preregistered_config.max_input_characters == 4096


def test_metric_denominators_and_empty_values_are_explicit() -> None:
    _, expectations, _ = load_semantic_gold()
    by_id = {item.scenario_id: item for item in expectations.scenarios}
    ids = ("semantic_zh_synonym_001", "semantic_empty_001")
    selected = {
        "semantic_zh_synonym_001": ("cand_zh_synonym_1",),
        "semantic_empty_001": (),
    }

    classification = classification_metrics(ids, selected, by_id)
    ranking = ranking_metrics(ids, selected, by_id)

    assert classification.micro_true_positive == 1
    assert classification.micro_false_positive == 0
    assert classification.micro_false_negative == 0
    assert classification.empty_correct == classification.empty_total == 1
    assert classification.false_memory_numerator == 0
    assert classification.false_memory_denominator == 1
    assert ranking.relevant_scenario_count == 1
    assert ranking.recall_at_1 == ranking.recall_at_3 == ranking.mrr == 1.0


def test_threshold_selection_uses_calibration_only_and_higher_tie_break() -> None:
    _, expectations, manifest = load_semantic_gold()
    by_id = {item.scenario_id: item for item in expectations.scenarios}
    scores = {}
    for scenario_id in manifest.preregistered_config.calibration_scenario_ids:
        expectation = by_id[scenario_id]
        if expectation.relevant_candidate_ids:
            scores[scenario_id] = ((expectation.relevant_candidate_ids[0], 0.75),)
        else:
            scores[scenario_id] = ((f"noise_{scenario_id.removeprefix('semantic_')}", 0.70),)

    threshold, metrics = select_empty_threshold(
        manifest.preregistered_config,
        scores,
        by_id,
    )

    assert threshold == 0.75
    assert metrics.empty_accuracy == 1.0
    assert metrics.macro_f1 == 1.0


def test_manifest_split_is_five_calibration_and_ten_test() -> None:
    _, _, manifest = load_semantic_gold()
    config = manifest.preregistered_config

    assert len(config.calibration_scenario_ids) == 5
    assert len(config.test_scenario_ids) == 10
    assert set(config.calibration_scenario_ids).isdisjoint(config.test_scenario_ids)
    assert set(config.calibration_scenario_ids) | set(config.test_scenario_ids) == set(REQUIRED_SEMANTIC_SCENARIOS)


def test_model_and_result_directories_are_git_ignored() -> None:
    root = DEFAULT_INPUT.parents[2]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "runtime_models/" in ignore
    assert "results/" in ignore


def test_all_scenarios_cross_the_real_repository_and_retriever_offline(tmp_path: Path) -> None:
    suite, _, _ = load_semantic_gold()
    adapter = DeterministicFakeEmbedding()

    for scenario in suite.scenarios:
        repository, aliases, retriever, scope, query = _prepare_repository(
            scenario,
            adapter,
            tmp_path / scenario.scenario_id / "memory.sqlite3",
        )
        result = retriever.retrieve_scoped(
            scope=scope,
            query_text=query,
            config=MemoryRetrievalConfig(
                top_k=3,
                min_similarity=-1.0,
                embedding_space_id=adapter.embedding_space_id,
                query_template_version="memory_query_v1",
            ),
        )

        assert all(hit.memory_id in aliases for hit in result.hits)
        assert all(hit.player_id == scenario.player_id for hit in result.hits)
        assert all(hit.source_session_id != scenario.current_session_id for hit in result.hits)
        assert _query_text(scenario) == query
        assert repository.schema_version() == 2
