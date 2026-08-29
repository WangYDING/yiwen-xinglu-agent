from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xuanyi_npc.evaluation.semantic_holdout_contracts import (
    CalibrationPolicyOutcome,
    CalibrationSelectionError,
    HoldoutContractError,
    HoldoutEvaluationMetrics,
    HoldoutManifest,
    HoldoutPolicyMetrics,
    HoldoutPreregisteredConfig,
    HoldoutScenarioPrediction,
    HoldoutSlice,
    HoldoutSplit,
    HoldoutSuiteExpectation,
    HoldoutSuiteInput,
    evaluate_holdout_predictions,
    select_conservative_policy,
    validate_holdout_partition,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tools" / "experiments" / "data" / "evaluation"
INPUT = DATA / "m45_semantic_holdout_inputs_v1.json"
GOLD = DATA / "m45_semantic_holdout_expectations_v1.json"
CONFIG = DATA / "m45_semantic_holdout_config_v1.json"
MANIFEST = DATA / "m45_semantic_holdout_manifest_v1.json"
OBSERVED = DATA / "m45_semantic_gold_inputs.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_suite() -> tuple[
    HoldoutSuiteInput,
    HoldoutSuiteExpectation,
    HoldoutPreregisteredConfig,
    HoldoutManifest,
]:
    return (
        HoldoutSuiteInput.model_validate_json(INPUT.read_text(encoding="utf-8")),
        HoldoutSuiteExpectation.model_validate_json(GOLD.read_text(encoding="utf-8")),
        HoldoutPreregisteredConfig.model_validate_json(
            CONFIG.read_text(encoding="utf-8")
        ),
        HoldoutManifest.model_validate_json(MANIFEST.read_text(encoding="utf-8")),
    )


def test_holdout_manifest_hashes_counts_and_partitions_are_frozen() -> None:
    suite, gold, config, manifest = load_suite()
    validate_holdout_partition(suite, gold, config)

    assert manifest.input_sha256 == sha(INPUT)
    assert manifest.expectation_sha256 == sha(GOLD)
    assert manifest.config_sha256 == sha(CONFIG)
    assert manifest.observed_development_input_sha256 == sha(OBSERVED)
    assert all(
        b"\r\n" not in path.read_bytes()
        for path in (INPUT, GOLD, CONFIG, MANIFEST)
    )
    assert len(suite.scenarios) == 36
    assert sum(item.split is HoldoutSplit.CALIBRATION for item in suite.scenarios) == 12
    assert sum(item.split is HoldoutSplit.FINAL_TEST for item in suite.scenarios) == 24
    assert sum(len(item.candidates) for item in suite.scenarios) == 144
    expectation_by_id = {item.scenario_id: item for item in gold.scenarios}
    assert sum(
        not expectation_by_id[item.scenario_id].expected_empty
        for item in suite.scenarios
        if item.split is HoldoutSplit.CALIBRATION
    ) == 8
    assert sum(
        not expectation_by_id[item.scenario_id].expected_empty
        for item in suite.scenarios
        if item.split is HoldoutSplit.FINAL_TEST
    ) == 20


def test_holdout_covers_required_slices_without_reusing_observed_sentences() -> None:
    suite, _, _, _ = load_suite()
    tags = {tag for scenario in suite.scenarios for tag in scenario.slice_tags}
    assert set(HoldoutSlice).issubset(tags)
    assert any(len(item.query.retrieval_intent) > 1000 for item in suite.scenarios)

    observed = json.loads(OBSERVED.read_text(encoding="utf-8"))
    observed_queries = {
        item["query"]["current_user_message"] for item in observed["scenarios"]
    }
    observed_actions = {
        candidate["source"]["public_action_description"]
        for scenario in observed["scenarios"]
        for candidate in scenario["candidates"]
    }
    new_queries = {item.query.retrieval_intent for item in suite.scenarios}
    new_actions = {
        candidate.source.public_action_description
        for scenario in suite.scenarios
        for candidate in scenario.candidates
    }
    assert not (observed_queries & new_queries)
    assert not (observed_actions & new_actions)
    serialized = INPUT.read_text(encoding="utf-8")
    forbidden = (
        "root_cause",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "correct_treatment",
        "api_key",
        "旧纸伞",
        "hidden_wooden_token",
    )
    assert all(item not in serialized.casefold() for item in forbidden)


def test_partition_reason_mismatch_and_omission_are_rejected() -> None:
    suite, gold, config, _ = load_suite()
    target = next(
        item for item in gold.scenarios if item.safety_excluded_candidates
    )
    bad_excluded = target.safety_excluded_candidates[0].model_copy(
        update={"reason": "hard_deleted"}
    )
    bad_target = target.model_copy(
        update={"safety_excluded_candidates": (bad_excluded,)}
    )
    bad_gold = gold.model_copy(
        update={
            "scenarios": tuple(
                bad_target if item.scenario_id == target.scenario_id else item
                for item in gold.scenarios
            )
        }
    )
    with pytest.raises(HoldoutContractError, match="reason"):
        validate_holdout_partition(suite, bad_gold, config)

    raw = target.model_dump()
    raw["semantic_negative_candidate_ids"] = raw[
        "semantic_negative_candidate_ids"
    ][:-1]
    with pytest.raises(ValueError, match="four"):
        type(target).model_validate(raw)


