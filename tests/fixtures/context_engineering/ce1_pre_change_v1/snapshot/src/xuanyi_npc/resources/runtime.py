"""Safe access to the distribution's small, versioned runtime resources."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Iterator


RESOURCE_PACKAGE = "xuanyi_npc.resources"
CORE_CASE_RESOURCE_NAMES = (
    "gray_hearth_inn.json",
    "moon_well_echo.json",
    "old_paper_umbrella.json",
)
ADVANCED_CASE_RESOURCE_NAMES = (
    "lantern_alley_conflicting_testimony.json",
    "mist_ferry_borrowed_lantern.json",
    "returning_contract_nameless_shrine.json",
)
CASE_RESOURCE_NAMES = CORE_CASE_RESOURCE_NAMES + ADVANCED_CASE_RESOURCE_NAMES
CAMPAIGN_RESOURCE_NAME = "cross_episode_rules_v1.json"
DEEPSEEK_POLICY_RESOURCE_NAME = "deepseek_v4_flash_pilot_policy_2026-08-07.json"
CLINIC_RUNTIME_RESOURCES = (
    "clinic/case_guides_v1.json",
    "campaign/cross_episode_rules_v2.json",
    "clinic/clinic.css",
    "clinic/clinic.js",
)
ALLOWED_RUNTIME_RESOURCES = frozenset(
    {
        *(f"cases/{name}" for name in CASE_RESOURCE_NAMES),
        *(f"cases/{name}" for name in ADVANCED_CASE_RESOURCE_NAMES),
        f"campaign/{CAMPAIGN_RESOURCE_NAME}",
        f"pilot/{DEEPSEEK_POLICY_RESOURCE_NAME}",
        *CLINIC_RUNTIME_RESOURCES,
    }
)


class PackageResourceError(RuntimeError):
    """Raised when an installed runtime resource is missing or unreadable."""


@dataclass(frozen=True)
class RuntimeResourcePaths:
    """Temporary filesystem view for existing Path-based application services."""

    case_dir: Path
    campaign_rules: Path


@dataclass(frozen=True)
class ClinicRuntimeResourcePaths:
    case_dir: Path
    campaign_rules: Path


def _resource(relative_path: str) -> Traversable:
    path = PurePosixPath(relative_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.as_posix() not in ALLOWED_RUNTIME_RESOURCES
    ):
        raise PackageResourceError("package resource path is invalid")
    item: Traversable = files(RESOURCE_PACKAGE)
    for part in path.parts:
        item = item.joinpath(part)
    if not item.is_file():
        raise PackageResourceError("required package resource is unavailable")
    return item


def read_runtime_text(relative_path: str) -> str:
    """Read one allow-listed package resource without depending on a repository."""

    try:
        return _resource(relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PackageResourceError("required package resource cannot be read") from exc


def _copy_resource(relative_path: str, destination: Path) -> None:
    source = _resource(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as source_handle, destination.open("wb") as target:
            shutil.copyfileobj(source_handle, target)
    except OSError as exc:
        raise PackageResourceError("required package resource cannot be materialized") from exc


@contextmanager
def materialized_runtime_resources() -> Iterator[RuntimeResourcePaths]:
    """Materialize only runtime data for existing filesystem-oriented boundaries.

    The package remains the single authority. The temporary copy exists only for the
    lifetime of this context and is never a writable source of truth.
    """

    try:
        with tempfile.TemporaryDirectory(prefix="xuanyi-runtime-") as temporary:
            root = Path(temporary)
            case_dir = root / "cases"
            for name in CORE_CASE_RESOURCE_NAMES:
                _copy_resource(f"cases/{name}", case_dir / name)
            campaign_rules = root / "campaign" / CAMPAIGN_RESOURCE_NAME
            _copy_resource(
                f"campaign/{CAMPAIGN_RESOURCE_NAME}", campaign_rules
            )
            yield RuntimeResourcePaths(
                case_dir=case_dir,
                campaign_rules=campaign_rules,
            )
    except PackageResourceError:
        raise
    except OSError as exc:
        raise PackageResourceError("runtime resources cannot be materialized") from exc


@contextmanager
def materialized_clinic_resources() -> Iterator[ClinicRuntimeResourcePaths]:
    """Materialize the six packaged cases and R5 campaign for the local clinic."""
    try:
        with tempfile.TemporaryDirectory(prefix="xuanyi-clinic-runtime-") as temporary:
            root = Path(temporary)
            case_dir = root / "cases"
            for name in CASE_RESOURCE_NAMES:
                _copy_resource(f"cases/{name}", case_dir / name)
            rules = root / "campaign" / "cross_episode_rules_v2.json"
            _copy_resource("campaign/cross_episode_rules_v2.json", rules)
            yield ClinicRuntimeResourcePaths(case_dir=case_dir, campaign_rules=rules)
    except PackageResourceError:
        raise
    except OSError as exc:
        raise PackageResourceError("clinic runtime resources cannot be materialized") from exc
