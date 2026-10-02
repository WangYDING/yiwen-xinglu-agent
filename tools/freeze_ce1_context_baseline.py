"""Freeze a versioned, independently rebuildable current-worktree baseline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "context_engineering"
ALLOWED_SUFFIXES = {".py", ".json", ".css", ".js", ".toml", ".txt"}


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _copy_snapshot(destination: Path) -> None:
    # Importing xuanyi_npc.application executes its eager package exports, so
    # the reproducible import closure is the package source rather than three
    # apparently direct modules.  Runtime data outside this package is omitted.
    package = ROOT / "src" / "xuanyi_npc"
    for source in sorted(package.rglob("*")):
        if (
            not source.is_file()
            or source.suffix.lower() not in ALLOWED_SUFFIXES
            or "__pycache__" in source.parts
        ):
            continue
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative in (Path("tests/context_baseline_support.py"), Path("pyproject.toml")):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    for source in sorted(ROOT.glob("requirements*.txt")):
        shutil.copy2(source, destination / source.name)
    shutil.copy2(ROOT / "tools" / "context_request_rebuild.py", destination / "rebuild_requests.py")


def _run_rebuild(snapshot: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(snapshot / "src"), str(snapshot))
    )
    completed = subprocess.run(
        [sys.executable, str(snapshot / "rebuild_requests.py")],
        cwd=snapshot,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(completed.stdout)


def freeze(baseline_id: str) -> Path:
    if re.fullmatch(r"[a-z0-9][a-z0-9_]{2,63}", baseline_id) is None:
        raise SystemExit("baseline_id must contain 3-64 lowercase letters, digits, or underscores")
    destination = FIXTURE_ROOT / baseline_id
    if destination.exists():
        raise SystemExit(
            f"REFUSE_OVERWRITE: frozen baseline already exists: {destination}"
        )
    destination.mkdir(parents=True)
    snapshot = destination / "snapshot"
    (snapshot / "tests").mkdir(parents=True)
    _copy_snapshot(snapshot)

    status = subprocess.check_output(
        ["git", "status", "--short", "--branch", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    )
    (destination / "workspace_status.txt").write_text(
        status, encoding="utf-8", newline="\n"
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    packages = {}
    for name in ("pydantic", "httpx", "python-dotenv", "pytest", "pytest-asyncio"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    _write_json(
        destination / "environment.json",
        {
            "baseline_id": baseline_id,
            "classification": (
                "current-worktree pre-change request baseline; not a pre-refactor CE-0 baseline"
            ),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": head,
            "python": {
                "implementation": sys.implementation.name,
                "version": sys.version,
            },
            "packages": packages,
            "rebuild_entrypoint": "snapshot/rebuild_requests.py",
            "exclusions": (
                "credentials",
                "private runtime data",
                "model output archives",
                "unrelated workspace files",
            ),
        },
    )

    built = _run_rebuild(snapshot)
    _write_json(destination / "requests.json", built["requests"])
    _write_json(destination / "provider_payloads.json", built["provider_payloads"])
    if _run_rebuild(snapshot) != built:
        raise SystemExit("SNAPSHOT_REBUILD_MISMATCH")
    _write_json(
        destination / "rebuild_verification.json",
        {
            "working_directory": "snapshot",
            "result": "exact_structural_match",
            "request_count": len(built["requests"]),
            "provider_payload_count": len(built["provider_payloads"]),
        },
    )

    hashes = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name not in {"manifest.json", "sha256s.json"}:
            hashes[path.relative_to(destination).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    _write_json(destination / "sha256s.json", hashes)
    _write_json(
        destination / "manifest.json",
        {
            "baseline_id": baseline_id,
            "git_head": head,
            "immutable": True,
            "not_ce0_claim": (
                "This baseline is not claimed to predate CE-0/CE-1 refactoring."
            ),
            "requests_sha256": hashlib.sha256(
                (destination / "requests.json").read_bytes()
            ).hexdigest(),
            "provider_payloads_sha256": hashlib.sha256(
                (destination / "provider_payloads.json").read_bytes()
            ).hexdigest(),
            "workspace_status_sha256": hashlib.sha256(
                (destination / "workspace_status.txt").read_bytes()
            ).hexdigest(),
            "sha256_manifest": "sha256s.json",
            "rebuild_verification": "rebuild_verification.json",
        },
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_id")
    args = parser.parse_args()
    print(freeze(args.baseline_id))


if __name__ == "__main__":
    main()
