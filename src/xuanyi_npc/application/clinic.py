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
from .clinic_mentor import ClinicMentorMode, ClinicMentorRuntime
from .public_presentation import PUBLIC_PRESENTATION


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
    mentor_runtime: ClinicMentorRuntime | None = None
    mentor_agent_factory: object | None = None

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
        factory = self.mentor_agent_factory or DeterministicFakeMentor
        return MentorTeachingService(case_service=self._service(player_id), mentor_agent=factory())

    @property
    def mentor_status(self):
        return (self.mentor_runtime.status if self.mentor_runtime is not None else
                {"mode":"fake","available":True,"used_cost":"0","remaining_budget":"0","fallback_active":False})

    def mentor_expression(self, player_id: str, request_id: str):
        """Generate language only from an authoritative public clinic projection."""
        runtime=self.mentor_runtime or ClinicMentorRuntime(ClinicMentorMode.FAKE,self.store.root)
        home=self.home(player_id)
        if request_id=="initial_lesson_hint_1":
            context={"mentor_role":"玄医先生是导师，玩家是需要亲自行动的弟子","lesson":{"title":"证据齐备再定证","goal":"区分事实、推断与诱饵，并只依据已发现证据判断","case_title":"旧纸伞"},"player_request":"请给我一次提示，但不要告诉我诊断或处置答案。","allowed_hint_cards":[{"hint_id":"hint_1","text":"请检查当前仍未覆盖的公开调查类别；先补足事实，不急于定性。"}]}
        elif request_id=="wrong_diagnosis_remediation_1":
            recommendation=home.current_recommendation.recommendation_id
            if recommendation!="remediate_diagnostic_reasoning_v1":raise ClinicError("mentor_interaction_unavailable","当前没有辨证补课需要解释。")
            context={"case_title":"旧纸伞","submitted_result":"玩家提交了合法但错误的诊断；辨证能力没有因此增加","public_improvement_area":PUBLIC_PRESENTATION.public_object("ability","reason_diagnosis"),"assigned_remediation":PUBLIC_PRESENTATION.public_object("remediation",recommendation),"deterministic_curriculum_decision":{"title":PUBLIC_PRESENTATION.name("remediation",recommendation),"effect":"补课本身不直接增加能力"}}
        elif request_id=="exam_failure_explanation_1":
            attempts=sorted((x for x in self.store.list_exam_sessions() if x.player_id==player_id and x.result is not None),key=lambda x:x.attempt_number)
            if not attempts or attempts[-1].result.passed:raise ClinicError("mentor_interaction_unavailable","当前没有考试失败结果需要解释。")
            result=attempts[-1].result
            context={"exam_result":{"passed":False,"total_score":result.total_score,"critical_failure":result.critical_failure,"public_improvement_areas":[PUBLIC_PRESENTATION.public_object("ability",x.value) for x in result.improvement_areas],"assigned_remediations":[PUBLIC_PRESENTATION.public_object("remediation",x) for x in result.required_remediation_ids]},"deterministic_decision":"考试失败；补课完成前不能重考；分数与通过状态不可由导师修改"}
        elif request_id=="inheritance_refusal_1":
            decision=self.inheritance.policy.decide(player_id)
            if decision.eligible:raise ClinicError("mentor_interaction_unavailable","当前传承决定不是拒绝。")
            context={"same_player_state":"before_requirements_met","deterministic_decision":"refused","public_reason_categories":list(decision.missing_requirement_categories),"instruction":"只解释公开类别，不披露精确数值门槛；语言说明不构成权限"}
        elif request_id=="inheritance_grant_1":
            permission=self.permissions.public_view(player_id)
            if not permission.granted_inheritance_ids:raise ClinicError("mentor_interaction_unavailable","当前尚无已授予传承。")
            context={"same_player_state":"after_requirements_met","deterministic_decision":"granted_once","public_grant":{"inheritance_title":"溯契还因","permission_name":PUBLIC_PRESENTATION.name("permission","INHERITANCE"),"duplicate_grant":False},"instruction":"解释规则层已经授予；导师语言不创建或重复写入权限"}
        else:raise ClinicError("mentor_interaction_unplanned","该交互继续使用本地确定性说明。")
        return runtime.express(request_id,context)

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
            abilities=tuple({"ability_id": key.value, "name": PUBLIC_PRESENTATION.name("ability", value.ability_id.value), "proficiency": value.proficiency} for key, value in apprenticeship.abilities.items()),
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
