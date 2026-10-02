"""Versioned contracts for the V2 evaluation pipeline.

These models deliberately do not reuse the V1 benchmark artifact schema.  A V2
artifact is either provider-backed or fixture-backed and can never silently
change kind during aggregation.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText


class ArtifactKind(str, Enum):
    REAL_MODEL_TRIAL = "real_model_trial"
    DETERMINISTIC_FIXTURE = "deterministic_fixture"


class GradeStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_READY = "NOT_READY"


class V2Scenario(DomainModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(pattern=r"^[A-Z]{1,2}[0-9]{2}$")
    suite: Literal["task", "engineering", "memory_transfer", "reflection_quality"]
    fixture_status: NonEmptyText
    expected: NonEmptyText
    graders: tuple[Identifier, ...]
    repeat_count: StrictInt = Field(ge=1)
    base_case_id: Identifier | None = None
    profile: Identifier | None = None
    split: str | None = None
    name: str | None = None
    stimulus: str | None = None
    conditions: tuple[str, ...] = ()


class V2Event(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Identifier
    event_id: Identifier
    sequence: StrictInt = Field(ge=1)
    event_type: Identifier
    occurred_at: datetime
    source: NonEmptyText
    turn: StrictInt | None = Field(default=None, ge=0)
    parent_event_id: Identifier | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def aware_time(self) -> "V2Event":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("event timestamp must be timezone-aware")
        return self


class V2Grade(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    grader_id: Identifier
    grader_version: NonEmptyText = "v2.0"
    status: GradeStatus
    reason_code: Identifier
    evidence_event_ids: tuple[Identifier, ...] = ()
    numerator: StrictInt | None = Field(default=None, ge=0)
    denominator: StrictInt | None = Field(default=None, ge=0)
    note: str | None = None


class V2RunArtifact(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["evaluation_v2_run_v1"] = "evaluation_v2_run_v1"
    trace_schema_version: Literal["v1_sparse", "v2_diagnostic"] = "v1_sparse"
    run_id: Identifier
    experiment_id: Identifier
    scenario_id: str = Field(pattern=r"^[A-Z]{1,2}[0-9]{2}$")
    suite: str
    condition: str | None = None
    repeat_index: StrictInt = Field(ge=1)
    artifact_kind: ArtifactKind
    started_at: datetime
    finished_at: datetime
    status: Literal["finished", "aborted", "invalid", "not_ready"]
    model: str | None = None
    provider: str | None = None
    system_fingerprints: tuple[str, ...] = ()
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)
    known_cost_cny: float | None = Field(default=None, ge=0)
    duration_ms: float = Field(ge=0)
    terminal_snapshot: dict[str, Any] = Field(default_factory=dict)
    public_input_fingerprint: str | None = None
    non_memory_input_fingerprint: str | None = None
    events: tuple[V2Event, ...] = ()
    grades: tuple[V2Grade, ...] = ()
    failure_code: str | None = None


class V2Manifest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["evaluation_v2_manifest_v1"] = "evaluation_v2_manifest_v1"
    experiment_id: Identifier
    phase: Literal["offline", "pilot", "full"]
    artifact_kind: ArtifactKind
    created_at: datetime
    git_commit: str | None
    git_dirty: StrictBool | None
    dirty_tree_hash: str
    model: str | None
    provider: str | None
    temperature: float | None
    max_output_tokens: StrictInt | None
    max_turns: StrictInt = Field(ge=1)
    hard_budget_cny: float | None = Field(default=None, gt=0)
    price_snapshot_id: str | None
    scenario_catalog_hash: NonEmptyText
    scenario_resolved_hash: NonEmptyText
    oracle_hash: NonEmptyText
    grader_hash: NonEmptyText
    runtime_hashes: dict[str, NonEmptyText]
    execution_order: tuple[str, ...]
    planned_runs: StrictInt = Field(ge=0)


class V2Aggregate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["evaluation_v2_aggregate_v1"] = "evaluation_v2_aggregate_v1"
    experiment_id: Identifier
    artifact_kind: ArtifactKind
    planned: StrictInt = Field(ge=0)
    started: StrictInt = Field(ge=0)
    finished: StrictInt = Field(ge=0)
    aborted: StrictInt = Field(ge=0)
    invalid: StrictInt = Field(ge=0)
    not_ready: StrictInt = Field(ge=0)
    task_success_n: StrictInt = Field(ge=0)
    task_success_d: StrictInt = Field(ge=0)
    strict_success_n: StrictInt = Field(ge=0)
    strict_success_d: StrictInt = Field(ge=0)
    safety_unknown: StrictInt = Field(ge=0)
    safety_failures: StrictInt = Field(ge=0)
    known_cost_cny: float
    cost_complete_runs: StrictInt = Field(ge=0)
    input_tokens_known: StrictInt = Field(ge=0)
    output_tokens_known: StrictInt = Field(ge=0)
    by_scenario: dict[str, dict[str, Any]]
