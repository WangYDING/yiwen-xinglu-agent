"""Strict public argument contracts for the frozen M3-P0 tool surface."""

from pydantic import ConfigDict, Field

from xuanyi_npc.domain.base import DomainModel, Identifier


class MCPToolInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    player_id: Identifier
    session_id: Identifier


class ReadToolInput(MCPToolInput):
    pass


class InvestigationToolInput(MCPToolInput):
    investigation_id: Identifier


class DiagnosisToolInput(MCPToolInput):
    diagnosis_id: Identifier
    evidence_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)


class TreatmentToolInput(MCPToolInput):
    treatment_id: Identifier
