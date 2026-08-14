"""Fail when release-forbidden runtime or sensitive files are Git tracked."""

from __future__ import annotations

import subprocess
from pathlib import PurePosixPath


FORBIDDEN_PARTS = {
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


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True
    )
    names = result.stdout.decode("utf-8").split("\0")
    violations: list[str] = []
    for name in filter(None, names):
        path = PurePosixPath(name)
        lowered = {part.lower() for part in path.parts}
        if lowered & FORBIDDEN_PARTS or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(name)
    if violations:
        print("release-forbidden tracked files:")
        for name in violations:
            print(f"- {name}")
        return 1
    print("release tracking check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
