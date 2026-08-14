"""Atomic JSON persistence for player and case-session state."""

from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from xuanyi_npc.domain.base import Identifier
from xuanyi_npc.domain.apprenticeship import (
    ApprenticeshipEventReplayer,
    ApprenticeshipReplayError,
    ApprenticeshipState,
)
from xuanyi_npc.domain.campaign import CampaignState
from xuanyi_npc.domain.cases import CaseSessionState
from xuanyi_npc.domain.player import PlayerState
from xuanyi_npc.domain.teaching import (
    TeachingEventReplayer,
    TeachingReplayError,
    TeachingSessionState,
)
from xuanyi_npc.domain.teaching_plan import (
    TeachingPlanEventReplayer,
    TeachingPlanReplayError,
    TeachingPlanState,
)
from xuanyi_npc.domain.exams import ExamEventReplayer, ExamReplayError, ExamSessionState
from xuanyi_npc.domain.permissions import (
    PermissionEventReplayer,
    PermissionPolicy,
    PermissionReplayError,
    PermissionState,
)
from xuanyi_npc.resources.runtime import read_runtime_text


class StorageError(RuntimeError):
    """Base error for state persistence failures."""


class StateNotFoundError(StorageError):
    """Raised when a requested state snapshot does not exist."""


class StateCorruptionError(StorageError):
    """Raised when stored JSON cannot be parsed as the expected model."""


ModelT = TypeVar("ModelT", bound=BaseModel)
_identifier_adapter = TypeAdapter(Identifier)


