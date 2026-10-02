from xuanyi_npc.evaluation.v2_scenarios import resolve_scenarios


def test_all_48_scenarios_resolve_and_all_six_cases_are_reachable():
    resolved, oracle = resolve_scenarios()
    assert len(resolved["scenarios"]) == 48
    assert len(resolved["cases"]) == 6
    assert resolved["preflight_passed"] is True
    assert all(item["reachable"] for item in resolved["cases"].values())
    assert set(oracle["cases"]) == set(resolved["cases"])


def test_wrong_hypotheses_are_frozen_public_distractors_not_truth_queries():
    resolved, oracle = resolve_scenarios()
    wrong = [item for item in resolved["scenarios"] if item.get("profile") == "wrong_hypothesis"]
    assert len(wrong) == 6
    for item in wrong:
        case = resolved["cases"][item["base_case_id"]]
        assert "{public_distractor_description}" not in item["stimulus"]
        assert case["public_distractor_id"] not in oracle["cases"][item["base_case_id"]]["valid_diagnosis_ids"]


def test_oracle_is_separate_from_public_resolved_scenarios():
    resolved, oracle = resolve_scenarios()
    encoded = str(resolved["scenarios"])
    for value in oracle["cases"].values():
        for diagnosis in value["valid_diagnosis_ids"]:
            # IDs may occur in private case metadata, but never in the public player script.
            assert all(diagnosis not in str(item.get("stimulus", "")) for item in resolved["scenarios"])

