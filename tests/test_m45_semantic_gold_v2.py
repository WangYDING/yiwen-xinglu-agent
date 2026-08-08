from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.evaluation.semantic_memory_contracts import (
    SafetyExclusionReason,
    SemanticCandidateRuntimeFact,
    SemanticCandidateRuntimeStatus,
    SemanticGoldSuiteExpectationV2,
)
from xuanyi_npc.evaluation.semantic_memory_runner import (
    DEFAULT_EXPECTATIONS,
    DEFAULT_EXPECTATIONS_V2,
    DEFAULT_INPUT,
    DEFAULT_MANIFEST,
    DEFAULT_MANIFEST_V2,
    _candidate_runtime_facts,
    _eligible_candidate_ids,
    _prepare_repository,
    _query_text,
    classification_metrics,
    load_semantic_gold_v2,
    ranking_metrics,
    runtime_safety_counts,
    validate_v2_partition_against_input,
)
from xuanyi_npc.memory.embeddings import DeterministicFakeEmbedding


def _sha256(path: object) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()  # type: ignore[attr-defined]


def _scenario(scenario_id: str):  # type: ignore[no-untyped-def]
    suite, expectations, _ = load_semantic_gold_v2()
    scenario = next(item for item in suite.scenarios if item.scenario_id == scenario_id)
    expectation = next(
        item for item in expectations.scenarios if item.scenario_id == scenario_id
    )
    return scenario, expectation


def _active_runtime_facts(scenario):  # type: ignore[no-untyped-def]
    return tuple(
        SemanticCandidateRuntimeFact(
            candidate_id=item.candidate_id,
            player_id=item.source.player_id,
            source_session_id=item.source.source_session_id,
            status=SemanticCandidateRuntimeStatus.ACTIVE,
        )
        for item in scenario.candidates
    )


def test_v2_freeze_reuses_v1_inputs_and_preserves_v1_file_identities() -> None:
    _, _, manifest = load_semantic_gold_v2()

    assert manifest.scenario_input_sha256 == (
        "ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d"
    )
    assert manifest.scenario_input_sha256 == _sha256(DEFAULT_INPUT)
    assert manifest.source_v1_expectation_sha256 == _sha256(DEFAULT_EXPECTATIONS)
    assert manifest.source_v1_manifest_sha256 == _sha256(DEFAULT_MANIFEST)
    assert manifest.gold_expectation_v2_sha256 == _sha256(DEFAULT_EXPECTATIONS_V2)
    assert manifest.model_metrics_read_or_generated is False


def test_all_15_scenarios_have_a_complete_four_candidate_v2_partition() -> None:
    suite, expectations, _ = load_semantic_gold_v2()
    by_id = {item.scenario_id: item for item in expectations.scenarios}

    assert len(suite.scenarios) == len(expectations.scenarios) == 15
    for scenario in suite.scenarios:
        expectation = by_id[scenario.scenario_id]
        partition = (
            set(expectation.relevant_candidate_ids)
            | set(expectation.semantic_negative_candidate_ids)
            | {
                item.candidate_id
                for item in expectation.safety_excluded_candidates
            }
        )
        assert len(scenario.candidates) == 4
        assert partition == {item.candidate_id for item in scenario.candidates}


