from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
README = REPO_ROOT / "README.md"


def test_readme_is_a_recruiter_homepage_in_the_frozen_order() -> None:
    text = README.read_text(encoding="utf-8")
    headings = (
        "# 玄医问道：可审计的师承型智能 NPC",
        "## Xuanyi: An Auditable Agentic Mentor NPC",
        "## 为什么值得看",
        "## 60 秒无 Key 启动",
        "## 安全架构",
        "## 三病例 Campaign",
        "## 真实本地演示",
        "## 两条阅读路径",
        "## 可复现证据",
        "## 诚实边界",
        "## 许可证与文档",
    )
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "P4b 未闭环" in text
    assert "5/5 行动修复" in text
    assert "语义记忆默认关闭" in text
    assert "Windows 10、CPython 3.12" in text
    assert "远程 CI" in text and "尚未" in text


def test_every_homepage_number_has_a_nearby_evidence_link() -> None:
    text = README.read_text(encoding="utf-8")
    required_linked_claims = (
        "| 3 个可玩病例 | [",
        "| 9 个冻结 MCP 工具 | [",
        "| 三案各 8 个连续事件",
        "| CampaignEvent 连续 1–3",
        "| M6-P1 基线 488 项离线测试 | [",
        "| M6-P2 当前 492 项离线测试 | [",
        "P4d 单次 5/5 行动契约修复，费用 `0.02345744 CNY` | [",
        "M4.5 排名 `Recall@3=1.00`，但返回门禁 `micro F1=0.6667`",
    )
    for claim in required_linked_claims:
        assert claim in text


def test_demo_assets_are_reproducible_and_private() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_portfolio_docs.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    asset_readme = (REPO_ROOT / "docs" / "assets" / "README.md").read_text(
        encoding="utf-8"
    )
    for transcript in sorted((REPO_ROOT / "docs" / "assets" / "transcripts").glob("*.txt")):
        digest = hashlib.sha256(transcript.read_bytes()).hexdigest().upper()
        assert digest in asset_readme


def test_old_detailed_readme_remains_available_as_technical_history() -> None:
    overview = (REPO_ROOT / "docs" / "TECHNICAL_OVERVIEW.md").read_text(
        encoding="utf-8"
    )
    assert "历史技术总览" in overview
    assert "当前状态" in overview
    assert "M2b-P1" in overview
    assert "M5-P0～P5" in overview