class JsonStateStore:
    """Small M0 store with atomic replacement and typed load boundaries."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def save_player(self, state: PlayerState) -> Path:
        return self._write("players", state.player_id, state)

    def load_player(self, player_id: str) -> PlayerState:
        return self._read("players", player_id, PlayerState)

    def save_case_session(self, state: CaseSessionState) -> Path:
        return self._write("case_sessions", state.session_id, state)

    def load_case_session(self, session_id: str) -> CaseSessionState:
        return self._read("case_sessions", session_id, CaseSessionState)

    def save_campaign(self, state: CampaignState) -> Path:
        return self._write("campaigns", state.player_id, state)

    def load_campaign(self, player_id: str) -> CampaignState:
        return self._read("campaigns", player_id, CampaignState)

    def save_apprenticeship(self, state: ApprenticeshipState) -> Path:
        replayed = ApprenticeshipEventReplayer().replay(state.events)
        if replayed != state:
            raise StateCorruptionError("apprenticeship snapshot does not match replay")
        return self._write("apprenticeships", state.player_id, state)

    def load_apprenticeship(self, player_id: str) -> ApprenticeshipState:
        source=self._path("apprenticeships",player_id)
        try: raw=json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc: raise StateNotFoundError("apprenticeships state does not exist") from exc
        except (OSError,ValueError) as exc: raise StateCorruptionError("apprenticeships state is invalid") from exc
        migrated=False
        if "observe_qi" not in raw.get("abilities",{}):
            initial=raw["events"][0];initial["initial_abilities"].append({"ability_id":"observe_qi","proficiency":0,"level":"unlearned","evidence_count":0,"latest_evidence_at":None,"unlocked":False})
            initial["schema_version"]="apprenticeship_state_v2";initial["progression_version"]="apprenticeship_progression_v2";raw["schema_version"]="apprenticeship_state_v2";raw["progression_version"]="apprenticeship_progression_v2"
            try:
                player=self.load_player(player_id);legacy=player.skills.get("observe_qi")
                value=legacy.proficiency if legacy and legacy.unlocked else 0;unlocked=bool(legacy and legacy.unlocked)
            except (StateNotFoundError,StateCorruptionError): value=0;unlocked=False
            sources=["legacy_player_skill_observe_qi",*(f"legacy_session_{x}" for x in raw.get("completed_source_sessions",[]))] if unlocked else []
            event={"event_type":"ability_schema_migrated","sequence":len(raw["events"])+1,"player_id":player_id,"occurred_at":raw["updated_at"],"from_schema_version":"six_ability_v1","added_ability_id":"observe_qi","migrated_proficiency":value,"migrated_unlocked":unlocked,"trusted_source_event_ids":sources,"public_description":"依据旧版玩家技能与已提交病例回执迁移观炁状态；未读取聊天内容。"}
            raw["events"].append(event);raw["abilities"]["observe_qi"]={"ability_id":"observe_qi","proficiency":value,"level":("novice" if value>=10 else "introduced" if value else "unlearned"),"evidence_count":0,"latest_evidence_at":None,"unlocked":unlocked};raw["revision"]=len(raw["events"]);migrated=True
        try: state=ApprenticeshipState.model_validate(raw)
        except (ValidationError,ValueError) as exc: raise StateCorruptionError("apprenticeships state is invalid") from exc
        try:
            replayed = ApprenticeshipEventReplayer().replay(state.events)
        except ApprenticeshipReplayError as exc:
            raise StateCorruptionError("apprenticeship event stream is invalid") from exc
        if replayed != state:
            raise StateCorruptionError("apprenticeship snapshot does not match replay")
        if migrated:self.save_apprenticeship(state)
        return state

    def save_teaching_session(self, state: TeachingSessionState) -> Path:
        replayed = TeachingEventReplayer().replay(state.events)
        if replayed != state:
            raise StateCorruptionError("teaching snapshot does not match replay")
        return self._write("teaching_sessions", state.teaching_session_id, state)

    def load_teaching_session(self, teaching_session_id: str) -> TeachingSessionState:
        state = self._read("teaching_sessions", teaching_session_id, TeachingSessionState)
        try:
            replayed = TeachingEventReplayer().replay(state.events)
        except TeachingReplayError as exc:
            raise StateCorruptionError("teaching event stream is invalid") from exc
        if replayed != state:
            raise StateCorruptionError("teaching snapshot does not match replay")
        return state

    def save_teaching_plan(self, state: TeachingPlanState) -> Path:
        replayed = TeachingPlanEventReplayer().replay(state.events)
        if replayed != state:
            raise StateCorruptionError("teaching plan snapshot does not match replay")
        return self._write("teaching_plans", state.player_id, state)

    def load_teaching_plan(self, player_id: str) -> TeachingPlanState:
        state = self._read("teaching_plans", player_id, TeachingPlanState)
        try:
            replayed = TeachingPlanEventReplayer().replay(state.events)
        except TeachingPlanReplayError as exc:
            raise StateCorruptionError("teaching plan event stream is invalid") from exc
        if replayed != state:
            raise StateCorruptionError("teaching plan snapshot does not match replay")
        return state

    def save_exam_session(self, state: ExamSessionState) -> Path:
        replayed = ExamEventReplayer().replay(state.events)
        if replayed != state:
            raise StateCorruptionError("exam snapshot does not match replay")
        return self._write("exam_sessions", state.exam_session_id, state)

    def load_exam_session(self, exam_session_id: str) -> ExamSessionState:
        state = self._read("exam_sessions", exam_session_id, ExamSessionState)
        try:
            replayed = ExamEventReplayer().replay(state.events)
        except ExamReplayError as exc:
            raise StateCorruptionError("exam event stream is invalid") from exc
        if replayed != state:
            raise StateCorruptionError("exam snapshot does not match replay")
        return state

    @staticmethod
    def _permission_replayer() -> PermissionEventReplayer:
        policy = PermissionPolicy.model_validate_json(
            read_runtime_text("permissions/permission_policy_v1.json")
        )
        return PermissionEventReplayer(policy)

    def save_permission_state(self, state: PermissionState) -> Path:
        replayed = self._permission_replayer().replay(state.events)
        if replayed != state:
            raise StateCorruptionError("permission snapshot does not match replay")
        return self._write("permissions", state.player_id, state)

    def load_permission_state(self, player_id: str) -> PermissionState:
        state = self._read("permissions", player_id, PermissionState)
        try:
            replayed = self._permission_replayer().replay(state.events)
        except PermissionReplayError as exc:
            raise StateCorruptionError("permission event stream is invalid") from exc
        if replayed != state:
            raise StateCorruptionError("permission snapshot does not match replay")
        return state

    def list_players(self) -> tuple[PlayerState, ...]:
        """Return all validated player snapshots in stable ID order."""

        return self._list("players", PlayerState, "player_id")

    def list_case_sessions(self) -> tuple[CaseSessionState, ...]:
        """Return all validated case sessions in stable ID order."""

        return self._list("case_sessions", CaseSessionState, "session_id")

    def list_campaigns(self) -> tuple[CampaignState, ...]:
        """Return all validated Campaign snapshots in stable player order."""

        return self._list("campaigns", CampaignState, "player_id")

    def list_apprenticeships(self) -> tuple[ApprenticeshipState, ...]:
        directory=self.root/"apprenticeships"
        if not directory.exists():return ()
        values=tuple(self.load_apprenticeship(path.stem) for path in sorted(directory.glob("*.json"),key=lambda item:item.name))
        for value in values:
            try:
                replayed = ApprenticeshipEventReplayer().replay(value.events)
            except ApprenticeshipReplayError as exc:
                raise StateCorruptionError("apprenticeship event stream is invalid") from exc
            if replayed != value:
                raise StateCorruptionError("apprenticeship snapshot does not match replay")
        return values

    def list_teaching_sessions(self) -> tuple[TeachingSessionState, ...]:
        values = self._list(
            "teaching_sessions", TeachingSessionState, "teaching_session_id"
        )
        for value in values:
            try:
                replayed = TeachingEventReplayer().replay(value.events)
            except TeachingReplayError as exc:
                raise StateCorruptionError("teaching event stream is invalid") from exc
            if replayed != value:
                raise StateCorruptionError("teaching snapshot does not match replay")
        return values

    def list_teaching_plans(self) -> tuple[TeachingPlanState, ...]:
        values = self._list("teaching_plans", TeachingPlanState, "player_id")
        for value in values:
            try:
                replayed = TeachingPlanEventReplayer().replay(value.events)
            except TeachingPlanReplayError as exc:
                raise StateCorruptionError("teaching plan event stream is invalid") from exc
            if replayed != value:
                raise StateCorruptionError("teaching plan snapshot does not match replay")
        return values

    def list_exam_sessions(self) -> tuple[ExamSessionState, ...]:
        values = self._list("exam_sessions", ExamSessionState, "exam_session_id")
        for value in values:
            if ExamEventReplayer().replay(value.events) != value:
                raise StateCorruptionError("exam snapshot does not match replay")
        return values

    def list_permission_states(self) -> tuple[PermissionState, ...]:
        values = self._list("permissions", PermissionState, "player_id")
        for value in values:
            if self._permission_replayer().replay(value.events) != value:
                raise StateCorruptionError("permission snapshot does not match replay")
        return values

    def _path(self, namespace: str, identifier: str) -> Path:
        try:
            safe_identifier = _identifier_adapter.validate_python(identifier)
        except ValidationError as exc:
            raise StorageError("state identifier is invalid") from exc
        return self.root / namespace / f"{safe_identifier}.json"

    def _write(self, namespace: str, identifier: str, state: BaseModel) -> Path:
        target = self._path(namespace, identifier)
        temp_path: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = state.model_dump_json(indent=2)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise StorageError(f"failed to save {namespace} state") from exc
        return target

    def _read(
        self,
        namespace: str,
        identifier: str,
        model_type: type[ModelT],
    ) -> ModelT:
        source = self._path(namespace, identifier)
        try:
            payload = source.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise StateNotFoundError(f"{namespace} state does not exist") from exc
        except OSError as exc:
            raise StorageError(f"failed to read {namespace} state") from exc

        try:
            return model_type.model_validate_json(payload)
        except (ValidationError, ValueError) as exc:
            raise StateCorruptionError(f"{namespace} state is invalid") from exc

    def _list(
        self,
        namespace: str,
        model_type: type[ModelT],
        identifier_field: str,
    ) -> tuple[ModelT, ...]:
        directory = self.root / namespace
        try:
            if not directory.exists():
                return ()
            if not directory.is_dir():
                raise StateCorruptionError(f"{namespace} state namespace is invalid")
            paths = tuple(sorted(directory.glob("*.json"), key=lambda path: path.name))
        except OSError as exc:
            raise StorageError(f"failed to list {namespace} state") from exc

        items: list[ModelT] = []
        for path in paths:
            try:
                payload = path.read_text(encoding="utf-8")
                item = model_type.model_validate_json(payload)
            except OSError as exc:
                raise StorageError(f"failed to read {namespace} state") from exc
            except (ValidationError, ValueError) as exc:
                raise StateCorruptionError(f"{namespace} state is invalid") from exc
            if getattr(item, identifier_field) != path.stem:
                raise StateCorruptionError(
                    f"{namespace} snapshot identifier does not match its file"
                )
            items.append(item)
        return tuple(items)