def test_all_v2_safety_reasons_match_materialized_repository_state(
    tmp_path: Path,
) -> None:
    suite, expectations, _ = load_semantic_gold_v2()
    by_id = {item.scenario_id: item for item in expectations.scenarios}
    adapter = DeterministicFakeEmbedding()

    for scenario in suite.scenarios:
        repository, aliases, _, _, _ = _prepare_repository(
            scenario,
            adapter,
            tmp_path / scenario.scenario_id / "memory.sqlite3",
        )
        facts = _candidate_runtime_facts(
            scenario=scenario,
            repository=repository,
            aliases=aliases,
        )
        expectation = by_id[scenario.scenario_id]
        assert _eligible_candidate_ids(facts, scenario) == (
            expectation.legal_ranking_candidate_ids
        )
        actual_excluded = {
            fact.candidate_id: (
                SafetyExclusionReason.CROSS_PLAYER
                if fact.player_id != scenario.player_id
                else (
                    SafetyExclusionReason.CURRENT_EPISODE
                    if fact.source_session_id == scenario.current_session_id
                    else SafetyExclusionReason(fact.status.value)
                )
            )
            for fact in facts
            if fact.candidate_id not in expectation.legal_ranking_candidate_ids
        }
        assert actual_excluded == {
            item.candidate_id: item.reason
            for item in expectation.safety_excluded_candidates
        }


def test_high_lexical_overlap_decoy_is_a_legal_semantic_negative() -> None:
    _, expectation = _scenario("semantic_lexical_distractor_001")

    assert "cand_lexical_distractor_2" in (
        expectation.semantic_negative_candidate_ids
    )
    assert expectation.safety_excluded_candidates == ()


def test_high_lexical_decoy_in_top_three_is_fp_but_not_safety() -> None:
    scenario, expectation = _scenario("semantic_lexical_distractor_001")
    selected = {
        scenario.scenario_id: (
            "cand_lexical_distractor_2",
            "cand_lexical_distractor_1",
            "cand_lexical_distractor_3",
        )
    }

    metrics = classification_metrics(
        (scenario.scenario_id,),
        selected,
        {scenario.scenario_id: expectation},
    )
    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=_active_runtime_facts(scenario),
        entered_candidate_ids=frozenset(selected[scenario.scenario_id]),
    )

    assert metrics.micro_true_positive == 1
    assert metrics.micro_false_positive == 2
    assert metrics.micro_precision == pytest.approx(1 / 3)
    assert metrics.micro_f1 == pytest.approx(0.5)
    assert safety.total == 0


def test_decoy_after_relevant_keeps_recall_and_mrr_correct_without_safety() -> None:
    scenario, expectation = _scenario("semantic_lexical_distractor_001")
    ranking = {
        scenario.scenario_id: (
            "cand_lexical_distractor_1",
            "cand_lexical_distractor_2",
            "cand_lexical_distractor_3",
        )
    }

    metrics = ranking_metrics(
        (scenario.scenario_id,),
        ranking,
        {scenario.scenario_id: expectation},
    )
    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=_active_runtime_facts(scenario),
        entered_candidate_ids=frozenset(ranking[scenario.scenario_id]),
    )

    assert metrics.recall_at_1 == metrics.recall_at_3 == metrics.mrr == 1.0
    assert safety.total == 0


def test_cross_player_result_is_a_runtime_safety_failure() -> None:
    scenario, _ = _scenario("semantic_player_isolation_001")
    facts = _active_runtime_facts(scenario)

    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=facts,
        entered_candidate_ids=frozenset({"cand_player_isolation_1"}),
    )

    assert safety.cross_player_recall == 1
    assert safety.total == 1


def test_current_episode_result_is_a_runtime_safety_failure() -> None:
    scenario, _ = _scenario("semantic_current_episode_exclusion_001")

    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=_active_runtime_facts(scenario),
        entered_candidate_ids=frozenset({"cand_current_episode_exclusion_1"}),
    )

    assert safety.current_episode_recall == 1


@pytest.mark.parametrize(
    "status",
    (
        SemanticCandidateRuntimeStatus.SUPERSEDED,
        SemanticCandidateRuntimeStatus.INVALIDATED,
    ),
)
def test_inactive_result_is_a_runtime_safety_failure(status) -> None:  # type: ignore[no-untyped-def]
    scenario, _ = _scenario("semantic_invalidation_001")
    facts = list(_active_runtime_facts(scenario))
    facts[0] = facts[0].model_copy(update={"status": status})

    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=tuple(facts),
        entered_candidate_ids=frozenset({facts[0].candidate_id}),
    )

    assert safety.inactive_memory_recall == 1


