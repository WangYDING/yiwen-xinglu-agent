"""Download the frozen BGE-M3 dense whitelist without using a global cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


MAX_ADDED_BYTES = 12 * 1024**3
MIN_FREE_BYTES = 20 * 1024**3
CHUNK_SIZE = 8 * 1024**2
ALLOWED_FILES = (
    "1_Pooling/config.json",
    "README.md",
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
MAIN_WEIGHT_SHA256 = "993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_model_target(project_root: Path, target: Path) -> Path:
    project_root = project_root.resolve(strict=True)
    model_root = (project_root / "runtime_models").resolve()
    target = target.resolve()
    if not target.is_relative_to(model_root) or target == model_root:
        raise ValueError("target must be a named directory under runtime_models")
    return target


def _load_expected_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "manifest_version",
        "repository_id",
        "revision",
        "mode",
        "precision",
        "dimension",
        "trust_remote_code",
        "revision_total_bytes",
        "expected_total_bytes",
        "files",
        "forbidden_patterns",
    }
    if set(payload) != required:
        raise ValueError("expected manifest fields do not match the frozen schema")
    if payload["repository_id"] != "BAAI/bge-m3":
        raise ValueError("model repository is not allowed")
    if payload["revision"] != "142964af7e05de16511657561de8e8750fc153a0":
        raise ValueError("model revision is not allowed")
    if payload["mode"] != "dense_only" or payload["precision"] != "fp32":
        raise ValueError("only dense FP32 files are allowed")
    if payload["dimension"] != 1024 or payload["trust_remote_code"] is not False:
        raise ValueError("model safety contract does not match")
    files = payload["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("expected manifest contains no files")
    file_fields = {"path", "expected_size_bytes", "expected_sha256"}
    if any(not isinstance(item, dict) or set(item) != file_fields for item in files):
        raise ValueError("expected manifest file fields do not match the frozen schema")
    expected_paths = [item["path"] for item in files]
    if tuple(expected_paths) != ALLOWED_FILES:
        raise ValueError("manifest file inventory is not the hard-coded whitelist")
    for item in files:
        if not isinstance(item["expected_size_bytes"], int) or item["expected_size_bytes"] < 1:
            raise ValueError("expected file size is invalid")
        expected_sha = item["expected_sha256"]
        if expected_sha is not None and (
            not isinstance(expected_sha, str)
            or len(expected_sha) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha)
        ):
            raise ValueError("expected file hash is invalid")
    main_weight = next(item for item in files if item["path"] == "model.safetensors")
    if main_weight["expected_sha256"] != MAIN_WEIGHT_SHA256:
        raise ValueError("main weight hash is not the frozen SHA-256")
    if sum(item["expected_size_bytes"] for item in files) != payload["expected_total_bytes"]:
        raise ValueError("expected manifest byte total is inconsistent")
    if payload["expected_total_bytes"] > MAX_ADDED_BYTES:
        raise ValueError("model whitelist exceeds the disk budget")
    return payload


def download(*, project_root: Path, target: Path, manifest_path: Path) -> dict[str, Any]:
    target = _require_model_target(project_root, target)
    manifest = _load_expected_manifest(manifest_path.resolve(strict=True))
    free_bytes = shutil.disk_usage(project_root).free
    if free_bytes < MIN_FREE_BYTES:
        raise RuntimeError("project volume has less than 20 GiB free")
    if target.exists() and any(target.rglob("*")):
        raise RuntimeError("target model directory must be absent or empty")
    target.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    verified: list[dict[str, Any]] = []
    base_url = (
        "https://huggingface.co/"
        f"{manifest['repository_id']}/resolve/{manifest['revision']}"
    )
    try:
        with httpx.Client(follow_redirects=True, timeout=180.0) as client:
            for item in manifest["files"]:
                relative = Path(item["path"])
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_name(destination.name + ".partial")
                created.append(partial)
                encoded_path = "/".join(quote(part) for part in relative.parts)
                url = f"{base_url}/{encoded_path}"
                digest = hashlib.sha256()
                size = 0
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with partial.open("xb") as stream:
                        for chunk in response.iter_bytes(CHUNK_SIZE):
                            size += len(chunk)
                            if size > item["expected_size_bytes"]:
                                raise RuntimeError("downloaded file exceeds expected size")
                            digest.update(chunk)
                            stream.write(chunk)
                actual_sha = digest.hexdigest()
                if size != item["expected_size_bytes"]:
                    raise RuntimeError("downloaded file size does not match manifest")
                expected_sha = item["expected_sha256"]
                if expected_sha is not None and actual_sha != expected_sha:
                    raise RuntimeError("downloaded file hash does not match manifest")
                partial.replace(destination)
                created[-1] = destination
                verified.append(
                    {"path": relative.as_posix(), "size_bytes": size, "sha256": actual_sha}
                )
        actual_paths = sorted(
            path.relative_to(target).as_posix()
            for path in target.rglob("*")
            if path.is_file()
        )
        if tuple(actual_paths) != ALLOWED_FILES:
            raise RuntimeError("download directory contains a non-whitelisted file")
        return {
            "repository_id": manifest["repository_id"],
            "revision": manifest["revision"],
            "target": str(target),
            "total_bytes": sum(item["size_bytes"] for item in verified),
            "files": verified,
        }
    except Exception:
        for path in reversed(created):
            if path.exists() and path.is_file() and path.is_relative_to(target):
                path.unlink()
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = download(
            project_root=args.project_root,
            target=args.target,
            manifest_path=args.manifest,
        )
    except Exception as exc:
        print(f"download failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
