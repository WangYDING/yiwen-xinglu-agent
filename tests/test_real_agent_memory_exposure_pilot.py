from pathlib import Path

import pytest

from xuanyi_npc.evaluation import real_agent_memory_exposure_pilot as pilot


def test_paid_entry_requires_confirmation(tmp_path):
    with pytest.raises(SystemExit):
        pilot.main(["--output-root", str(tmp_path)])


def test_pilot_identity_and_budget_are_frozen():
    root = Path(__file__).parents[1]
    config = root / "tools/experiments/data/evaluation/cross_session_memory_exposure_real_agent_pilot_v1.json"
    assert pilot.canonical_hash(config) == "6d61c108bc1b6cfcceedebdec2a1acd50da4474e2f77b2fec785e6048568e73e"
