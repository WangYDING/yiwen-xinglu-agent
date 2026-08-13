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
FOUNDATION_CASE_RESOURCE_NAMES = (
    "gray_hearth_inn.json",
    "moon_well_echo.json",
    "old_paper_umbrella.json",
)
ADVANCED_CASE_RESOURCE_NAMES = (
    "lantern_alley_conflicting_testimony.json",
    "mist_ferry_borrowed_lantern.json",
    "returning_contract_nameless_shrine.json",
)
CASE_RESOURCE_NAMES = FOUNDATION_CASE_RESOURCE_NAMES + ADVANCED_CASE_RESOURCE_NAMES
CAMPAIGN_RESOURCE_NAME = "cross_episode_rules_v1.json"
M5_HISTORY_RESOURCE_NAME = "m5_history_evidence_v1.json"
DEEPSEEK_POLICY_RESOURCE_NAME = "deepseek_v4_flash_pilot_policy_2026-08-07.json"
PROGRESSION_RESOURCE_NAME = "apprenticeship_progression_v1.json"
MENTOR_PROFILE_RESOURCE_NAME = "mentor_profile_v1.json"
R2_LESSON_RESOURCE_NAME = "evidence_before_diagnosis_v1.json"
R3_CURRICULUM_RESOURCE_NAMES = (
    R2_LESSON_RESOURCE_NAME,
    "provenance_before_intent_v1.json",
    "corroborate_before_handoff_v1.json",
    "remediate_evidence_completeness_v1.json",
    "remediate_diagnostic_reasoning_v1.json",
    "remediate_treatment_alignment_v1.json",
    "curriculum_selection_v1.json",
    "structured_mentor_memory_selection_v1.json",
    "r3_acceptance_v1.json",
)
R4_RUNTIME_RESOURCES = (
    "exams/foundational_xuanyi_exam_v1.json",
    "permissions/permission_policy_v1.json",
    "inheritance/trace_vow_restore_v1.json",
    "inheritance/r4_acceptance_v1.json",
)
R5_RUNTIME_RESOURCES = (
    "curriculum/curriculum_selection_v2.json",
    "curriculum/cross_check_conflicting_testimony_v1.json",
    "curriculum/bounded_treatment_and_consequence_v1.json",
    "curriculum/integrated_causal_reasoning_v1.json",
    "clinic/clinic_contract_v1.json",
    "clinic/r5_acceptance_v1.json",
    "clinic/case_access_policy_v1.json",
    "campaign/cross_episode_rules_v2.json",
    "clinic/clinic.css",
    "clinic/clinic.js",
)
R6_RUNTIME_RESOURCES = (
    "acceptance/product_acceptance_v1.json",
    "acceptance/real_mentor_pilot_v1.json",
    "acceptance/r6_real_mentor_pilot_v2.json",
    "acceptance/r6_real_mentor_pilot_v3.json",
    "pilot/deepseek_v4_flash_mentor_pricing_2026-08-13.json",
)
ALLOWED_RUNTIME_RESOURCES = frozenset(
    {
        *(f"cases/{name}" for name in CASE_RESOURCE_NAMES),
        *(f"cases/{name}" for name in ADVANCED_CASE_RESOURCE_NAMES),
        f"campaign/{CAMPAIGN_RESOURCE_NAME}",
        f"release/{M5_HISTORY_RESOURCE_NAME}",
        f"pilot/{DEEPSEEK_POLICY_RESOURCE_NAME}",
        f"progression/{PROGRESSION_RESOURCE_NAME}",
        f"mentor/{MENTOR_PROFILE_RESOURCE_NAME}",
        *(f"curriculum/{name}" for name in R3_CURRICULUM_RESOURCE_NAMES),
        *R4_RUNTIME_RESOURCES,
        *R5_RUNTIME_RESOURCES,
        *R6_RUNTIME_RESOURCES,
    }
)


class PackageResourceError(RuntimeError):
    """Raised when an installed runtime resource is missing or unreadable."""


@dataclass(frozen=True)
class RuntimeResourcePaths:
    """Temporary filesystem view for existing Path-based application services."""

    case_dir: Path
    campaign_rules: Path
    m5_history_evidence: Path
    deepseek_policy: Path


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
            for name in FOUNDATION_CASE_RESOURCE_NAMES:
                _copy_resource(f"cases/{name}", case_dir / name)
            campaign_rules = root / "campaign" / CAMPAIGN_RESOURCE_NAME
            _copy_resource(
                f"campaign/{CAMPAIGN_RESOURCE_NAME}", campaign_rules
            )
            history = root / "release" / M5_HISTORY_RESOURCE_NAME
            _copy_resource(f"release/{M5_HISTORY_RESOURCE_NAME}", history)
            policy = root / "pilot" / DEEPSEEK_POLICY_RESOURCE_NAME
            _copy_resource(f"pilot/{DEEPSEEK_POLICY_RESOURCE_NAME}", policy)
            yield RuntimeResourcePaths(
                case_dir=case_dir,
                campaign_rules=campaign_rules,
                m5_history_evidence=history,
                deepseek_policy=policy,
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
