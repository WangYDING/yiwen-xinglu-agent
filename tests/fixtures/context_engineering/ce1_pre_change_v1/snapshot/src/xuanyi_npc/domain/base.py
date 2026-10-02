"""Shared types and validation configuration for domain models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


Identifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2000),
]


class DomainModel(BaseModel):
    """Base class that rejects undeclared fields across the domain boundary."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )
