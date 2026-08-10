from __future__ import annotations

import importlib
import sys

from xuanyi_npc.evaluation.semantic_memory_diagnostics import (
    POST_HOC_ANALYSIS_LABEL,
    DiagnosticCandidateCategory,
    DiagnosticCandidateScore,
    DiagnosticScenarioScore,
    ExploratoryPolicy,
    default_exploratory_policies,
    evaluate_exploratory_policy,
)
from xuanyi_npc.evaluation.semantic_memory_runner import load_semantic_gold_v2


def _scenario(
    scenario_id: str,
    *,
    relevant_score: float | None,
    negative_scores: tuple[float, ...],
) -> DiagnosticScenarioScore:
    values: list[tuple[str, float, DiagnosticCandidateCategory]] = [
        (f"{scenario_id}_negative_{index}", score, DiagnosticCandidateCategory.SEMANTIC_NEGATIVE)
        for index, score in enumerate(negative_scores, start=1)
    ]
    if relevant_score is not None:
        values.append(
            (
                f"{scenario_id}_relevant",
                relevant_score,
                DiagnosticCandidateCategory.RELEVANT,
            )
        )
    while len(values) < 4:
        values.append(
            (
                f"{scenario_id}_excluded_{len(values)}",
                -0.5,
                DiagnosticCandidateCategory.SAFETY_EXCLUDED,
            )
        )
    values.sort(key=lambda item: (-item[1], item[0]))
    legal_ids = [item[0] for item in values if item[2] is not DiagnosticCandidateCategory.SAFETY_EXCLUDED]
    return DiagnosticScenarioScore(
        scenario_id=scenario_id,
        split="test",
        candidates=tuple(
            DiagnosticCandidateScore(
                candidate_id=candidate_id,
                similarity=score,
                full_rank=index,
                legal_rank=(legal_ids.index(candidate_id) + 1 if candidate_id in legal_ids else None),
                category=category,
            )
            for index, (candidate_id, score, category) in enumerate(values, start=1)
        ),
    )


def test_top1_does_not_recover_a_relevant_item_ranked_fourth() -> None:
    scenario = _scenario(
        "correction",
        relevant_score=0.63,
        negative_scores=(0.66, 0.65, 0.64),
    )
    result = evaluate_exploratory_policy(
        policy=ExploratoryPolicy(
            policy_id="top1",
            absolute_threshold=-1.0,
            max_results=1,
            min_top1_to_top2_margin=0.0,
        ),
        scenarios=(scenario,),
    )

    assert result.analysis_label == POST_HOC_ANALYSIS_LABEL
    assert (result.true_positive, result.false_positive, result.false_negative) == (0, 1, 1)


def test_higher_absolute_threshold_trades_false_positive_for_false_negative() -> None:
    scenarios = (
        _scenario("low_relevant", relevant_score=0.64, negative_scores=(0.60,)),
        _scenario("high_negative", relevant_score=0.72, negative_scores=(0.69,)),
    )
    lower = evaluate_exploratory_policy(
        policy=ExploratoryPolicy(
            policy_id="lower",
            absolute_threshold=0.60,
            max_results=3,
            min_top1_to_top2_margin=0.0,
        ),
        scenarios=scenarios,
    )
    higher = evaluate_exploratory_policy(
        policy=ExploratoryPolicy(
            policy_id="higher",
            absolute_threshold=0.70,
            max_results=3,
            min_top1_to_top2_margin=0.0,
        ),
        scenarios=scenarios,
    )

    assert lower.false_positive > higher.false_positive
    assert lower.false_negative < higher.false_negative


def test_margin_gate_is_always_marked_post_hoc() -> None:
    result = evaluate_exploratory_policy(
        policy=ExploratoryPolicy(
            policy_id="margin",
            absolute_threshold=0.65,
            max_results=1,
            min_top1_to_top2_margin=0.02,
        ),
        scenarios=(
            _scenario("clear", relevant_score=0.75, negative_scores=(0.60,)),
        ),
    )

    assert result.analysis_label == POST_HOC_ANALYSIS_LABEL
    assert result.policy.analysis_label == POST_HOC_ANALYSIS_LABEL


def test_default_policies_preserve_frozen_threshold_grid() -> None:
    _, _, manifest = load_semantic_gold_v2()
    policies = default_exploratory_policies(manifest)
    absolute_thresholds = {
        item.absolute_threshold
        for item in policies
        if item.policy_id.startswith("absolute_") and item.max_results == 3
        and item.min_top1_to_top2_margin == 0
    }

    assert absolute_thresholds == set(manifest.preregistered_config.empty_threshold_grid)
    assert all(item.analysis_label == POST_HOC_ANALYSIS_LABEL for item in policies)


def test_diagnostic_module_does_not_import_model_runtimes() -> None:
    for module_name in ("torch", "transformers", "sentence_transformers"):
        sys.modules.pop(module_name, None)

    importlib.reload(
        importlib.import_module(
            "xuanyi_npc.evaluation.semantic_memory_diagnostics"
        )
    )

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
    assert "sentence_transformers" not in sys.modules
