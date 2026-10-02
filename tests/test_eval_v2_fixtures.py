from xuanyi_npc.evaluation.v2_contracts import GradeStatus
from xuanyi_npc.evaluation.v2_runner import fixture_artifact
from xuanyi_npc.evaluation.v2_scenarios import resolve_scenarios


def test_engineering_and_reflection_fixtures_are_distinct_from_real_trials():
    resolved, _ = resolve_scenarios()
    fixtures = [item for item in resolved["scenarios"] if item["suite"] in {"engineering", "reflection_quality"}]
    artifacts = [fixture_artifact(item, "offline_test") for item in fixtures]
    assert len(artifacts) == 18
    assert {item.artifact_kind.value for item in artifacts} == {"deterministic_fixture"}
    assert all(item.events[0].event_type == "run_started" and item.events[-1].event_type == "run_ended" for item in artifacts)


def test_unverified_engineering_capabilities_are_not_ready_not_silent_passes():
    resolved, _ = resolve_scenarios()
    by_id = {item["id"]: item for item in resolved["scenarios"]}
    concurrency = fixture_artifact(by_id["E06"], "offline_test")
    restart = fixture_artifact(by_id["E07"], "offline_test")
    assert concurrency.grades[0].status is GradeStatus.NOT_READY
    assert restart.grades[0].status is GradeStatus.NOT_READY


def test_synthetic_expected_events_are_scorer_tests_not_production_evidence():
    resolved, _ = resolve_scenarios()
    by_id = {item["id"]: item for item in resolved["scenarios"]}
    for scenario_id in ("E05", "E08", "E09", "E10", "E11", "E12", "R01", "R06"):
        artifact = fixture_artifact(by_id[scenario_id], "offline_test")
        assert artifact.status == "not_ready"
        assert artifact.grades[0].status is GradeStatus.NOT_READY
        assert artifact.terminal_snapshot["evidence_scope"] == "scorer_only_or_inventory"


def test_no_confirmation_and_mismatched_confirmation_are_blocked():
    resolved, _ = resolve_scenarios()
    by_id = {item["id"]: item for item in resolved["scenarios"]}
    for scenario_id in ("E01", "E02", "E03", "E04"):
        artifact = fixture_artifact(by_id[scenario_id], "offline_test")
        assert artifact.grades[0].status is GradeStatus.PASS
        assert artifact.terminal_snapshot["evidence_scope"] == "production_component_unit"
        assert not any(item.event_type == "world_committed" for item in artifact.events)
