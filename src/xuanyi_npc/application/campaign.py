"""M5-P3 deterministic Campaign projection, rules, views, and coordination."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import ConfigDict, Field, StrictBool, StrictInt, ValidationError

from xuanyi_npc.domain import (
    CAMPAIGN_PROJECTION_VERSION,
    CampaignEvent,
    CampaignFact,
    CampaignFactType,
    CampaignState,
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
    CompletedCaseSummary,
    CrossEpisodeRulesConfig,
    KnowledgeUnlock,
    PlayerState,
    RecommendedCaseRule,
    TreatmentOutcome,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.storage import (
    JsonStateStore,
    StateCorruptionError,
    StateNotFoundError,
)


class CampaignCatalog(Protocol):
    def case_ids(self) -> tuple[str, ...]: ...

    def get(self, case_id: str) -> CaseDefinition | None: ...


class CampaignError(RuntimeError):
    code = "campaign_error"


class CampaignRuleConfigurationError(CampaignError):
    code = "campaign_rule_invalid"


class CampaignSourceError(CampaignError):
    code = "campaign_source_invalid"


class CampaignSourceMissingError(CampaignSourceError):
    code = "campaign_source_missing"


class CampaignSourceConflictError(CampaignSourceError):
    code = "campaign_source_conflict"


class CampaignProjectionModel(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class CampaignFactView(CampaignProjectionModel):
    fact_type: CampaignFactType
    public_text: NonEmptyText
    occurred_at: datetime


class KnowledgeView(CampaignProjectionModel):
    knowledge_id: Identifier
    public_description: NonEmptyText
    unlocked_at: datetime


class CompletedCaseView(CampaignProjectionModel):
    case_id: Identifier
    title: NonEmptyText
    outcome: TreatmentOutcome
    score: StrictInt = Field(ge=0, le=100)
    submitted_diagnosis_id: Identifier
    selected_treatment_id: Identifier
    completed_at: datetime


class RecommendedCaseView(CampaignProjectionModel):
    case_id: Identifier
    title: NonEmptyText
    public_reason: NonEmptyText


class CampaignView(CampaignProjectionModel):
    player_id: Identifier
    revision: StrictInt = Field(ge=0)
    completed_cases: tuple[CompletedCaseView, ...] = Field(default_factory=tuple)
    active_facts: tuple[CampaignFactView, ...] = Field(default_factory=tuple)
    unlocked_knowledge: tuple[KnowledgeView, ...] = Field(default_factory=tuple)
    recommended_next_case: RecommendedCaseView | None = None


class CampaignCaseContext(CampaignProjectionModel):
    case_id: Identifier
    history_reaction: NonEmptyText
    related_knowledge: tuple[KnowledgeView, ...] = Field(default_factory=tuple)
    recommended_investigation_id: Identifier | None = None
    recommendation_reason: NonEmptyText | None = None


class CampaignProjectionResult(CampaignProjectionModel):
    state: CampaignState
    changed: StrictBool
    event: CampaignEvent | None = None
    newly_unlocked: tuple[KnowledgeUnlock, ...] = Field(default_factory=tuple)


class CampaignRuleSet:
    """Validated rule configuration over a trusted Case catalog."""

    def __init__(
        self,
        config: CrossEpisodeRulesConfig,
        catalog: CampaignCatalog,
    ) -> None:
        self.config = config
        self.catalog = catalog
        self._validate_catalog_references()

    @classmethod
    def load(cls, path: Path | str, catalog: CampaignCatalog) -> "CampaignRuleSet":
        try:
            config = CrossEpisodeRulesConfig.model_validate_json(
                Path(path).read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise CampaignRuleConfigurationError(
                "campaign rule configuration is invalid"
            ) from exc
        return cls(config, catalog)

    @classmethod
    def empty(cls, catalog: CampaignCatalog) -> "CampaignRuleSet":
        config = CrossEpisodeRulesConfig(
            recommended_case_order=tuple(
                RecommendedCaseRule(
                    case_id=case_id,
                    public_reason="该病例当前可独立开始。",
                )
                for case_id in catalog.case_ids()
            )
        )
        return cls(config, catalog)

    def matching_rules(self, summary: CompletedCaseSummary):
        return tuple(
            rule
            for rule in self.config.rules
            if rule.source_case_id == summary.case_id
            and rule.source_treatment_id == summary.selected_treatment_id
            and rule.source_outcome is summary.outcome
        )

    def recommended_next(self, state: CampaignState) -> RecommendedCaseRule | None:
        completed = {summary.case_id for summary in state.completed_cases}
        return next(
            (
                entry
                for entry in self.config.recommended_case_order
                if entry.case_id not in completed
            ),
            None,
        )

    def context_for(self, case_id: str, state: CampaignState) -> CampaignCaseContext:
        knowledge_by_id = self._knowledge_by_id(state)
        applicable = tuple(
            rule
            for rule in self.config.rules
            if rule.effect.target_case_id == case_id
            and rule.effect.knowledge_id in state.unlocked_knowledge_ids
        )
        related = tuple(
            knowledge_by_id[rule.effect.knowledge_id]
            for rule in applicable
        )
        if applicable:
            selected = applicable[0]
            return CampaignCaseContext(
                case_id=case_id,
                history_reaction=selected.effect.history_reaction,
                related_knowledge=tuple(
                    KnowledgeView(
                        knowledge_id=item.knowledge_id,
                        public_description=item.public_description,
                        unlocked_at=item.unlocked_at,
                    )
                    for item in related
                ),
                recommended_investigation_id=(
                    selected.effect.recommended_investigation_id
                ),
                recommendation_reason=selected.effect.recommendation_reason,
            )
        neutral = next(
            (
                item.neutral_reaction
                for item in self.config.target_case_contexts
                if item.case_id == case_id
            ),
            "当前没有与本案相关的公开历程，请依据眼前可见信息调查。",
        )
        return CampaignCaseContext(case_id=case_id, history_reaction=neutral)

    def view(self, state: CampaignState) -> CampaignView:
        knowledge = tuple(
            KnowledgeView(
                knowledge_id=item.knowledge_id,
                public_description=item.public_description,
                unlocked_at=item.unlocked_at,
            )
            for item in self._knowledge_by_id(state).values()
        )
        completed = tuple(
            CompletedCaseView(
                case_id=summary.case_id,
                title=self._require_case(summary.case_id).title,
                outcome=summary.outcome,
                score=summary.score,
                submitted_diagnosis_id=summary.submitted_diagnosis_id,
                selected_treatment_id=summary.selected_treatment_id,
                completed_at=summary.completed_at,
            )
            for summary in state.completed_cases
        )
        recommended = self.recommended_next(state)
        recommended_view = (
            RecommendedCaseView(
                case_id=recommended.case_id,
                title=self._require_case(recommended.case_id).title,
                public_reason=recommended.public_reason,
            )
            if recommended is not None
            else None
        )
        return CampaignView(
            player_id=state.player_id,
            revision=state.revision,
            completed_cases=completed,
            active_facts=tuple(
                CampaignFactView(
                    fact_type=fact.fact_type,
                    public_text=fact.public_text,
                    occurred_at=fact.occurred_at,
                )
                for fact in state.active_facts
            ),
            unlocked_knowledge=knowledge,
            recommended_next_case=recommended_view,
        )

    def _knowledge_by_id(self, state: CampaignState) -> dict[str, KnowledgeUnlock]:
        values = {
            item.knowledge_id: item
            for event in state.event_history
            for item in event.new_knowledge
        }
        return dict(sorted(values.items()))

    def _require_case(self, case_id: str) -> CaseDefinition:
        case = self.catalog.get(case_id)
        if case is None:
            raise CampaignRuleConfigurationError("campaign references unknown case")
        return case

    def _validate_catalog_references(self) -> None:
        catalog_ids = set(self.catalog.case_ids())
        recommended_ids = {
            entry.case_id for entry in self.config.recommended_case_order
        }
        if not recommended_ids or not recommended_ids.issubset(catalog_ids):
            raise CampaignRuleConfigurationError(
                "recommended case order must be a non-empty trusted catalog subset"
            )
        for context in self.config.target_case_contexts:
            self._require_case(context.case_id)
        context_ids = {item.case_id for item in self.config.target_case_contexts}
        for rule in self.config.rules:
            source = self._require_case(rule.source_case_id)
            treatment = source.treatments.get(rule.source_treatment_id)
            if treatment is None:
                raise CampaignRuleConfigurationError(
                    "campaign rule references unknown source treatment"
                )
            if treatment.outcome is not rule.source_outcome:
                raise CampaignRuleConfigurationError(
                    "campaign rule outcome does not match public treatment outcome"
                )
            target = self._require_case(rule.effect.target_case_id)
            if rule.effect.target_case_id not in context_ids:
                raise CampaignRuleConfigurationError(
                    "campaign rule target requires a neutral context"
                )
            if not any(
                item.investigation_id == rule.effect.recommended_investigation_id
                for item in target.investigations
            ):
                raise CampaignRuleConfigurationError(
                    "campaign rule recommends an unknown investigation"
                )


class CampaignProjector:
    """Project one already-committed completed Episode into Campaign state."""

    def __init__(self, rules: CampaignRuleSet) -> None:
        self.rules = rules

    def project(
        self,
        state: CampaignState,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
    ) -> CampaignProjectionResult:
        if state.player_id != player.player_id:
            raise CampaignSourceError("campaign state player does not match trusted player")
        summary = self._public_summary(player, case, session)
        existing = next(
            (
                item
                for item in state.completed_cases
                if item.session_id == session.session_id
            ),
            None,
        )
        if existing is not None:
            if existing != summary:
                raise CampaignSourceConflictError(
                    "committed session no longer matches campaign receipt"
                )
            return CampaignProjectionResult(state=state, changed=False)
        if any(item.case_id == case.case_id for item in state.completed_cases):
            raise CampaignSourceConflictError(
                "campaign already contains a different session for this case"
            )

        matching = self.rules.matching_rules(summary)
        facts = tuple(
            CampaignFact(
                fact_id=rule.effect.fact_id,
                fact_type=rule.effect.fact_type,
                player_id=player.player_id,
                source_case_id=case.case_id,
                source_session_id=session.session_id,
                source_event_sequence=session.revision,
                public_text=rule.effect.fact_public_text,
                occurred_at=summary.completed_at,
            )
            for rule in matching
        )
        knowledge = tuple(
            KnowledgeUnlock(
                knowledge_id=rule.effect.knowledge_id,
                player_id=player.player_id,
                source_case_id=case.case_id,
                source_session_id=session.session_id,
                source_event_sequence=session.revision,
                public_description=rule.effect.knowledge_public_description,
                unlocked_at=summary.completed_at,
            )
            for rule in matching
            if rule.effect.knowledge_id not in state.unlocked_knowledge_ids
        )
        event = CampaignEvent(
            sequence=state.revision + 1,
            player_id=player.player_id,
            completed_case=summary,
            new_facts=facts,
            new_knowledge=knowledge,
            occurred_at=summary.completed_at,
        )
        updated = CampaignState(
            player_id=state.player_id,
            projection_version=state.projection_version,
            revision=state.revision + 1,
            event_history=(*state.event_history, event),
            completed_cases=(*state.completed_cases, summary),
            active_facts=(*state.active_facts, *facts),
            unlocked_knowledge_ids=(
                state.unlocked_knowledge_ids
                | {item.knowledge_id for item in knowledge}
            ),
        )
        return CampaignProjectionResult(
            state=updated,
            changed=True,
            event=event,
            newly_unlocked=knowledge,
        )

    @staticmethod
    def _public_summary(
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
    ) -> CompletedCaseSummary:
        if session.player_id != player.player_id:
            raise CampaignSourceError("session player does not match trusted player")
        if session.case_id != case.case_id:
            raise CampaignSourceError("session case does not match trusted case")
        if session.status is not CaseSessionStatus.COMPLETED:
            raise CampaignSourceError("only a completed session can be projected")
        if (
            session.outcome is None
            or session.score is None
            or session.submitted_diagnosis_id is None
            or session.selected_treatment_id is None
            or not session.action_history
        ):
            raise CampaignSourceError("completed session has no public result receipt")
        if session.revision != len(session.action_history):
            raise CampaignSourceError("session revision does not match action receipts")

        discovered: set[str] = set()
        for record in session.action_history:
            if record.action_type in {
                CaseActionType.OBSERVE_PATIENT,
                CaseActionType.QUESTION_PATIENT,
                CaseActionType.INSPECT_OBJECT,
                CaseActionType.OBSERVE_QI,
                CaseActionType.INVESTIGATE_LOCATION,
            }:
                investigation = next(
                    (
                        item
                        for item in case.investigations
                        if item.investigation_id == record.reference_id
                    ),
                    None,
                )
                if (
                    investigation is None
                    or investigation.action_type is not record.action_type
                    or investigation.target_id != record.target_id
                    or not record.revealed_clue_ids.issubset(
                        investigation.reveals_clue_ids
                    )
                ):
                    raise CampaignSourceError("investigation receipt is invalid")
                discovered.update(record.revealed_clue_ids)
            elif record.action_type is CaseActionType.SUBMIT_DIAGNOSIS:
                if (
                    record.reference_id not in case.diagnosis_candidates
                    or record.target_id != record.reference_id
                    or not record.evidence_clue_ids.issubset(discovered)
                ):
                    raise CampaignSourceError("diagnosis receipt is invalid")
            elif record.action_type is CaseActionType.EXECUTE_TREATMENT:
                treatment = case.treatments.get(record.reference_id)
                if treatment is None or record.target_id != record.reference_id:
                    raise CampaignSourceError("treatment receipt is invalid")
            else:
                raise CampaignSourceError("unknown action receipt cannot be projected")

        final_record = session.action_history[-1]
        treatment = case.treatments.get(session.selected_treatment_id)
        if (
            final_record.action_type is not CaseActionType.EXECUTE_TREATMENT
            or final_record.reference_id != session.selected_treatment_id
            or treatment is None
            or treatment.outcome is not session.outcome
            or frozenset(discovered) != session.discovered_clue_ids
        ):
            raise CampaignSourceError("final public treatment receipt is inconsistent")
        return CompletedCaseSummary(
            case_id=case.case_id,
            session_id=session.session_id,
            outcome=session.outcome,
            score=session.score,
            submitted_diagnosis_id=session.submitted_diagnosis_id,
            selected_treatment_id=session.selected_treatment_id,
            discovered_clue_ids=session.discovered_clue_ids,
            source_revision=session.revision,
            source_event_sequences=tuple(
                record.sequence for record in session.action_history
            ),
            completed_at=final_record.occurred_at,
        )


class CampaignCoordinator:
    """Coordinate committed JSON Episodes into a separate Campaign snapshot."""

    def __init__(
        self,
        store: JsonStateStore,
        rules: CampaignRuleSet,
    ) -> None:
        self.store = store
        self.rules = rules
        self.projector = CampaignProjector(rules)

    def load_or_empty(self, player_id: str) -> CampaignState:
        try:
            return self.store.load_campaign(player_id)
        except StateNotFoundError:
            return CampaignState(player_id=player_id)

    def project_completed(
        self,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
    ) -> CampaignProjectionResult:
        state = self.load_or_empty(player.player_id)
        result = self.projector.project(state, player, case, session)
        if result.changed:
            self.store.save_campaign(result.state)
        return result

    def reconcile(self, player: PlayerState) -> CampaignProjectionResult:
        current = self.load_or_empty(player.player_id)
        self._verify_existing_sources(player, current)
        updated = current
        new_events: list[CampaignEvent] = []
        new_knowledge: list[KnowledgeUnlock] = []
        try:
            sessions = tuple(
                sorted(
                    (
                        session
                        for session in self.store.list_case_sessions()
                        if session.player_id == player.player_id
                        and session.status is CaseSessionStatus.COMPLETED
                    ),
                    key=lambda item: (
                        item.action_history[-1].occurred_at,
                        item.session_id,
                    ),
                )
            )
        except StateCorruptionError as exc:
            raise CampaignSourceConflictError(
                "committed session storage is corrupted"
            ) from exc
        for session in sessions:
            case = self.rules.catalog.get(session.case_id)
            if case is None:
                raise CampaignSourceError("completed session references unknown case")
            projected = self.projector.project(updated, player, case, session)
            updated = projected.state
            if projected.event is not None:
                new_events.append(projected.event)
                new_knowledge.extend(projected.newly_unlocked)
        changed = updated != current
        if changed:
            self.store.save_campaign(updated)
        return CampaignProjectionResult(
            state=updated,
            changed=changed,
            event=(new_events[-1] if len(new_events) == 1 else None),
            newly_unlocked=tuple(new_knowledge),
        )

    def _verify_existing_sources(
        self,
        player: PlayerState,
        state: CampaignState,
    ) -> None:
        for summary in state.completed_cases:
            try:
                session = self.store.load_case_session(summary.session_id)
            except StateNotFoundError as exc:
                raise CampaignSourceMissingError(
                    "campaign source session is missing"
                ) from exc
            except StateCorruptionError as exc:
                raise CampaignSourceConflictError(
                    "campaign source session is corrupted"
                ) from exc
            case = self.rules.catalog.get(summary.case_id)
            if case is None:
                raise CampaignSourceConflictError(
                    "campaign source case is unavailable"
                )
            rebuilt = self.projector._public_summary(player, case, session)
            if rebuilt != summary:
                raise CampaignSourceConflictError(
                    "campaign source session no longer matches its receipt"
                )
