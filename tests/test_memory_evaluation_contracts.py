from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.evaluation.memory_contracts import (
    REQUIRED_MEMORY_GOLD_SCENARIOS,
    MemoryGoldManifest,
    MemoryGoldSuiteExpectation,
    MemoryGoldSuiteInput,
)
from xuanyi_npc.memory.canonical import sha256_hex


DATA_DIR = Path(__file__).parents[1] / "data" / "evaluation"
INPUT_PATH = DATA_DIR / "memory_gold_inputs.json"
EXPECTATION_PATH = DATA_DIR / "memory_gold_expectations.json"
MANIFEST_PATH = DATA_DIR / "memory_gold_manifest.json"


def load_frozen_gold() -> tuple[
    MemoryGoldSuiteInput,
    MemoryGoldSuiteExpectation,
    MemoryGoldManifest,
]:
    return (
        MemoryGoldSuiteInput.model_validate_json(INPUT_PATH.read_text(encoding="utf-8")),
        MemoryGoldSuiteExpectation.model_validate_json(
            EXPECTATION_PATH.read_text(encoding="utf-8")
        ),
        MemoryGoldManifest.model_validate_json(
            MANIFEST_PATH.read_text(encoding="utf-8")
        ),
    )


def test_frozen_memory_gold_has_exact_scenarios_and_separate_expectations() -> None:
    suite, expectations, manifest = load_frozen_gold()

    assert tuple(item.scenario_id for item in suite.scenarios) == (
        REQUIRED_MEMORY_GOLD_SCENARIOS
    )
    assert tuple(item.scenario_id for item in expectations.scenarios) == (
        REQUIRED_MEMORY_GOLD_SCENARIOS
    )
    assert len(suite.players) >= 2
    assert manifest.suite_id == suite.suite_id == expectations.suite_id
    assert "expected_memory_ids" not in INPUT_PATH.read_text(encoding="utf-8")
    assert "current_user_message" not in EXPECTATION_PATH.read_text(encoding="utf-8")
    assert "memory_placeholder" not in EXPECTATION_PATH.read_text(encoding="utf-8")


def test_frozen_memory_gold_manifest_hashes_input_gold_and_config() -> None:
    suite, _, manifest = load_frozen_gold()

    assert manifest.scenario_input_sha256 == hashlib.sha256(
        INPUT_PATH.read_bytes()
    ).hexdigest()
    assert manifest.gold_expectation_sha256 == hashlib.sha256(
        EXPECTATION_PATH.read_bytes()
    ).hexdigest()
    assert manifest.retrieval_config_sha256 == sha256_hex(suite.retrieval_configs)


def test_memory_gold_contracts_reject_unknown_fields() -> None:
    raw = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    raw["unexpected"] = "not allowed"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        MemoryGoldSuiteInput.model_validate(raw)

    raw = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    raw["scenarios"][0]["query"]["gold_answer"] = "must stay separate"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        MemoryGoldSuiteInput.model_validate(raw)


def test_current_episode_and_cross_player_traps_are_explicitly_frozen() -> None:
    suite, expectations, _ = load_frozen_gold()
    relevant = suite.scenarios[0]
    isolation = suite.scenarios[2]

    assert "source_current_episode" in relevant.source_refs
    assert (
        suite.sources["source_current_episode"].source_session_id
        == relevant.current_session_id
    )
    assert "source_player_b_bait" in isolation.source_refs
    assert suite.sources["source_player_b_bait"].player_id != isolation.player_id
    assert expectations.scenarios[0].forbidden_memory_ids
    assert expectations.scenarios[2].forbidden_memory_ids
