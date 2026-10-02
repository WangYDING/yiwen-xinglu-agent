"""Create a new CE-2A request-identity fixture; never overwrite a version."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="new filename stem, for example ce2a_requests_v2")
    args = parser.parse_args()
    target = (
        Path(__file__).parents[1]
        / "tests" / "fixtures" / "context_engineering" / f"{args.version}.json"
    )
    if target.exists():
        parser.error(f"REFUSE_OVERWRITE: {target}")
    parser.error(
        "Generation is intentionally review-gated. Copy the deterministic builder "
        "from test_context_engineering_ce2a.py, review its public snapshot, then add "
        "the new version with apply_patch. Existing versions are immutable."
    )


if __name__ == "__main__":
    raise SystemExit(main())
