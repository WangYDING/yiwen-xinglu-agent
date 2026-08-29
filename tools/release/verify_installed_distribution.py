"""Verify a clean installed wheel without using repository source imports."""

from __future__ import annotations

import shutil
import subprocess
import sys

from xuanyi_npc.application import CaseCatalog
from xuanyi_npc.resources.runtime import materialized_clinic_resources


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


def main() -> int:
    with materialized_clinic_resources() as resources:
        if len(CaseCatalog(resources.case_dir).case_ids()) != 6:
            raise RuntimeError("installed package does not contain six cases")

    for command in ("yiwen-xinglu", "xuanyi-clinic", "xuanyi-mcp-stdio"):
        executable = shutil.which(command)
        if executable is None:
            raise RuntimeError(f"installed command is missing: {command}")
        _run([executable, "--help"])

    print("installed distribution verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
