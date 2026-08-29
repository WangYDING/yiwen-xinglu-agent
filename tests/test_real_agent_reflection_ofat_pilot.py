from pathlib import Path

import pytest

from xuanyi_npc.evaluation import real_agent_reflection_ofat_pilot as pilot


def test_paid_entry_requires_explicit_confirmation(tmp_path):
    with pytest.raises(SystemExit):
        pilot.main(["--output-root", str(tmp_path)])


def test_e12_config_identity_is_frozen():
    root = Path(__file__).parents[1]
    path = root / "tools/experiments/data/evaluation/cross_session_reflection_ofat_real_agent_pilot_v1.json"
    assert pilot.canonical_hash(path) == "06f5c0b27a60740cb09d7373539416480eff770801691ce67529db576d8b0d2e"
