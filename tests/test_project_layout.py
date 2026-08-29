from __future__ import annotations

import hashlib
import re
from pathlib import Path

from tools.release.audit_distribution import _is_forbidden


ROOT = Path(__file__).parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
MIGRATED_SHA256 = {
    "tools/experiments/data/evaluation/m45_semantic_gold_expectations.json": "ee68a03de2e4a3adbd6fd81d9f751a94f1f504e37cf7e33573a7fcb0ae79ef80",
    "tools/experiments/data/evaluation/m45_semantic_gold_expectations_v2.json": "2ce0c4ab316243b06be7a80a5b3617f26b06545a736202bd27ebf24490b9d8d0",
    "tools/experiments/data/evaluation/m45_semantic_gold_inputs.json": "ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d",
    "tools/experiments/data/evaluation/m45_semantic_gold_manifest.json": "9c17fbcc4f5f867ddcf40cf4ef056ab5299d65173595910d3312c97b4cccb9ef",
    "tools/experiments/data/evaluation/m45_semantic_gold_manifest_v2.json": "4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61",
    "tools/experiments/data/evaluation/m45_semantic_holdout_config_v1.json": "d119d075618744241bc54921fde007e9defb96fb83d38e8129104d3e6dd679f0",
    "tools/experiments/data/evaluation/m45_semantic_holdout_expectations_v1.json": "9caf5e4c7470f8f9c7bfbd29c0f8b60f1cc36558b19c98251e8bb0e03cbc8896",
    "tools/experiments/data/evaluation/m45_semantic_holdout_inputs_v1.json": "686508ead3ac174dcd949eca5e5051b5d137b50c796dba52f34bde26ce5141ea",
    "tools/experiments/data/evaluation/m45_semantic_holdout_manifest_v1.json": "44424fc212d382c98799b67ce0d70a222acd4cf0e0809ebc0b4c070fb7f653c8",
}


def test_first_time_reader_and_top_level_layout_are_explicit():
    start = (ROOT / "START_HERE.md").read_text(encoding="utf-8")
    assert "xuanyi-clinic" in start and "runtime_data" in start
    for relative in (
        "src", "tests", "docs/product", "docs/architecture",
        "docs/portfolio", "docs/evaluation", "docs/archive",
        "tools/release", "tools/experiments", "requirements",
    ):
        assert (ROOT / relative).is_dir()


def test_only_current_semantic_memory_evidence_is_retained():
    archive = ROOT / "docs" / "archive"
    assert (archive / "M45_HOLDOUT_VALIDATION_PLAN.md").is_file()
    assert (archive / "M45_REAL_MEMORY_VALIDATION_PLAN.md").is_file()
    assert not (archive / "M2_EXIT_AUDIT.md").exists()
    assert not (archive / "R6_REAL_MENTOR_PILOT_V2_RESULT.md").exists()


def test_all_committed_markdown_links_resolve_locally():
    markdown = [ROOT / "README.md", ROOT / "START_HERE.md", *sorted((ROOT / "docs").rglob("*.md"))]
    errors = []
    for path in markdown:
        for raw in LINK_PATTERN.findall(path.read_text(encoding="utf-8")):
            target = raw.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (path.parent / relative).resolve().exists():
                errors.append(f"{path.relative_to(ROOT)} -> {target}")
    assert errors == []


def test_installable_product_resources_remain_the_single_rule_source():
    resources = ROOT / "src" / "xuanyi_npc" / "resources"
    assert len(list((resources / "cases").glob("*.json"))) == 6
    assert not (ROOT / "data").exists()
    runtime_source = (resources / "runtime.py").read_text(encoding="utf-8")
    assert 'RESOURCE_PACKAGE = "xuanyi_npc.resources"' in runtime_source
    assert "from importlib.resources import files" in runtime_source


def test_product_runtime_does_not_load_experimental_or_archived_evidence_paths():
    package = ROOT / "src" / "xuanyi_npc"
    formal_runtime_roots = (
        "application", "cli", "clinic", "domain", "engine", "mcp_server",
        "resources", "storage",
    )
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for relative in formal_runtime_roots
        for path in (package / relative).rglob("*.py")
    )
    assert "tools/experiments/data" not in sources.replace("\\", "/")
    assert "docs/archive/evidence" not in sources.replace("\\", "/")


def test_experimental_data_and_archived_evidence_are_forbidden_from_distributions():
    assert _is_forbidden("xuanyi_npc-0.1.0/tools/experiments/data/evaluation/input.json")
    assert _is_forbidden("xuanyi_npc-0.1.0/docs/archive/evidence/model_runs/run.json")


def test_experimental_runners_have_an_explicit_non_product_boundary():
    experiments = ROOT / "tools" / "experiments"
    runners = experiments / "runners"
    assert not list(experiments.glob("*.py"))
    assert {path.name for path in experiments.iterdir() if path.is_dir()} == {
        "data",
        "model_manifests",
        "runners",
    }
    assert len(list(runners.glob("*.py"))) == 5

    runner_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in runners.glob("*.py")
    ).replace("\\", "/")
    assert '"tools" / "experiments" / "data"' in runner_sources
    assert '"tools" / "experiments" / "model_manifests"' not in runner_sources
    assert 'ROOT / "data"' not in runner_sources

    package_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "xuanyi_npc").rglob("*.py")
    ).replace("\\", "/")
    assert "tools.experiments" not in package_sources
    assert "tools/experiments/runners" not in package_sources

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert 'where = ["src"]' in pyproject
    assert "recursive-include tools" not in manifest


def test_migrated_data_bytes_keep_their_prefreeze_sha256():
    for relative, expected in MIGRATED_SHA256.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_machine_local_directories_remain_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in (".venv/", "runtime_models/", "runtime_data/", "results/"):
        assert entry in ignore
