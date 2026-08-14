from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def test_first_time_reader_and_top_level_layout_are_explicit():
    start = (ROOT / "START_HERE.md").read_text(encoding="utf-8")
    assert "xuanyi-clinic" in start and "runtime_data" in start
    for relative in (
        "src", "tests", "data", "docs/product", "docs/architecture",
        "docs/portfolio", "docs/evaluation", "docs/archive",
        "tools/release", "tools/experiments", "requirements",
    ):
        assert (ROOT / relative).is_dir()


def test_historical_evidence_was_archived_not_dropped():
    archive = ROOT / "docs" / "archive"
    for name in (
        "M2_EXIT_AUDIT.md", "M3_EXIT_AUDIT.md", "M4_EXIT_AUDIT.md",
        "M45_TERMINATION_AUDIT.md", "M5_EXIT_AUDIT.md",
        "M6_RELEASE_READINESS_AUDIT.md", "R6_REAL_MENTOR_PILOT_V2_RESULT.md",
    ):
        assert (archive / name).is_file()


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
    explanation = (ROOT / "data" / "README.md").read_text(encoding="utf-8")
    assert "唯一权威真源" in explanation and "wheel" in explanation


def test_machine_local_directories_remain_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in (".venv/", "runtime_models/", "runtime_data/", "results/"):
        assert entry in ignore
