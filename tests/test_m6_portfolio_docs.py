from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
README = REPO_ROOT / "README.md"


def test_readme_presents_current_cooperative_product_in_order() -> None:
    text = README.read_text(encoding="utf-8")
    headings = (
        "# 玄医问道：Human-Agent Cooperative Game NPC System",
        "## Human-Agent Cooperation",
        "## Planning, Memory and Reflection",
        "## Evaluation",
        "### Real LLM Validation",
        "## Evolution and Retained Baselines",
        "## Limitations",
    )
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "`GameNPCAgent` | Current cooperative main Agent" in text
    assert "`MentorAgent` | Retained teaching / presentation branch" in text
    assert "`DoctorAgent` | V0 baseline / legacy benchmark Agent" in text
    assert text.index("GameNPCAgent proposal") < text.index("MentorAgent` | Retained")
    assert "# 玄医问道：可审计的师承型智能 NPC" not in text
    assert "Xuanyi: An Auditable Agentic Mentor NPC" not in text


def test_current_product_claims_have_evidence_links() -> None:
    text = README.read_text(encoding="utf-8")
    benchmark_target = "docs/benchmarks/m5/agent_benchmark_report.md"
    assert f"]({benchmark_target})" in text
    assert (REPO_ROOT / benchmark_target).is_file()
    assert "M5 在冻结的同条件 fixtures 上完成 5 个 paired experiments" in text
    assert "post-fix small real-model pilot 共 9 runs" in text
    assert "不代表生产分布成功率或玩家收益" in text

    assert "`MentorAgent` | Retained teaching / presentation branch" in text
    assert "[文档导航](docs/INDEX.md)" in text
    assert "[历史归档](docs/archive/README.md)" in text
    assert (REPO_ROOT / "docs" / "INDEX.md").is_file()
    assert (REPO_ROOT / "docs" / "archive" / "README.md").is_file()
    assert text.index(f"]({benchmark_target})") < text.index("`MentorAgent` | Retained")


def test_demo_assets_are_reproducible_and_private() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/release/check_portfolio_docs.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    asset_readme = (REPO_ROOT / "docs" / "portfolio" / "assets" / "README.md").read_text(
        encoding="utf-8"
    )
    for transcript in sorted((REPO_ROOT / "docs" / "portfolio" / "assets" / "transcripts").glob("*.txt")):
        digest = hashlib.sha256(transcript.read_bytes()).hexdigest().upper()
        assert digest in asset_readme


def test_old_detailed_readme_remains_available_as_technical_history() -> None:
    overview = (REPO_ROOT / "docs" / "architecture" / "TECHNICAL_OVERVIEW.md").read_text(
        encoding="utf-8"
    )
    assert "历史技术总览" in overview
    assert "当前状态" in overview
    assert "M2b-P1" in overview
    assert "M5-P0～P5" in overview
