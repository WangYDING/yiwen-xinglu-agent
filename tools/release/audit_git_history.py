"""Offline secret and forbidden-artifact scan over every Git history blob."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import PurePosixPath


SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "authorization_bearer": re.compile(rb"Authorization\s*[:=]\s*Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    "deepseek_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
}
FORBIDDEN_PATH_PARTS = {
    ".env",
    ".venv",
    "results",
    "runtime_data",
    "runtime_models",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
}


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments], capture_output=True, check=True
    ).stdout


def _history_objects() -> tuple[tuple[str, str], ...]:
    objects: list[tuple[str, str]] = []
    for line in _git("rev-list", "--objects", "--all").decode("utf-8").splitlines():
        object_id, separator, path = line.partition(" ")
        if separator and path:
            objects.append((object_id, path))
    return tuple(objects)


def audit() -> dict[str, object]:
    objects = _history_objects()
    secret_hits: list[dict[str, str]] = []
    forbidden_history_paths: set[str] = set()
    max_blob_bytes = 0
    scanned_blobs = 0
    for object_id, name in objects:
        path = PurePosixPath(name)
        lowered = {part.lower() for part in path.parts}
        if lowered & FORBIDDEN_PATH_PARTS or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            forbidden_history_paths.add(name)
        object_type = _git("cat-file", "-t", object_id).strip()
        if object_type != b"blob":
            continue
        size = int(_git("cat-file", "-s", object_id))
        max_blob_bytes = max(max_blob_bytes, size)
        scanned_blobs += 1
        if size > 5 * 1024 * 1024:
            continue
        payload = _git("cat-file", "blob", object_id)
        for hit_type, pattern in SECRET_PATTERNS.items():
            if pattern.search(payload):
                secret_hits.append(
                    {"type": hit_type, "object": object_id, "path": name}
                )

    commits = int(_git("rev-list", "--count", "--all"))
    emails = sorted(
        set(
            filter(
                None,
                _git("log", "--all", "--format=%ae%n%ce")
                .decode("utf-8")
                .splitlines(),
            )
        )
    )
    result: dict[str, object] = {
        "status": "passed" if not secret_hits and not forbidden_history_paths else "failed",
        "commits": commits,
        "unique_path_objects": len(objects),
        "scanned_blobs": scanned_blobs,
        "max_blob_bytes": max_blob_bytes,
        "secret_hits": secret_hits,
        "forbidden_history_paths": sorted(forbidden_history_paths),
        "author_email_identities": emails,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
