"""Deterministic identifiers and hashes for public memory data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Set
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel


MEMORY_NAMESPACE = UUID("22f2da8c-65dc-5a66-a9c4-e071bbb7328f")


def normalize_utc(value: datetime) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def utc_text(value: datetime) -> str:
    """Return one stable UTC representation used by JSON and SQLite."""

    return normalize_utc(value).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return utc_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        items = [_canonical_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize public data with stable keys, collections and timestamps."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hex(value: Any) -> str:
    """Hash only the canonical value supplied by the caller."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _stable_identifier(prefix: str, purpose: str, value: Any) -> str:
    name = f"{purpose}:{canonical_json(value)}"
    return f"{prefix}_{uuid5(MEMORY_NAMESPACE, name).hex}"


def stable_source_event_id(
    source_event_type: str,
    source_session_id: str,
    source_sequence: int,
) -> str:
    return _stable_identifier(
        "ce",
        "case_event",
        {
            "event_type": source_event_type,
            "session_id": source_session_id,
            "sequence": source_sequence,
        },
    )


def stable_memory_id(
    player_id: str,
    source_event_id: str,
    projection_version: str,
    projection_ordinal: int,
) -> str:
    return _stable_identifier(
        "mem",
        "memory_event",
        {
            "player_id": player_id,
            "projection_ordinal": projection_ordinal,
            "projection_version": projection_version,
            "source_event_id": source_event_id,
        },
    )


def stable_lifecycle_operation_id(
    action: str,
    player_id: str,
    target_memory_id: str,
    request_id: str,
) -> str:
    return _stable_identifier(
        "lop",
        "memory_lifecycle",
        {
            "action": action,
            "player_id": player_id,
            "request_id": request_id,
            "target_memory_id": target_memory_id,
        },
    )


def stable_correction_source_id(operation_id: str) -> str:
    return _stable_identifier(
        "mc",
        "memory_correction_source",
        {"operation_id": operation_id},
    )
