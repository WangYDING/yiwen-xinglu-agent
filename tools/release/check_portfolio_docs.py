"""Offline link, provenance, SVG and privacy checks for the portfolio homepage."""

from __future__ import annotations

import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_MARKDOWN = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "INDEX.md",
    REPO_ROOT / "docs" / "archive" / "M5_DEMO_GUIDE.md",
    REPO_ROOT / "docs" / "portfolio" / "assets" / "README.md",
)
ASSET_HASHES = {
    "transcripts/01_case_catalog.txt": "81AFD803C94298FBDB02E89722BD8C3C597CF068EF49CC2E7E12E9FAB5DD36FC",
    "transcripts/02_campaign_continuity.txt": "09A6ABE61926E762E0B11667021B361A209E6050D6E17B264D2C5F874F106F59",
    "transcripts/03_acceptance_summary.txt": "70184C1487266F3497E1DB728B1CFBC72EC0F400165293A095DD04C40D24259D",
    "demo-01-case-catalog.svg": "BD2CA006CEB1E1F6E0C2F068E5D5083C444A0A26C7478E8047A9E64F27946A3E",
    "demo-02-campaign-continuity.svg": "6F55D2D050CE33476B271C40501A6221DA1AA7B426B0F5F84BE9BE864BE7690E",
    "demo-03-acceptance-summary.svg": "8DBBC41E1FE045E8F5EB1BFEF8170A9B6012E5F58F26E7DCE62AC63C5FDBB729",
}
FORBIDDEN_ASSET_PATTERNS = (
    re.compile(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\", re.IGNORECASE),
    re.compile(r"DEEPSEEK_API_KEY", re.IGNORECASE),
    re.compile(r"Authorization\s*:", re.IGNORECASE),
    re.compile(r"provider_request_id", re.IGNORECASE),
    re.compile(r"root_cause", re.IGNORECASE),
    re.compile(r"valid_diagnosis_ids", re.IGNORECASE),
    re.compile(r"diagnosis_correct", re.IGNORECASE),
)
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _local_link_errors(markdown_path: Path) -> list[str]:
    errors: list[str] = []
    text = markdown_path.read_text(encoding="utf-8")
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        relative_path = target.split("#", 1)[0]
        if not relative_path:
            continue
        resolved = (markdown_path.parent / relative_path).resolve()
        if not resolved.is_relative_to(REPO_ROOT):
            errors.append(f"{markdown_path}: link escapes repository: {target}")
        elif not resolved.exists():
            errors.append(f"{markdown_path}: missing local target: {target}")
    return errors


def run_checks() -> list[str]:
    errors: list[str] = []
    asset_root = REPO_ROOT / "docs" / "portfolio" / "assets"
    for markdown_path in CHECKED_MARKDOWN:
        errors.extend(_local_link_errors(markdown_path))

    for relative_path, expected in ASSET_HASHES.items():
        path = asset_root / relative_path
        if not path.is_file():
            errors.append(f"missing provenance asset: {relative_path}")
        elif _sha256(path) != expected:
            errors.append(f"asset hash mismatch: {relative_path}")

    for svg_path in sorted(asset_root.glob("*.svg")):
        try:
            ET.parse(svg_path)
        except ET.ParseError as exc:
            errors.append(f"invalid SVG XML: {svg_path.name}: {exc}")

    for path in sorted(asset_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".svg"}:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_ASSET_PATTERNS:
            if pattern.search(text):
                errors.append(f"privacy sentinel found in {path.relative_to(REPO_ROOT)}")

    return errors


def main() -> int:
    errors = run_checks()
    if errors:
        print("作品集文档检查失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("作品集文档检查：本地链接、素材哈希、SVG 与隐私哨兵全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