def test_hard_deleted_result_is_deletion_resurrection() -> None:
    scenario, _ = _scenario("semantic_hard_delete_001")
    facts = list(_active_runtime_facts(scenario))
    facts[0] = facts[0].model_copy(
        update={"status": SemanticCandidateRuntimeStatus.HARD_DELETED}
    )

    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=tuple(facts),
        entered_candidate_ids=frozenset({facts[0].candidate_id}),
    )

    assert safety.deletion_resurrection == 1


def test_semantic_negative_is_never_inferred_to_be_inactive() -> None:
    scenario, _ = _scenario("semantic_lexical_distractor_001")

    safety = runtime_safety_counts(
        scenario=scenario,
        runtime_facts=_active_runtime_facts(scenario),
        entered_candidate_ids=frozenset({"cand_lexical_distractor_2"}),
    )

    assert safety.inactive_memory_recall == 0
    assert safety.total == 0


def test_v2_contract_rejects_overlap_and_old_forbidden_field() -> None:
    payload = json.loads(DEFAULT_EXPECTATIONS_V2.read_text(encoding="utf-8"))
    payload["scenarios"][0]["semantic_negative_candidate_ids"].append(
        payload["scenarios"][0]["relevant_candidate_ids"][0]
    )
    with pytest.raises(ValidationError):
        SemanticGoldSuiteExpectationV2.model_validate(payload)

    payload = json.loads(DEFAULT_EXPECTATIONS_V2.read_text(encoding="utf-8"))
    payload["scenarios"][0]["forbidden_candidate_ids"] = []
    with pytest.raises(ValidationError):
        SemanticGoldSuiteExpectationV2.model_validate(payload)


def test_v2_partition_rejects_missing_candidate_and_incorrect_safety_reason() -> None:
    suite, expectations, _ = load_semantic_gold_v2()
    missing = expectations.model_copy(
        update={
            "scenarios": (
                expectations.scenarios[0].model_copy(
                    update={"semantic_negative_candidate_ids": ("cand_zh_synonym_2",)}
                ),
                *expectations.scenarios[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="cover all four"):
        validate_v2_partition_against_input(suite, missing)

    player_index = next(
        index
        for index, item in enumerate(expectations.scenarios)
        if item.scenario_id == "semantic_player_isolation_001"
    )
    player = expectations.scenarios[player_index]
    wrong_reason = player.model_copy(
        update={
            "safety_excluded_candidates": (
                player.safety_excluded_candidates[0].model_copy(
                    update={"reason": SafetyExclusionReason.CURRENT_EPISODE}
                ),
            )
        }
    )
    changed = list(expectations.scenarios)
    changed[player_index] = wrong_reason
    with pytest.raises(ValueError, match="does not match"):
        validate_v2_partition_against_input(
            suite,
            expectations.model_copy(update={"scenarios": tuple(changed)}),
        )


def test_gold_truth_remains_outside_inputs_queries_and_product_context() -> None:
    suite, _, _ = load_semantic_gold_v2()
    visible = DEFAULT_INPUT.read_text(encoding="utf-8") + "\n" + "\n".join(
        _query_text(scenario) for scenario in suite.scenarios
    )

    for field in (
        "relevant_candidate_ids",
        "semantic_negative_candidate_ids",
        "safety_excluded_candidates",
        "forbidden_candidate_ids",
        "expected_empty",
    ):
        assert field not in visible


def test_v2_manifest_keeps_model_threshold_split_and_sorting_identity() -> None:
    _, _, v2 = load_semantic_gold_v2()
    v1 = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    assert v2.preregistered_config.model_dump(mode="json") == v1[
        "preregistered_config"
    ]
    assert v2.preregistered_config_sha256 == v1["preregistered_config_sha256"]
    assert _sha256(DEFAULT_MANIFEST_V2) == (
        "4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61"
    )
