import json
from pathlib import Path

from xuanyi_npc.evaluation.reflection_ofat import load_condition, run_condition
from xuanyi_npc.resources.runtime import materialized_clinic_resources


ROOT = Path(__file__).parents[1]
DATA = ROOT / "tools/experiments/data/evaluation"
CONTROL = DATA / "cross_session_reflection_ofat_control_v1.json"
ABLATION = DATA / "cross_session_reflection_ofat_ablation_v1.json"


def _pair(tmp_path):
    with materialized_clinic_resources() as resources:
        control = run_condition(
            condition_path=CONTROL, state_dir=tmp_path / "control", resources=resources
        )
        ablation = run_condition(
            condition_path=ABLATION, state_dir=tmp_path / "ablation", resources=resources
        )
    return control, ablation


def test_control_triggers_generates_persists_writes_and_indexes(tmp_path):
    control, _ = _pair(tmp_path)
    assert control.reflection_trigger_count == 1
    assert control.reflection_generation_count == 1
    assert control.reflection_write_count == 1
    assert control.reflection_receipt_persisted is True
    assert control.reflection_indexed_count == 1


def test_control_later_session_retrieves_and_selects_derived_memory(tmp_path):
    control, _ = _pair(tmp_path)
    assert control.session_a_episode_id != control.session_b_episode_id
    assert control.reflection_derived_candidate_ids == control.reflection_derived_memory_ids
    assert control.reflection_derived_selected_ids == control.reflection_derived_memory_ids
    assert control.current_session_leakage is False


def test_ablation_has_boundary_but_zero_reflection_activity(tmp_path):
    _, ablation = _pair(tmp_path)
    assert ablation.reflection_trigger_count == 1
    assert ablation.reflection_generation_count == 0
    assert ablation.reflection_write_count == 0
    assert ablation.reflection_derived_memory_ids == ()
    assert ablation.reflection_derived_candidate_ids == ()
    assert ablation.reflection_receipt_persisted is False


def test_ablation_retains_ordinary_semantic_memory(tmp_path):
    _, ablation = _pair(tmp_path)
    assert ablation.memory_mode == "semantic"
    assert ablation.memory_ordinary_write_count > 0
    assert ablation.ordinary_candidate_ids
    assert set(ablation.ordinary_candidate_ids).intersection(ablation.selected_ids)


def test_conditions_are_matched_except_reflection_identity(tmp_path):
    control_config = load_condition(CONTROL)
    ablation_config = load_condition(ABLATION)
    left = control_config.model_dump(exclude={"condition", "reflection_mode"})
    right = ablation_config.model_dump(exclude={"condition", "reflection_mode"})
    assert left == right
    control, ablation = _pair(tmp_path)
    assert control.ordinary_memory_ids == ablation.ordinary_memory_ids
    assert control.session_a_episode_id == ablation.session_a_episode_id
    assert control.session_b_episode_id == ablation.session_b_episode_id
    assert control.configuration_hash != ablation.configuration_hash
    assert control.manifest_hash != ablation.manifest_hash


def test_isolation_safety_and_efficiency_placeholders(tmp_path):
    control, ablation = _pair(tmp_path)
    for result in (control, ablation):
        assert result.player_isolation_violation is False
        assert result.repository_leakage is False
        assert result.current_session_leakage is False
        assert result.authority_violations == 0
        assert result.infrastructure_failures == 0
        assert result.provider_requests == result.input_tokens == result.output_tokens == 0
        assert result.estimated_cost_cny == 0.0
        assert result.duration_seconds > 0


def test_condition_hashes_are_frozen_and_distinct():
    from xuanyi_npc.evaluation.cross_session_memory_exposure import canonical_hash
    assert canonical_hash(CONTROL) == "ef6ba3a0fc0f27804bb2e8a9926ad2ca647a524a2b4b38e3324fdea7a0fc0975"
    assert canonical_hash(ABLATION) == "7ea06d7a4fab1aa8c286beb240d534af0ffd44251e7bf774c61263cfe135f801"


def test_e6_identity_and_formal_cases_are_unchanged():
    frozen = json.loads((DATA / "agent_task_benchmark_v1.json").read_text(encoding="utf-8"))
    assert frozen["case_ids"] == [
        "old_paper_umbrella", "gray_hearth_inn", "lantern_alley_conflicting_testimony"
    ]
    assert frozen["memory_mode"] == "semantic"
    assert frozen["reflection_mode"] == "enabled"
