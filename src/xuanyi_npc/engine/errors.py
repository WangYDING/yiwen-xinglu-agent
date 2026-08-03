"""Explicit rule violations returned by the deterministic engine."""


class RuleViolation(Exception):
    """Base class for a rejected command. Rejections never mutate session state."""

    code = "rule_violation"


class ContextMismatchError(RuleViolation):
    code = "context_mismatch"


class SessionClosedError(RuleViolation):
    code = "session_closed"


class UnknownCommandError(RuleViolation):
    code = "unknown_command"


class UnknownInvestigationError(RuleViolation):
    code = "unknown_investigation"


class ActionMismatchError(RuleViolation):
    code = "action_mismatch"


class SkillLockedError(RuleViolation):
    code = "skill_locked"


class InsufficientSkillError(RuleViolation):
    code = "insufficient_skill"


class MissingCluePrerequisiteError(RuleViolation):
    code = "missing_clue_prerequisite"


class EvidenceNotDiscoveredError(RuleViolation):
    code = "evidence_not_discovered"


class DiagnosisRequiredError(RuleViolation):
    code = "diagnosis_required"


class UnknownTreatmentError(RuleViolation):
    code = "unknown_treatment"


class TreatmentPrerequisiteError(RuleViolation):
    code = "treatment_prerequisite_missing"
