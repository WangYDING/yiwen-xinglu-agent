"""Resolve and preflight the 48 V2 scenario specifications without a provider."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.evaluation.v2_contracts import V2Scenario


ROOT = Path(__file__).resolve().parents[3]
DESIGN_ROOT = ROOT / "docs" / "evaluation" / "v2_design"
CATALOG_PATH = DESIGN_ROOT / "scenario_catalog.json"
CASE_ROOT = ROOT / "src" / "xuanyi_npc" / "resources" / "cases"
CAMPAIGN_PATH = ROOT / "src" / "xuanyi_npc" / "resources" / "campaign" / "cross_episode_rules_v2.json"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return sha256(payload).hexdigest()


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reachable_investigations(case, skills: dict[str, int]) -> tuple[str, ...]:
    discovered: set[str] = set()
    executed: set[str] = set()
    changed = True
    while changed:
        changed = False
        for item in case.investigations:
            if item.investigation_id in executed:
                continue
            level = skills.get(item.required_skill_id, skills.get("inspect_evidence", -1) if item.required_skill_id == "inspect_object" else -1)
            if level < item.minimum_skill_level or not set(item.required_clue_ids).issubset(discovered):
                continue
            executed.add(item.investigation_id)
            discovered.update(item.reveals_clue_ids)
            changed = True
    return tuple(sorted(executed)), tuple(sorted(discovered))


def resolve_scenarios(path: Path = CATALOG_PATH) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = load_catalog(path)
    catalog = CaseCatalog(CASE_ROOT)
    skills = {
        "observe_form": 100, "ask_cause": 100, "inspect_evidence": 100,
        "inspect_object": 100, "observe_qi": 100, "reason_diagnosis": 100,
        "apply_treatment": 100, "ethical_practice": 100,
    }
    cases: dict[str, Any] = {}
    oracle: dict[str, Any] = {}
    for case_id in raw["case_catalog"]:
        case = catalog.get(case_id)
        investigations, clues = _reachable_investigations(case, skills)
        valid_treatments = tuple(sorted(
            item.treatment_id for item in case.treatments.values()
            if item.outcome.value == "resolved" and set(item.required_clue_ids).issubset(clues)
        ))
        reachable = bool(valid_treatments and case.valid_diagnosis_ids)
        resource_path = CASE_ROOT / f"{case_id}.json"
        diagnoses = tuple(sorted(case.diagnosis_candidates))
        distractor = next(item for item in diagnoses if item not in case.valid_diagnosis_ids)
        cases[case_id] = {
            "case_id": case_id,
            "resource_hash": sha256(resource_path.read_bytes()).hexdigest(),
            "campaign_hash": sha256(CAMPAIGN_PATH.read_bytes()).hexdigest(),
            "skill_profile": skills,
            "reachable_investigation_ids": investigations,
            "reachable_clue_ids": clues,
            "reachable": reachable,
            "public_distractor_id": distractor,
            "public_distractor_description": case.diagnosis_candidates[distractor].public_description,
        }
        oracle[case_id] = {
            "valid_diagnosis_ids": tuple(case.valid_diagnosis_ids),
            "resolved_treatment_ids": valid_treatments,
        }
    scenarios = []
    for item in raw["scenarios"]:
        scenario = V2Scenario.model_validate(item)
        value = scenario.model_dump(mode="json")
        if scenario.base_case_id:
            case = cases[scenario.base_case_id]
            value["fixture_status"] = "preflight_passed" if case["reachable"] else "preflight_failed"
            value["fixture_hash"] = digest(case)
            if scenario.profile == "wrong_hypothesis":
                value["stimulus"] = str(value["stimulus"]).replace(
                    "{public_distractor_description}", case["public_distractor_description"]
                )
        else:
            value["fixture_status"] = "frozen_fixture_spec"
            value["fixture_hash"] = digest({"id": scenario.id, "stimulus": scenario.stimulus, "expected": scenario.expected})
        scenarios.append(value)
    resolved = {
        "schema_version": "evaluation_v2_scenarios_v1",
        "source_catalog_hash": sha256(path.read_bytes()).hexdigest(),
        "campaign_hash": sha256(CAMPAIGN_PATH.read_bytes()).hexdigest(),
        "cases": cases,
        "scenarios": scenarios,
        "preflight_passed": all(item["reachable"] for item in cases.values()),
    }
    return resolved, {"schema_version": "evaluation_v2_oracle_v1", "cases": oracle}

