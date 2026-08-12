"""Strict, versioned R6 product acceptance contract."""

from typing import Literal
from pydantic import ConfigDict, Field, model_validator
from .base import DomainModel, Identifier, NonEmptyText


class AcceptanceModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AcceptanceGate(AcceptanceModel):
    gate_id: Identifier
    requirements: tuple[NonEmptyText, ...] = Field(min_length=1)


class AcceptanceRoute(AcceptanceModel):
    route_id: Identifier
    title: NonEmptyText
    assertions: tuple[NonEmptyText, ...] = Field(min_length=3)


class DeterminismContract(AcceptanceModel):
    runs: Literal[2]
    normalized_streams: tuple[Identifier, ...] = Field(min_length=9)
    allowed_differences: tuple[Identifier, ...] = Field(min_length=3)
    hashes_must_match: Literal[True]


class ProductAcceptanceV1(AcceptanceModel):
    contract_id: Literal["product_acceptance_v1"]
    version: Literal["v1"]
    status_on_offline_pass: Literal["r6_in_progress"]
    gates: tuple[AcceptanceGate, ...] = Field(min_length=5, max_length=5)
    routes: tuple[AcceptanceRoute, ...] = Field(min_length=8, max_length=8)
    determinism: DeterminismContract
    real_pilot_scenarios: tuple[Identifier, ...] = Field(min_length=4, max_length=4)
    real_pilot_budget_cny: Literal[0.05]
    playtest_versions_minutes: tuple[Literal[15], Literal[45]]
    playtest_recommended_people: Literal["3-5"]
    release_blockers: tuple[Identifier, ...] = Field(min_length=8)
    forbidden_claim_conflations: tuple[NonEmptyText, ...] = Field(min_length=3)
    prohibited_external_actions: tuple[Identifier, ...] = Field(min_length=8)

    @model_validator(mode="after")
    def frozen_shape(self):
        if {item.gate_id for item in self.gates} != {
            "product_completeness", "mentor_experience", "engineering_safety",
            "stability", "truthfulness_boundary",
        }:
            raise ValueError("all five R6 gates are required")
        if tuple(item.route_id for item in self.routes) != tuple(f"route_{i}" for i in range(1, 9)):
            raise ValueError("the eight product routes must remain ordered")
        return self
