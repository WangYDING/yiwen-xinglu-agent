from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from xuanyi_npc.application import CampaignRuleSet, CaseCatalog
from xuanyi_npc.resources.runtime import (
    CASE_RESOURCE_NAMES,
    PackageResourceError,
    materialized_runtime_resources,
    read_runtime_text,
)


ROOT = Path(__file__).parents[1]
PACKAGE_RESOURCES = ROOT / "src" / "xuanyi_npc" / "resources"


def test_packaged_runtime_resources_load_the_three_cases_and_campaign() -> None:
    with materialized_runtime_resources() as paths:
        catalog = CaseCatalog(paths.case_dir)
        assert catalog.case_ids() == (
            "gray_hearth_inn",
            "moon_well_echo",
            "old_paper_umbrella",
        )
        rules = CampaignRuleSet.load(paths.campaign_rules, catalog)
        assert rules.config.rules_version == "cross_episode_rules_v1"


def test_runtime_resource_allowlist_rejects_experiments_and_traversal() -> None:
    for path in (
        "evaluation/m45_semantic_gold_inputs.json",
        "../data/cases/old_paper_umbrella.json",
        "cases/unknown.json",
    ):
        with pytest.raises(PackageResourceError):
            read_runtime_text(path)


def test_package_resource_tree_is_the_single_runtime_authority() -> None:
    assert not (ROOT / "data").exists()
    assert tuple(sorted(path.name for path in (PACKAGE_RESOURCES / "cases").glob("*.json"))) == tuple(
        sorted(CASE_RESOURCE_NAMES)
    )
    packaged_files = {
        path.relative_to(PACKAGE_RESOURCES).as_posix()
        for path in PACKAGE_RESOURCES.rglob("*")
        if path.is_file()
    }
    assert not any(path.startswith("evaluation/") for path in packaged_files)
    assert not any(path.endswith((".safetensors", ".pt", ".db", ".sqlite")) for path in packaged_files)


def test_importing_resource_module_has_no_filesystem_or_model_side_effect(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import xuanyi_npc.resources.runtime; "
                "assert 'torch' not in sys.modules; "
                "assert 'sentence_transformers' not in sys.modules"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert tuple(tmp_path.iterdir()) == ()
