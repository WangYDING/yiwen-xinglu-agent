"""Memory categories used by the current cooperative investigation runtime."""

from enum import Enum


class StructuredMemoryType(str, Enum):
    CASE_EXPERIENCE = "case_experience"
    LEARNING_PATTERN = "learning_pattern"


class StructuredMemorySourceType(str, Enum):
    CASE_COMPLETION = "case_completion"
    ASSESSMENT = "assessment"
