"""Generic permission-gated investigation overlays for clinic case catalogs."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .cases import CaseActionType
from .permissions import PermissionLevel


class CaseAccessModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PermissionInvestigation(CaseAccessModel):
    case_id: Identifier
    investigation_id: Identifier
    action_type: CaseActionType
    target_id: Identifier
    public_description: NonEmptyText
    reveals_clue_ids: frozenset[Identifier] = Field(min_length=1)
    required_permission: PermissionLevel
    required_skill_id: Identifier | None = None
    minimum_skill_level: int = 0
    required_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    satisfies_requirement_id: Identifier


class CaseAccessPolicy(CaseAccessModel):
    policy_id: Literal["case_access_policy_v1"]
    version: Literal["v1"]
    permission_investigations: tuple[PermissionInvestigation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> "CaseAccessPolicy":
        keys = {(item.case_id, item.investigation_id) for item in self.permission_investigations}
        if len(keys) != len(self.permission_investigations):
            raise ValueError("permission investigation ids must be unique per case")
        return self
