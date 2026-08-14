"""Audit built archives for required package data and forbidden release files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


REQUIRED_RESOURCES = {
    "xuanyi_npc/resources/campaign/cross_episode_rules_v1.json",
    "xuanyi_npc/resources/cases/gray_hearth_inn.json",
    "xuanyi_npc/resources/cases/moon_well_echo.json",
    "xuanyi_npc/resources/cases/old_paper_umbrella.json",
    "xuanyi_npc/resources/pilot/deepseek_v4_flash_pilot_policy_2026-08-07.json",
    "xuanyi_npc/resources/release/m5_history_evidence_v1.json",
}
REQUIRED_LICENSE_FILES = {
    "CONTENT_RIGHTS.md",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
}
FORBIDDEN_PARTS = {
    ".env",
    ".git",
    ".venv",
    "__pycache__",
    "results",
    "runtime_data",
    "runtime_models",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".npy",
    ".npz",
    ".onnx",
    ".pickle",
    ".pt",
    ".pth",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
}
PRIVATE_PATH_PATTERNS = (
    re.compile(rb"[A-Za-z]:\\\\Users\\\\[^\\\\\r\n]+"),
    re.compile(rb"[A-Za-z]:\\\\[^\r\n]+"),
    re.compile(rb"/(?:home|Users)/[^/\r\n]+/"),
)


class DistributionAuditError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _is_forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    lowered = {part.lower() for part in path.parts}
    if lowered & FORBIDDEN_PARTS:
        return True
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    return "data/evaluation/" in name.lower()


def _audit_names(names: list[str]) -> None:
    forbidden = sorted(name for name in names if _is_forbidden(name))
    if forbidden:
        raise DistributionAuditError(f"forbidden archive members: {forbidden}")


def _wheel_resources(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _audit_names(names)
        license_names = {
            PurePosixPath(name).name
            for name in names
            if ".dist-info/licenses/" in name
        }
        if license_names != REQUIRED_LICENSE_FILES:
            raise DistributionAuditError("wheel license boundary is incomplete")
        missing = sorted(REQUIRED_RESOURCES - set(names))
        if missing:
            raise DistributionAuditError(f"wheel resources missing: {missing}")
        for name in names:
            if name.endswith((".py", ".json", ".md", ".txt")):
                payload = archive.read(name)
                if any(pattern.search(payload) for pattern in PRIVATE_PATH_PATTERNS):
                    raise DistributionAuditError(f"private path in wheel member: {name}")
        return {name: archive.read(name) for name in REQUIRED_RESOURCES}


def _sdist_resources(path: Path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        names = [member.name for member in members]
        _audit_names(names)
        resources: dict[str, bytes] = {}
        for required in REQUIRED_RESOURCES:
            matches = [name for name in names if name.endswith(f"/src/{required}")]
            if len(matches) != 1:
                raise DistributionAuditError(f"sdist resource identity invalid: {required}")
            handle = archive.extractfile(matches[0])
            if handle is None:
                raise DistributionAuditError(f"sdist resource unreadable: {required}")
            resources[required] = handle.read()
        for member in members:
            if member.name.endswith((".py", ".json", ".md", ".txt")):
                handle = archive.extractfile(member)
                payload = handle.read() if handle is not None else b""
                if any(pattern.search(payload) for pattern in PRIVATE_PATH_PATTERNS):
                    raise DistributionAuditError(f"private path in sdist member: {member.name}")
        return resources


def audit(dist_dir: Path) -> dict[str, object]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise DistributionAuditError("expected exactly one wheel and one sdist")
    wheel_resources = _wheel_resources(wheels[0])
    sdist_resources = _sdist_resources(sdists[0])
    if wheel_resources != sdist_resources:
        raise DistributionAuditError("wheel and sdist runtime resources differ")
    return {
        "status": "passed",
        "wheel": {
            "name": wheels[0].name,
            "sha256": _sha256(wheels[0]),
            "size_bytes": wheels[0].stat().st_size,
        },
        "sdist": {
            "name": sdists[0].name,
            "sha256": _sha256(sdists[0]),
            "size_bytes": sdists[0].stat().st_size,
        },
        "required_resources": sorted(REQUIRED_RESOURCES),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.dist_dir.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
