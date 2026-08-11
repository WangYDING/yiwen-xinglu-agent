"""Frozen R4 teaching-stage and permission contracts."""

from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .base import DomainModel, Identifier, NonEmptyText


class PermissionModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class R4TeachingStage(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    APPRENTICE = "APPRENTICE"
    EXAM_CANDIDATE = "EXAM_CANDIDATE"
    INNER_DISCIPLE = "INNER_DISCIPLE"


class PermissionLevel(str, Enum):
    PUBLIC = "PUBLIC"
    APPRENTICE = "APPRENTICE"
    INNER_DISCIPLE = "INNER_DISCIPLE"
    CORE_TEACHING = "CORE_TEACHING"
    INHERITANCE = "INHERITANCE"
    MENTOR_SECRET = "MENTOR_SECRET"


class PermissionRule(PermissionModel):
    permission: PermissionLevel
    public_description: NonEmptyText
    grant_condition_code: Identifier


class PermissionPolicy(PermissionModel):
    policy_id: Literal["permission_policy_v1"]
    version: Literal["v1"]
    default_permissions: tuple[PermissionLevel, ...] = (PermissionLevel.PUBLIC,)
    rules: tuple[PermissionRule, ...] = Field(min_length=6, max_length=6)
    allowed_stage_transitions: dict[R4TeachingStage, tuple[R4TeachingStage, ...]]
    mentor_secret_grantable: Literal[False]
    denial_error_code: Literal["knowledge_access_denied"]

    @model_validator(mode="after")
    def validate_policy(self) -> "PermissionPolicy":
        if {item.permission for item in self.rules} != set(PermissionLevel):
            raise ValueError("permission policy must define every level once")
        if set(self.allowed_stage_transitions) != set(R4TeachingStage):
            raise ValueError("permission policy must define every stage transition")
        return self