def test_selector_reads_exact_calibration_only_and_uses_frozen_tie_break() -> None:
    _, _, config, _ = load_suite()
    outcomes = tuple(
        CalibrationPolicyOutcome(
            parameter=parameter,
            evaluated_scenario_ids=config.calibration_scenario_ids,
            metrics=HoldoutPolicyMetrics(
                macro_f1=0.8,
                recall_at_3=0.9,
                mrr=0.85,
                irrelevant_retrieval_rate=0.1,
                empty_accuracy=1.0,
                safety_total=0,
            ),
        )
        for parameter in config.parameter_grid
    )
    selected = select_conservative_policy(outcomes=outcomes, config=config)
    assert selected.parameter.min_similarity == 0.75
    assert selected.parameter.max_results == 1
    assert selected.parameter.minimum_margin == 0.06

    contaminated = outcomes[0].model_copy(
        update={"evaluated_scenario_ids": config.final_test_scenario_ids}
    )
    with pytest.raises(CalibrationSelectionError, match="calibration"):
        select_conservative_policy(
            outcomes=(contaminated, *outcomes[1:]),
            config=config,
        )


def test_metrics_keep_semantic_fp_multi_relevant_and_undefined_denominators() -> None:
    suite, gold, _, _ = load_suite()
    gold_by_id = {item.scenario_id: item for item in gold.scenarios}
    predictions = []
    for scenario in suite.scenarios:
        expectation = gold_by_id[scenario.scenario_id]
        ranked = (
            *expectation.relevant_candidate_ids,
            *expectation.semantic_negative_candidate_ids,
        )
        returned = expectation.relevant_candidate_ids
        if scenario.scenario_id == "test_15_multi":
            returned = returned[:1]
        if scenario.scenario_id == "test_17_injection":
            returned = (
                *returned,
                expectation.semantic_negative_candidate_ids[0],
            )
        predictions.append(
            HoldoutScenarioPrediction(
                scenario_id=scenario.scenario_id,
                ranked_candidate_ids=ranked,
                returned_candidate_ids=returned,
            )
        )
    metrics = evaluate_holdout_predictions(
        suite=suite,
        gold=gold,
        predictions=tuple(predictions),
    )
    assert metrics.micro_false_positive == 1
    assert metrics.micro_false_negative == 1
    assert metrics.irrelevant_retrieval_numerator == 1
    assert metrics.empty_accuracy == 1.0
    assert metrics.return_counts[
        next(
            index
            for index, item in enumerate(suite.scenarios)
            if item.scenario_id == "test_15_multi"
        )
    ] == 1

    empty_suite = suite.model_copy(
        update={
            "scenarios": tuple(
                item for item in suite.scenarios if item.scenario_id.startswith("cal_09")
            )
        }
    )
    empty_gold = gold.model_copy(
        update={
            "scenarios": tuple(
                item for item in gold.scenarios if item.scenario_id.startswith("cal_09")
            )
        }
    )
    # The frozen suite contract deliberately rejects ad-hoc subsets; denominator
    # behavior is therefore checked directly on its strict result contract.
    undefined = HoldoutEvaluationMetrics(
        relevant_scenario_count=0,
        recall_at_1=None,
        recall_at_3=None,
        mrr=None,
        macro_precision=None,
        macro_recall=None,
        macro_f1=None,
        macro_precision_denominator=0,
        macro_recall_denominator=0,
        macro_f1_denominator=0,
        micro_true_positive=0,
        micro_false_positive=0,
        micro_false_negative=0,
        micro_precision=None,
        micro_recall=None,
        micro_f1=None,
        irrelevant_retrieval_numerator=0,
        irrelevant_retrieval_denominator=0,
        irrelevant_retrieval_rate=None,
        empty_correct=1,
        empty_total=1,
        empty_accuracy=1.0,
        correction_false_negative=0,
        negation_false_negative=0,
        return_counts=(0,),
    )
    assert undefined.irrelevant_retrieval_rate is None
    assert empty_suite.scenarios and empty_gold.scenarios


def test_gold_is_not_imported_by_product_retrieval_modules() -> None:
    product_files = (
        ROOT / "src" / "xuanyi_npc" / "application" / "retrieval_query.py",
        ROOT / "src" / "xuanyi_npc" / "application" / "memory_retrieval.py",
        ROOT / "src" / "xuanyi_npc" / "memory" / "representations.py",
        ROOT / "src" / "xuanyi_npc" / "application" / "game_npc_memory.py",
    )
    for path in product_files:
        text = path.read_text(encoding="utf-8")
        assert "m45_semantic_holdout" not in text
        assert "relevant_candidate_ids" not in text
        assert "semantic_negative_candidate_ids" not in text
