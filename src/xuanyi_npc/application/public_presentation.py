"""Trusted public terminology and player-visible presentation boundary."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from xuanyi_npc.domain.base import DomainModel, NonEmptyText
from xuanyi_npc.resources.runtime import read_runtime_text


EntityType = Literal[
    "ability", "lesson", "remediation", "stage", "permission", "inheritance",
    "exam", "recommendation", "reason", "phase", "outcome", "relationship",
    "case_status", "exam_status", "inheritance_status",
]


class PublicTerminologyEntry(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entity_type: EntityType
    internal_id: NonEmptyText
    public_name: NonEmptyText
    public_short_description: NonEmptyText


class PublicTerminologyCatalog(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    catalog_id: Literal["public_terminology_v1"]
    version: Literal["v1"]
    entries: tuple[PublicTerminologyEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_entries(self):
        keys = tuple((item.entity_type, item.internal_id) for item in self.entries)
        if len(keys) != len(set(keys)):
            raise ValueError("public terminology contains duplicate mappings")
        return self


class PublicPresentationMapper:
    """Maps trusted internal references without ever echoing an unknown identifier."""

    def __init__(self, catalog: PublicTerminologyCatalog):
        self.catalog = catalog
        self._by_key = {(item.entity_type, item.internal_id): item for item in catalog.entries}
        self.internal_ids = frozenset(item.internal_id for item in catalog.entries)

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls):
        return cls(PublicTerminologyCatalog.model_validate_json(
            read_runtime_text("presentation/public_terminology_v1.json")
        ))

    def entry(self, entity_type: EntityType, internal_id: str) -> PublicTerminologyEntry | None:
        return self._by_key.get((entity_type, str(internal_id)))

    def name(self, entity_type: EntityType, internal_id: str, *, fallback: str = "相关内容") -> str:
        item = self.entry(entity_type, internal_id)
        return item.public_name if item else fallback

    def public_object(self, entity_type: EntityType, internal_id: str) -> dict[str, str]:
        item = self.entry(entity_type, internal_id)
        if item is None:
            return {"public_name": "相关内容", "public_description": "具体名称暂不可公开显示。"}
        return {"public_name": item.public_name, "public_description": item.public_short_description}

    def recommendation_name(self, kind: str, internal_id: str) -> str:
        entity = {"core_lesson":"lesson","advanced_lesson":"lesson","remediation":"remediation","exam":"exam","inheritance":"inheritance","complete":"recommendation","foundation_complete":"recommendation"}.get(str(kind),"recommendation")
        return self.name(entity, internal_id, fallback="当前建议")

    def detected_internal_ids(self, text: str) -> tuple[str, ...]:
        hits = set()
        for internal_id in self.internal_ids:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(internal_id)}(?![A-Za-z0-9_])", text):
                hits.add(internal_id)
        # Conservative structural forms: snake_case identifiers and versioned IDs.
        # Single ordinary English words are not matched unless present in the catalog.
        hits.update(re.findall(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:_v\d+)?(?![A-Za-z0-9_])", text))
        hits.update(re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![A-Za-z0-9_])", text))
        return tuple(sorted(hits))

    def contains_internal_id(self, text: str) -> bool:
        return bool(self.detected_internal_ids(text))

    def sanitize_legacy_text(self, text: str) -> str:
        value = str(text)
        for internal_id in sorted(self.internal_ids, key=len, reverse=True):
            entries = [item for item in self.catalog.entries if item.internal_id == internal_id]
            public = entries[0].public_name if entries else "相关内容"
            value = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(internal_id)}(?![A-Za-z0-9_])", public, value)
        # Unknown identifier-like values never get echoed from legacy public text.
        value = re.sub(r"(?<![A-Za-z0-9_])[a-z][a-z0-9_]{2,}_(?:v\d+|[a-z][a-z0-9_]+)(?![A-Za-z0-9_])", "相关内容", value)
        return value


PUBLIC_PRESENTATION = PublicPresentationMapper.load()
