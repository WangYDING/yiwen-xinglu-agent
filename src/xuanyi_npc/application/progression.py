"""Versioned deterministic apprenticeship progression and coordination."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Protocol

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from xuanyi_npc.domain.apprenticeship import (
    APPRENTICESHIP_SCHEMA_VERSION,
    PROGRESSION_POLICY_VERSION,
    AbilityEvidence,
    AbilityEvidenceRecorded,
    AbilityId,
    AbilityLevel,
    AbilityProgressed,
    AbilityState,
    ApprenticeshipEventReplayer,
    ApprenticeshipInitialized,
    ApprenticeshipState,
    EpisodeGrowthApplied,
    EvidencePolarity,
    RelationshipChanged,
    RelationshipDimension,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import (
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    CaseSessionStatus,
    TreatmentOutcome,
)
from xuanyi_npc.domain.player import PlayerState, TeachingStage
from xuanyi_npc.domain.relationship import RelationshipState
from xuanyi_npc.resources.runtime import PROGRESSION_RESOURCE_NAME, read_runtime_text
from xuanyi_npc.storage import (
    JsonStateStore,
    StateCorruptionError,
    StateNotFoundError,
)


class ProgressionError(RuntimeError):
    code = "apprenticeship_source_invalid"


class ProgressionSourceError(ProgressionError):
    pass


class ProgressionSourceMissingError(ProgressionSourceError):
    code = "apprenticeship_source_missing"


class ProgressionSourceConflictError(ProgressionSourceError):
    code = "apprenticeship_source_conflict"


class ProgressionConfigError(ProgressionError):
    pass


class ProgressionModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AbilityLevelRule(ProgressionModel):
    level: AbilityLevel
    minimum_proficiency: Annotated[StrictInt, Field(ge=0, le=100)]


class AbilityRule(ProgressionModel):
    ability_id: AbilityId
    display_name: NonEmptyText
    initial_proficiency: Annotated[StrictInt, Field(ge=0, le=100)]
    unlocked: StrictBool


class RelationshipRule(ProgressionModel):
    outcome: TreatmentOutcome
    minimum_score: Annotated[StrictInt, Field(ge=0, le=100)]
    maximum_score: Annotated[StrictInt, Field(ge=0, le=100)]
    affinity: Annotated[StrictInt, Field(ge=-2, le=2)]
    trust: Annotated[StrictInt, Field(ge=-2, le=2)]
    recognition: Annotated[StrictInt, Field(ge=-2, le=2)]
    public_reason_code: Identifier
    public_description: NonEmptyText

    @model_validator(mode="after")
    def validate_range(self) -> "RelationshipRule":
        if self.minimum_score > self.maximum_score:
            raise ValueError("relationship score range is inverted")
        if self.affinity != 0:
            raise ValueError("R1 affinity rules must remain zero")
        return self


class ProgressionConfig(ProgressionModel):
    policy_version: str
    state_schema_version: str
    teaching_stage: TeachingStage
    ability_levels: tuple[AbilityLevelRule, ...]
    abilities: tuple[AbilityRule, ...]
    initial_relationship: RelationshipState
    maximum_positive_growth_per_ability_per_episode: Annotated[
        StrictInt, Field(ge=1, le=2)
    ]
    investigation_action_ability_map: dict[CaseActionType, AbilityId]
    relationship_rules: tuple[RelationshipRule, ...]

    @model_validator(mode="after")
    def validate_frozen_policy(self) -> "ProgressionConfig":
        if self.policy_version != PROGRESSION_POLICY_VERSION:
            raise ValueError("unsupported progression policy version")
        if self.state_schema_version != APPRENTICESHIP_SCHEMA_VERSION:
            raise ValueError("unsupported apprenticeship schema version")
        if {item.ability_id for item in self.abilities} != set(AbilityId):
            raise ValueError("progression policy must define exactly six abilities")
        thresholds = [item.minimum_proficiency for item in self.ability_levels]
        if thresholds != sorted(set(thresholds)) or not thresholds or thresholds[0] != 0:
            raise ValueError("ability level thresholds must be unique and start at zero")
        if {item.level for item in self.ability_levels} != set(AbilityLevel):
            raise ValueError("progression policy must define all ability levels")
        expected_actions = {
            CaseActionType.OBSERVE_PATIENT,
            CaseActionType.QUESTION_PATIENT,
            CaseActionType.INSPECT_OBJECT,
            CaseActionType.OBSERVE_QI,
            CaseActionType.INVESTIGATE_LOCATION,
        }
        if set(self.investigation_action_ability_map) != expected_actions:
            raise ValueError("investigation mapping must cover all investigation actions")
        return self


class AbilityChangeView(ProgressionModel):
    ability_id: AbilityId
    display_name: NonEmptyText
    proficiency_before: Annotated[StrictInt, Field(ge=0, le=100)]
    proficiency_after: Annotated[StrictInt, Field(ge=0, le=100)]
    delta: Annotated[StrictInt, Field(ge=1, le=2)]
    public_description: NonEmptyText


class RelationshipChangeView(ProgressionModel):
    dimension: RelationshipDimension
    value_before: Annotated[StrictInt, Field(ge=0, le=100)]
    value_after: Annotated[StrictInt, Field(ge=0, le=100)]
    delta: Annotated[StrictInt, Field(ge=-2, le=2)]
    public_description: NonEmptyText


class AbilityPublicView(ProgressionModel):
    ability_id: AbilityId
    display_name: NonEmptyText
    level: AbilityLevel
    proficiency: Annotated[StrictInt, Field(ge=0, le=100)]
    evidence_count: Annotated[StrictInt, Field(ge=0)]
    unlocked: StrictBool


class ApprenticeshipView(ProgressionModel):
    teaching_stage: TeachingStage
    abilities: tuple[AbilityPublicView, ...]
    affinity: Annotated[StrictInt, Field(ge=0, le=100)]
    trust: Annotated[StrictInt, Field(ge=0, le=100)]
    recognition: Annotated[StrictInt, Field(ge=0, le=100)]
    latest_growth_reason: NonEmptyText | None = None
    applied_episode_count: Annotated[StrictInt, Field(ge=0)]
    revision: Annotated[StrictInt, Field(ge=1)]


class ProgressionProjectionResult(ProgressionModel):
    state: ApprenticeshipState
    changed: StrictBool
    event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = ()
    ability_changes: tuple[AbilityChangeView, ...] = ()
    relationship_changes: tuple[RelationshipChangeView, ...] = ()


class ProgressionPolicy:
    def __init__(self, config: ProgressionConfig) -> None:
        self.config = config
        self._abilities = {item.ability_id: item for item in config.abilities}

    @classmethod
    def load_default(cls) -> "ProgressionPolicy":
        try:
            config = ProgressionConfig.model_validate_json(
                read_runtime_text(f"progression/{PROGRESSION_RESOURCE_NAME}")
            )
        except (ValueError, TypeError) as exc:
            raise ProgressionConfigError("progression policy is invalid") from exc
        return cls(config)

    def display_name(self, ability_id: AbilityId) -> str:
        return self._abilities[ability_id].display_name

    def level_for(self, proficiency: int) -> AbilityLevel:
        applicable = tuple(
            item
            for item in self.config.ability_levels
            if item.minimum_proficiency <= proficiency
        )
        return applicable[-1].level

    def initialize(self, player_id: str, occurred_at: datetime) -> ApprenticeshipState:
        abilities = tuple(
            AbilityState(
                ability_id=item.ability_id,
                proficiency=item.initial_proficiency,
                level=self.level_for(item.initial_proficiency),
                unlocked=item.unlocked,
            )
            for item in self.config.abilities
        )
        event = ApprenticeshipInitialized(
            sequence=1,
            player_id=player_id,
            occurred_at=occurred_at,
            teaching_stage=self.config.teaching_stage,
            initial_abilities=abilities,
            initial_relationship=self.config.initial_relationship,
        )
        return ApprenticeshipEventReplayer().replay((event,))

    def view(self, state: ApprenticeshipState) -> ApprenticeshipView:
        latest_reason = None
        for event in reversed(state.events):
            if isinstance(event, (AbilityProgressed, RelationshipChanged)):
                latest_reason = event.public_description
                break
            if isinstance(event, AbilityEvidenceRecorded):
                latest_reason = event.evidence.public_description
                break
        return ApprenticeshipView(
            teaching_stage=state.teaching_stage,
            abilities=tuple(
                self._ability_view(state, rule.ability_id)
                for rule in self.config.abilities
            ),
            affinity=state.relationship.affinity,
            trust=state.relationship.trust,
            recognition=state.relationship.recognition,
            latest_growth_reason=latest_reason,
            applied_episode_count=len(state.completed_source_sessions),
            revision=state.revision,
        )

    def _ability_view(
        self,
        state: ApprenticeshipState,
        ability_id: AbilityId,
    ) -> AbilityPublicView:
        ability = state.abilities[ability_id]
        return AbilityPublicView(
            ability_id=ability.ability_id,
            display_name=self.display_name(ability.ability_id),
            level=ability.level,
            proficiency=ability.proficiency,
            evidence_count=ability.evidence_count,
            unlocked=ability.unlocked,
        )


class ProgressionProjector:
    def __init__(self, policy: ProgressionPolicy) -> None:
        self.policy = policy
        self.replayer = ApprenticeshipEventReplayer()

    def project(
        self,
        state: ApprenticeshipState,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
    ) -> ProgressionProjectionResult:
        fingerprint = self.source_fingerprint(player, case, session)
        existing = next(
            (
                event
                for event in state.events
                if isinstance(event, EpisodeGrowthApplied)
                and event.source_session_id == session.session_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.source_case_id != session.case_id
                or existing.source_revision != session.revision
                or existing.source_fingerprint != fingerprint
            ):
                raise ProgressionSourceConflictError(
                    "projected source session no longer matches its receipt"
                )
            return ProgressionProjectionResult(state=state, changed=False)

        occurred_at = session.action_history[-1].occurred_at
        evidences = self._evidence(player, case, session, occurred_at)
        new_events = list(state.events)
        start_sequence = state.revision + 1
        for evidence in evidences:
            new_events.append(
                AbilityEvidenceRecorded(
                    sequence=len(new_events) + 1,
                    player_id=player.player_id,
                    occurred_at=evidence.occurred_at,
                    evidence=evidence,
                )
            )

        working = self.replayer.replay(tuple(new_events))
        ability_changes: list[AbilityChangeView] = []
        for ability_id in AbilityId:
            positive = sum(
                evidence.strength
                for evidence in evidences
                if evidence.ability_id is ability_id
                and evidence.polarity is EvidencePolarity.DEMONSTRATED
            )
            delta = min(
                positive,
                self.policy.config.maximum_positive_growth_per_ability_per_episode,
                100 - working.abilities[ability_id].proficiency,
            )
            if delta <= 0:
                continue
            before = working.abilities[ability_id]
            after_value = before.proficiency + delta
            matching_ids = tuple(
                evidence.evidence_id
                for evidence in evidences
                if evidence.ability_id is ability_id
                and evidence.polarity is EvidencePolarity.DEMONSTRATED
            )
            description = f"{self.policy.display_name(ability_id)}获得已提交病例证据，熟练度提升{delta}点。"
            event = AbilityProgressed(
                sequence=len(new_events) + 1,
                player_id=player.player_id,
                occurred_at=occurred_at,
                ability_id=ability_id,
                delta=delta,
                proficiency_before=before.proficiency,
                proficiency_after=after_value,
                level_before=before.level,
                level_after=self.policy.level_for(after_value),
                evidence_ids=matching_ids,
                public_reason_code="episode_evidence_progressed",
                public_description=description,
            )
            new_events.append(event)
            working = self.replayer.replay(tuple(new_events))
            ability_changes.append(
                AbilityChangeView(
                    ability_id=ability_id,
                    display_name=self.policy.display_name(ability_id),
                    proficiency_before=before.proficiency,
                    proficiency_after=after_value,
                    delta=delta,
                    public_description=description,
                )
            )

        relationship_changes: list[RelationshipChangeView] = []
        relation_rule = self._relationship_rule(session.outcome, session.score)
        for dimension in RelationshipDimension:
            requested_delta = getattr(relation_rule, dimension.value)
            before = getattr(working.relationship, dimension.value)
            after = max(0, min(100, before + requested_delta))
            delta = after - before
            if delta == 0:
                continue
            event = RelationshipChanged(
                sequence=len(new_events) + 1,
                player_id=player.player_id,
                occurred_at=occurred_at,
                dimension=dimension,
                delta=delta,
                value_before=before,
                value_after=after,
                public_reason_code=relation_rule.public_reason_code,
                public_description=relation_rule.public_description,
                source_case_id=case.case_id,
                source_session_id=session.session_id,
                source_event_sequence=session.revision,
            )
            new_events.append(event)
            working = self.replayer.replay(tuple(new_events))
            relationship_changes.append(
                RelationshipChangeView(
                    dimension=dimension,
                    value_before=before,
                    value_after=after,
                    delta=delta,
                    public_description=relation_rule.public_description,
                )
            )

        new_events.append(
            EpisodeGrowthApplied(
                sequence=len(new_events) + 1,
                player_id=player.player_id,
                occurred_at=occurred_at,
                source_case_id=case.case_id,
                source_session_id=session.session_id,
                source_revision=session.revision,
                source_event_sequences=tuple(range(1, session.revision + 1)),
                source_fingerprint=fingerprint,
                evidence_ids=tuple(item.evidence_id for item in evidences),
                ability_change_count=len(ability_changes),
                relationship_change_count=len(relationship_changes),
            )
        )
        updated = self.replayer.replay(tuple(new_events))
        return ProgressionProjectionResult(
            state=updated,
            changed=True,
            event_sequences=tuple(range(start_sequence, updated.revision + 1)),
            ability_changes=tuple(ability_changes),
            relationship_changes=tuple(relationship_changes),
        )

    def source_fingerprint(
        self,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
    ) -> str:
        if session.player_id != player.player_id:
            raise ProgressionSourceError("session player does not match trusted player")
        if session.case_id != case.case_id:
            raise ProgressionSourceError("session case does not match trusted case")
        if session.status is not CaseSessionStatus.COMPLETED:
            raise ProgressionSourceError("only completed sessions can produce growth")
        if (
            session.outcome is None
            or session.score is None
            or session.submitted_diagnosis_id is None
            or session.selected_treatment_id is None
            or session.revision != len(session.action_history)
            or not session.action_history
        ):
            raise ProgressionSourceError("completed session receipt is incomplete")
        discovered: set[str] = set()
        for record in session.action_history:
            if record.action_type in self.policy.config.investigation_action_ability_map:
                investigation = next(
                    (item for item in case.investigations if item.investigation_id == record.reference_id),
                    None,
                )
                if (
                    investigation is None
                    or investigation.action_type is not record.action_type
                    or investigation.target_id != record.target_id
                    or not record.revealed_clue_ids.issubset(investigation.reveals_clue_ids)
                ):
                    raise ProgressionSourceError("investigation receipt is invalid")
                discovered.update(record.revealed_clue_ids)
            elif record.action_type is CaseActionType.SUBMIT_DIAGNOSIS:
                if (
                    record.reference_id not in case.diagnosis_candidates
                    or record.target_id != record.reference_id
                    or not record.evidence_clue_ids.issubset(discovered)
                ):
                    raise ProgressionSourceError("diagnosis receipt is invalid")
            elif record.action_type is CaseActionType.EXECUTE_TREATMENT:
                if (
                    record.reference_id not in case.treatments
                    or record.target_id != record.reference_id
                ):
                    raise ProgressionSourceError("treatment receipt is invalid")
            else:
                raise ProgressionSourceError("unknown action receipt")
        final = session.action_history[-1]
        treatment = case.treatments.get(session.selected_treatment_id)
        if (
            final.action_type is not CaseActionType.EXECUTE_TREATMENT
            or final.reference_id != session.selected_treatment_id
            or treatment is None
            or treatment.outcome is not session.outcome
            or session.discovered_clue_ids != frozenset(discovered)
        ):
            raise ProgressionSourceError("final treatment receipt is inconsistent")
        public_payload = {
            "player_id": session.player_id,
            "case_id": session.case_id,
            "session_id": session.session_id,
            "revision": session.revision,
            "actions": [
                {
                    "sequence": item.sequence,
                    "action_type": item.action_type.value,
                    "reference_id": item.reference_id,
                    "target_id": item.target_id,
                    "revealed_clue_ids": sorted(item.revealed_clue_ids),
                    "evidence_clue_ids": sorted(item.evidence_clue_ids),
                    "occurred_at": item.occurred_at.isoformat(),
                }
                for item in session.action_history
            ],
            "diagnosis_id": session.submitted_diagnosis_id,
            "treatment_id": session.selected_treatment_id,
            "outcome": session.outcome.value,
            "score": session.score,
        }
        digest = hashlib.sha256(
            json.dumps(public_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32]
        return f"source_{digest}"

    def _evidence(
        self,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
        completed_at: datetime,
    ) -> tuple[AbilityEvidence, ...]:
        grouped: dict[AbilityId, list[int]] = {}
        for record in session.action_history:
            ability_id = self.policy.config.investigation_action_ability_map.get(
                record.action_type
            )
            if ability_id is not None:
                grouped.setdefault(ability_id, []).append(record.sequence)
        values: list[AbilityEvidence] = []
        for ability_id in AbilityId:
            sequences = grouped.get(ability_id, [])
            if sequences:
                values.append(
                    self._make_evidence(
                        player, case, session, ability_id,
                        EvidencePolarity.DEMONSTRATED,
                        min(len(sequences), 2),
                        "accepted_unique_investigation",
                        f"完成了与{self.policy.display_name(ability_id)}相关的有效调查。",
                        tuple(sequences), completed_at,
                    )
                )
        diagnosis_record = next(
            item for item in session.action_history
            if item.action_type is CaseActionType.SUBMIT_DIAGNOSIS
        )
        diagnosis_correct = session.submitted_diagnosis_id in case.valid_diagnosis_ids
        values.append(
            self._make_evidence(
                player, case, session, AbilityId.REASON_DIAGNOSIS,
                EvidencePolarity.DEMONSTRATED if diagnosis_correct else EvidencePolarity.NEEDS_IMPROVEMENT,
                2 if diagnosis_correct else 1,
                "diagnosis_positive" if diagnosis_correct else "diagnosis_needs_improvement",
                "最终辨证获得正向公开评价。" if diagnosis_correct else "本次正式辨证仍需改进。",
                (diagnosis_record.sequence, session.revision), completed_at,
            )
        )
        if session.outcome is TreatmentOutcome.RESOLVED:
            for ability_id, strength, code, description in (
                (AbilityId.APPLY_TREATMENT, 2, "treatment_resolved", "处置产生了圆满的公开结果。"),
                (AbilityId.ETHICAL_PRACTICE, 1, "safe_practice_resolved", "处置安全且与公开结果一致。"),
            ):
                values.append(self._make_evidence(
                    player, case, session, ability_id, EvidencePolarity.DEMONSTRATED,
                    strength, code, description, (session.revision,), completed_at,
                ))
        else:
            code = f"treatment_{session.outcome.value}_needs_improvement"
            description = "本次处置结果提示施治与守则仍需改进。"
            for ability_id in (AbilityId.APPLY_TREATMENT, AbilityId.ETHICAL_PRACTICE):
                values.append(self._make_evidence(
                    player, case, session, ability_id, EvidencePolarity.NEEDS_IMPROVEMENT,
                    1, code, description, (session.revision,), completed_at,
                ))
        return tuple(values)

    @staticmethod
    def _make_evidence(
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
        ability_id: AbilityId,
        polarity: EvidencePolarity,
        strength: int,
        code: str,
        description: str,
        sequences: tuple[int, ...],
        occurred_at: datetime,
    ) -> AbilityEvidence:
        unique_sequences = tuple(sorted(set(sequences)))
        key = "|".join((
            PROGRESSION_POLICY_VERSION, player.player_id, case.case_id,
            session.session_id, ability_id.value, polarity.value, code,
            ",".join(str(item) for item in unique_sequences), str(session.revision),
        ))
        evidence_id = f"evidence_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}"
        return AbilityEvidence(
            evidence_id=evidence_id,
            player_id=player.player_id,
            ability_id=ability_id,
            polarity=polarity,
            strength=strength,
            public_reason_code=code,
            public_description=description,
            source_case_id=case.case_id,
            source_session_id=session.session_id,
            source_event_sequences=unique_sequences,
            source_revision=session.revision,
            occurred_at=occurred_at,
        )

    def _relationship_rule(
        self,
        outcome: TreatmentOutcome | None,
        score: int | None,
    ) -> RelationshipRule:
        if outcome is None or score is None:
            raise ProgressionSourceError("completed result is unavailable")
        matches = tuple(
            item for item in self.policy.config.relationship_rules
            if item.outcome is outcome and item.minimum_score <= score <= item.maximum_score
        )
        if len(matches) != 1:
            raise ProgressionConfigError("relationship rules do not uniquely cover result")
        return matches[0]


class ProgressionCatalog(Protocol):
    def get(self, case_id: str) -> CaseDefinition | None: ...


class ApprenticeshipCoordinator:
    def __init__(
        self,
        store: JsonStateStore,
        catalog: ProgressionCatalog,
        policy: ProgressionPolicy,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.policy = policy
        self.projector = ProgressionProjector(policy)

    def initialize(self, player_id: str, occurred_at: datetime) -> ApprenticeshipState:
        state = self.policy.initialize(player_id, occurred_at)
        self.store.save_apprenticeship(state)
        return state

    def load_or_initialize(
        self,
        player_id: str,
        occurred_at: datetime,
        *,
        persist: bool = True,
    ) -> ApprenticeshipState:
        try:
            return self.store.load_apprenticeship(player_id)
        except StateNotFoundError:
            state = self.policy.initialize(player_id, occurred_at)
            if persist:
                self.store.save_apprenticeship(state)
            return state

    def project_completed(
        self,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
        occurred_at: datetime,
    ) -> ProgressionProjectionResult:
        state = self.load_or_initialize(player.player_id, occurred_at, persist=False)
        self._verify_existing_sources(player, state)
        result = self.projector.project(state, player, case, session)
        if result.changed or state.revision == 1 and not self._exists(player.player_id):
            self.store.save_apprenticeship(result.state)
        return result

    def reconcile(
        self,
        player: PlayerState,
        occurred_at: datetime,
    ) -> ProgressionProjectionResult:
        try:
            sessions = tuple(sorted(
                (
                    item for item in self.store.list_case_sessions()
                    if item.player_id == player.player_id
                    and item.status is CaseSessionStatus.COMPLETED
                ),
                key=lambda item: (item.action_history[-1].occurred_at, item.session_id),
            ))
        except StateCorruptionError as exc:
            raise ProgressionSourceConflictError("session storage is corrupted") from exc
        initialization_time = (
            sessions[0].action_history[-1].occurred_at if sessions else occurred_at
        )
        current = self.load_or_initialize(
            player.player_id,
            initialization_time,
            persist=False,
        )
        self._verify_existing_sources(player, current)
        updated = current
        all_sequences: list[int] = []
        ability_changes: list[AbilityChangeView] = []
        relationship_changes: list[RelationshipChangeView] = []
        for session in sessions:
            case = self.catalog.get(session.case_id)
            if case is None:
                raise ProgressionSourceError("completed session references unknown case")
            result = self.projector.project(updated, player, case, session)
            updated = result.state
            all_sequences.extend(result.event_sequences)
            ability_changes.extend(result.ability_changes)
            relationship_changes.extend(result.relationship_changes)
        changed = updated != current
        if changed or not self._exists(player.player_id):
            self.store.save_apprenticeship(updated)
        return ProgressionProjectionResult(
            state=updated,
            changed=changed,
            event_sequences=tuple(all_sequences),
            ability_changes=tuple(ability_changes),
            relationship_changes=tuple(relationship_changes),
        )

    def _verify_existing_sources(
        self,
        player: PlayerState,
        state: ApprenticeshipState,
    ) -> None:
        for event in state.events:
            if not isinstance(event, EpisodeGrowthApplied):
                continue
            try:
                session = self.store.load_case_session(event.source_session_id)
            except StateNotFoundError as exc:
                raise ProgressionSourceMissingError("growth source session is missing") from exc
            except StateCorruptionError as exc:
                raise ProgressionSourceConflictError("growth source session is corrupted") from exc
            case = self.catalog.get(event.source_case_id)
            if case is None:
                raise ProgressionSourceConflictError("growth source case is unavailable")
            fingerprint = self.projector.source_fingerprint(player, case, session)
            if (
                session.revision != event.source_revision
                or fingerprint != event.source_fingerprint
            ):
                raise ProgressionSourceConflictError("growth source no longer matches receipt")

    def _exists(self, player_id: str) -> bool:
        try:
            self.store.load_apprenticeship(player_id)
            return True
        except StateNotFoundError:
            return False
