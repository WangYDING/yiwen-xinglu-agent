"""Composition-only local clinic application service for ordinary players."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseActionType
from xuanyi_npc.domain.permissions import PermissionLevel
from xuanyi_npc.storage import JsonStateStore, StateNotFoundError

from .case_access import PermissionFilteredCaseCatalog
from .curriculum_v2 import CurriculumV2Recommendation, CurriculumV2Selector
from .exams import ExamService
from .inheritance import InheritanceService
from .multicase import (
    CampaignPlayerInput, CampaignRuleSet, CaseCatalog, CreatePlayerInput, ListCasesInput, ListPlayersInput,
    MultiCaseEpisodeService, ResumeEpisodeInput, StartEpisodeInput, SubmitActionInput,
)
from .permissions import PermissionCoordinator
from .teaching import MentorTeachingService
from .teaching import CreateTeachingSessionInput, TeachingRequest


class ClinicError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ClinicPlayerSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_id: Identifier
    display_name: NonEmptyText


class ClinicCaseView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: Identifier
    title: NonEmptyText
    synopsis: NonEmptyText
    status: str
    recommended: bool


class ClinicView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_summary: ClinicPlayerSummary
    mentor_summary: NonEmptyText
    teaching_stage: str
    current_recommendation: CurriculumV2Recommendation
    unresolved_remediations: tuple[Identifier, ...]
    abilities: tuple[dict[str, object], ...]
    relationship: dict[str, int]
    visible_cases: tuple[ClinicCaseView, ...]
    active_case: Identifier | None = None
    exam_status: str
    permissions: tuple[str, ...]
    inheritance_status: str
    recent_public_history: tuple[NonEmptyText, ...]
    pending_operations: tuple[Identifier, ...] = ()


class ClinicActionInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    operation_id: Identifier
    action_type: Literal["investigation", "diagnosis", "treatment"]
    selection_id: Identifier
    evidence_clue_ids: tuple[Identifier, ...] = ()


@dataclass
class ClinicService:
    store: JsonStateStore
    base_catalog: CaseCatalog
    campaign_path: object
    clock: object
    player_id_factory: object | None = None
    session_id_factory: object | None = None

    def __post_init__(self) -> None:
        kwargs = {"state_store": self.store, "case_catalog": self.base_catalog,
                  "campaign_rules": CampaignRuleSet.load(self.campaign_path, self.base_catalog),
                  "clock": self.clock}
        if self.player_id_factory is not None:
            kwargs["player_id_factory"] = self.player_id_factory
        if self.session_id_factory is not None:
            kwargs["session_id_factory"] = self.session_id_factory
        self.base_service = MultiCaseEpisodeService(**kwargs)
        self.permissions = PermissionCoordinator(self.store, self.clock)
        self.exams = ExamService(self.store, self.permissions, self.clock)
        self.inheritance = InheritanceService(self.store, self.permissions, self.clock)
        self.curriculum = CurriculumV2Selector()

    def create_player(self, display_name: str):
        result = self.base_service.create_player(CreatePlayerInput(display_name=display_name))
        if not result.ok or result.player_id is None:
            raise ClinicError("player_create_failed", result.message)
        self.permissions.ensure(result.player_id)
        return self.home(result.player_id)

    def list_players(self) -> tuple[ClinicPlayerSummary, ...]:
        result = self.base_service.list_players(ListPlayersInput())
        return tuple(ClinicPlayerSummary(player_id=item.player_id, display_name=item.display_name) for item in result.players)

    def _service(self, player_id: str) -> MultiCaseEpisodeService:
        permission = self.permissions.ensure(player_id)
        catalog = PermissionFilteredCaseCatalog(self.base_catalog, permission.permissions)
        kwargs = {"state_store": self.store, "case_catalog": catalog,
                  "campaign_rules": CampaignRuleSet.load(self.campaign_path, catalog),
                  "clock": self.clock}
        if self.session_id_factory is not None:
            kwargs["session_id_factory"] = self.session_id_factory
        return MultiCaseEpisodeService(**kwargs)

    def teaching_service(self, player_id: str) -> MentorTeachingService:
        return MentorTeachingService(case_service=self._service(player_id), mentor_agent=DeterministicFakeMentor())

    def home(self, player_id: str) -> ClinicView:
        try:
            player = self.store.load_player(player_id)
            apprenticeship = self.store.load_apprenticeship(player_id)
        except StateNotFoundError as exc:
            raise ClinicError("player_not_found", "未找到该弟子。") from exc
        teaching = self.teaching_service(player_id)
        plan = teaching.plan_service.ensure(player_id)
        permission = self.permissions.reconcile(player_id)
        service = self._service(player_id)
        cases = service.list_cases(ListCasesInput(player_id=player_id))
        campaign = service.get_campaign_view(CampaignPlayerInput(player_id=player_id))
        completed = frozenset(item.case_id for item in (campaign.campaign_view.completed_cases if campaign.campaign_view else ()))
        recommendation = self.curriculum.select(plan=plan, permission=permission, completed_case_ids=completed)
        active = next((item.case_id for item in cases.cases if item.play_status.value == "active"), None)
        history = tuple(
            item.public_text for item in (campaign.campaign_view.active_facts if campaign.campaign_view else ())
        )[-3:]
        return ClinicView(
            player_summary=ClinicPlayerSummary(player_id=player_id, display_name=player.display_name),
            mentor_summary="玄医先生会解释规则结果，但不会替你调查、作答或处置。",
            teaching_stage=permission.teaching_stage.value,
            current_recommendation=recommendation,
            unresolved_remediations=tuple(item.value for item in plan.unresolved_improvement_areas),
            abilities=tuple({"ability_id": key.value, "name": value.ability_id.value, "proficiency": value.proficiency} for key, value in apprenticeship.abilities.items()),
            relationship=apprenticeship.relationship.model_dump(),
            visible_cases=tuple(ClinicCaseView(case_id=item.case_id, title=item.title, synopsis=item.synopsis, status=item.play_status.value, recommended=item.is_recommended_next) for item in cases.cases),
            active_case=active,
            exam_status="passed" if permission.passed_exam_attempt_id else ("eligible" if permission.exam_eligible else "not_eligible"),
            permissions=tuple(item.value for item in sorted(permission.permissions, key=lambda value: value.value) if item is not PermissionLevel.MENTOR_SECRET),
            inheritance_status="granted" if permission.granted_inheritance_ids else "not_granted",
            recent_public_history=history,
        )

    def start_case(self, player_id: str, case_id: str):
        result = self._service(player_id).start_episode(StartEpisodeInput(player_id=player_id, case_id=case_id))
        if not result.ok:
            raise ClinicError(result.error_code or "case_start_failed", result.message)
        return result

    def resume_case(self, player_id: str, case_id: str, session_id: str):
        result = self._service(player_id).resume_episode(ResumeEpisodeInput(player_id=player_id, case_id=case_id, session_id=session_id))
        if not result.ok:
            raise ClinicError(result.error_code or "case_resume_failed", result.message)
        return result

    def submit_case_action(self, request: ClinicActionInput):
        from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
        service = self._service(request.player_id)
        case = service.case_catalog.get(request.case_id)
        if case is None:
            raise ClinicError("case_not_found", "病例不存在。")
        if request.action_type == "investigation":
            investigation = next((item for item in case.investigations if item.investigation_id == request.selection_id), None)
            if investigation is None:
                raise ClinicError("investigation_not_available", "该调查当前不可用。")
            tool = {CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT, CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT, CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT, CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI, CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION}[investigation.action_type]
            arguments = {"investigation_id": request.selection_id}
        elif request.action_type == "diagnosis":
            tool, arguments = ToolName.SUBMIT_DIAGNOSIS, {"diagnosis_id": request.selection_id, "evidence_clue_ids": list(request.evidence_clue_ids)}
        else:
            tool, arguments = ToolName.EXECUTE_TREATMENT, {"treatment_id": request.selection_id}
        action = AgentAction(action_id=request.operation_id, action_type=AgentActionType.USE_TOOL, dialogue="玩家通过医馆页面选择了公开行动。", tool_call=ToolCallRequest(name=tool, arguments=arguments), confidence=1.0)
        result = service.submit_action(SubmitActionInput(player_id=request.player_id, case_id=request.case_id, session_id=request.session_id, action=action))
        if not result.ok:
            raise ClinicError(result.error_code or "case_action_rejected", result.message)
        session = self.store.load_case_session(request.session_id)
        if session.status.value == "completed":
            teaching = self.teaching_service(request.player_id)
            created = teaching.create(CreateTeachingSessionInput(
                player_id=request.player_id, case_session_id=request.session_id,
            ))
            if created.ok and created.state is not None:
                teaching.observe_case_completion(TeachingRequest(
                    player_id=request.player_id,
                    teaching_session_id=created.state.teaching_session_id,
                ))
        return result
