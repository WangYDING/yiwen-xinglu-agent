"""Public API for deterministic case execution."""

from .case_engine import CaseEngine
from .errors import (
    ActionMismatchError,
    ContextMismatchError,
    DiagnosisRequiredError,
    EvidenceNotDiscoveredError,
    InsufficientSkillError,
    MissingCluePrerequisiteError,
    RuleViolation,
    SessionClosedError,
    SkillLockedError,
    TreatmentPrerequisiteError,
    UnknownCommandError,
    UnknownInvestigationError,
    UnknownTreatmentError,
)
from .results import EngineResult, ScoreBreakdown
from .replay import CaseEventReplayer, EventReplayError

__all__ = [
    "ActionMismatchError",
    "CaseEngine",
    "CaseEventReplayer",
    "ContextMismatchError",
    "DiagnosisRequiredError",
    "EngineResult",
    "EvidenceNotDiscoveredError",
    "EventReplayError",
    "InsufficientSkillError",
    "MissingCluePrerequisiteError",
    "RuleViolation",
    "ScoreBreakdown",
    "SessionClosedError",
    "SkillLockedError",
    "TreatmentPrerequisiteError",
    "UnknownCommandError",
    "UnknownInvestigationError",
    "UnknownTreatmentError",
]
