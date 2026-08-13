from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
README = REPO_ROOT / "README.md"


def test_readme_presents_the_current_mentor_product_in_order() -> None:
    text = README.read_text(encoding="utf-8")
    headings = (
        "# 玄医问道：可审计的师承型智能 NPC",
        "## Xuanyi: An Auditable Agentic Mentor NPC",
        "## 为什么值得看",
        "## 60 秒无 Key 启动",
        "## 安全架构",
        "## 六病例教学与成长",
        "## 真实本地演示",
        "## 当前阅读路径",
        "## 可复现证据",
        "## 诚实边界",
        "## 许可证与文档",
    )
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "six-case game-AI product" in text
    assert "MentorAgent" in text
    assert "DoctorAgent" in text and "历史" in text
    assert "语义记忆" in text and "默认关闭" in text
    assert "Windows 10、CPython 3.12" in text
    assert "公共 CI" in text and "尚未" in text


def test_current_product_claims_have_evidence_links() -> None:
    text = README.read_text(encoding="utf-8")
    required_linked_claims = (
        "| 6 个可玩病例与本地医馆 | [",
        "| 玩家行动与独立 MentorAgent 教学边界 | [",
        "| 确定性成长、课程与结构化导师记忆 | [",
        "| R4 正式考试、权限过滤、两进程恢复与单传承链 | [",
        "| R6 八路线离线验收通过；真实导师与真人试玩未执行 | [",
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
