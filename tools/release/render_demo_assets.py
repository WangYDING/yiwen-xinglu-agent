"""Render deterministic SVG terminal cards from committed, sanitized transcripts."""

from __future__ import annotations

import hashlib
import html
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "docs" / "portfolio" / "assets"
TRANSCRIPT_ROOT = ASSET_ROOT / "transcripts"
CARDS = (
    ("01_case_catalog.txt", "demo-01-case-catalog.svg", "01 · 三病例目录 / no-key"),
    ("02_campaign_continuity.txt", "demo-02-campaign-continuity.svg", "02 · 公开知识与跨案反应"),
    ("03_acceptance_summary.txt", "demo-03-acceptance-summary.svg", "03 · 离线验收摘要"),
)


def _render(source: Path, destination: Path, title: str) -> None:
    raw = source.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    source_sha = hashlib.sha256(raw).hexdigest().upper()
    width = 1160
    line_height = 27
    height = 112 + max(1, len(lines)) * line_height + 36
    text_lines = []
    for index, line in enumerate(lines):
        y = 104 + index * line_height
        text_lines.append(
            f'<text x="38" y="{y}" class="terminal">{html.escape(line)}</text>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(title)}</title>
  <desc id="desc">由项目真实离线终端输出的脱敏文本确定性生成。</desc>
  <metadata>source_sha256={source_sha}; copyright=2026 WangYDING</metadata>
  <rect width="100%" height="100%" rx="18" fill="#111827"/>
  <rect x="18" y="18" width="1124" height="48" rx="10" fill="#1f2937"/>
  <circle cx="43" cy="42" r="7" fill="#fb7185"/>
  <circle cx="67" cy="42" r="7" fill="#fbbf24"/>
  <circle cx="91" cy="42" r="7" fill="#34d399"/>
  <text x="116" y="49" class="title">{html.escape(title)}</text>
  <style>
    .title {{ fill: #e5e7eb; font: 600 18px ui-monospace, Consolas, monospace; }}
    .terminal {{ fill: #d1fae5; font: 17px ui-monospace, Consolas, monospace; }}
  </style>
  {''.join(text_lines)}
</svg>
'''
    destination.write_text(svg, encoding="utf-8", newline="\n")


def main() -> int:
    for source_name, destination_name, title in CARDS:
        _render(
            TRANSCRIPT_ROOT / source_name,
            ASSET_ROOT / destination_name,
            title,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
