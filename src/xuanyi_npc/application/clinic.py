"""Composition-only local clinic application service for ordinary players."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from xuanyi_npc.agents import DeterministicCooperativeNPC, DeterministicFakeMentor
from xuanyi_npc.domain.cooperation import (
    CooperativeTurnResult,
    PendingActionConfirmation,
    PlayerContribution,
    PlayerContributionType,
)
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
from .case_mentor import (AbilityStatus, CaseDialogueStore, DeterministicCaseMentor, RealModelCaseMentor,
    ChatMessage, DialogueTurn, MentorCaseContext, asks_participant_identity, case_participants, load_guides, validate_reply)
from .case_mentor import MentorInterventionPolicy
from .case_mentor import MentorWorkingMemoryStore, update_working_memory, working_memory_view
from .player_experience import classify_case_message, propose_investigation
from .cooperative_runtime import CooperativeRuntime, CooperativeTurnInput


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


class ClinicContributionInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    operation_id: Identifier
    text: NonEmptyText
    contribution_type: PlayerContributionType = PlayerContributionType.SUGGESTION
    responds_to_decision_id: Identifier | None = None
    pending_confirmation_id: Identifier | None = None


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
    game_npc_agent: object | None = None
    legacy_auto_foundation: bool = False

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
        self.case_guides = load_guides()
        self.case_dialogues = CaseDialogueStore(self.store.root)
        self.case_mentor_agent = (RealModelCaseMentor(self.mentor_runtime)
            if self.mentor_runtime is not None and self.mentor_runtime.mode is ClinicMentorMode.DEEPSEEK
            else DeterministicCaseMentor())
        self.mentor_interventions=MentorInterventionPolicy()
        self.mentor_working_memory=MentorWorkingMemoryStore(self.store.root)
        self.game_npc_agent = self.game_npc_agent or DeterministicCooperativeNPC()
        self.cooperative_pending: dict[str, PendingActionConfirmation] = {}

    def create_player(self, display_name: str):
        result = self.base_service.create_player(CreatePlayerInput(display_name=display_name))
        if not result.ok or result.player_id is None:
            raise ClinicError("player_create_failed", result.message)
        self.permissions.ensure(result.player_id)
        if self.legacy_auto_foundation:
            for exercise in self.base_service.progression_policy.config.foundation_exercises:
                self.base_service.complete_foundation_exercise(result.player_id,exercise.exercise_id,exercise.required_action_id)
        return self.home(result.player_id)

    def complete_foundation_exercise(self,player_id:str,exercise_id:str,action_id:str):
        result=self.base_service.complete_foundation_exercise(player_id,exercise_id,action_id)
        if not result.ok:raise ClinicError(result.error_code or "foundation_rejected",result.message)
        return result.apprenticeship_view

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
            abilities=tuple({"ability_id": key.value, "name": PUBLIC_PRESENTATION.name("ability", value.ability_id.value), "proficiency": value.proficiency,"level":value.level.value,"level_name":(self.base_service.progression_policy.level_rule_for(value.proficiency).public_name or value.level.value),"level_description":(self.base_service.progression_policy.level_rule_for(value.proficiency).public_description or ""),"unlocked":value.unlocked} for key, value in apprenticeship.abilities.items()),
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
        self.teaching_service(player_id).create(CreateTeachingSessionInput(player_id=player_id,case_session_id=result.session_id))
        self.mentor_intervention(player_id,case_id,result.session_id,"case_started",event_key="started")
        return result

    def case_experience(self, player_id: str, case_id: str, session_id: str):
        resumed=self.resume_case(player_id,case_id,session_id)
        session=self.store.load_case_session(session_id); case=self._service(player_id).case_catalog.get(case_id)
        guide=self.case_guides[case_id]
        performed={x.reference_id for x in session.action_history}
        stages=[]; current=guide.stages[-1]
        for stage in guide.stages:
            done=set(stage.completion_requirement_ids).issubset(performed)
            stages.append((stage,done))
            if not done and current is guide.stages[-1]: current=stage
        dialogue=self.case_dialogues.load(session_id,player_id,case_id)
        if not dialogue.current_target:
            dialogue=dialogue.model_copy(update={"current_target":case.patient.patient_id})
        abilities=tuple(AbilityStatus(ability_id=x["ability_id"],name=x["name"],proficiency=x["proficiency"],level=x["level"],unlocked=x["unlocked"],executable=x["unlocked"],reason=("" if x["unlocked"] else "尚未掌握")) for x in self.home(player_id).abilities)
        return resumed,guide,tuple(stages),current,dialogue,abilities

    def case_chat_message(self,player_id:str,case_id:str,session_id:str,operation_id:str,raw_message:str):
        resumed,guide,stages,current,dialogue,abilities=self.case_experience(player_id,case_id,session_id)
        participants=case_participants(case_id)
        classification=classify_case_message(raw_message,dialogue.current_target,participants)
        recipient=classification.recipient_id or "system";text=classification.message_text
        player_msg=ChatMessage(speaker_id="player",recipient_id=recipient,message_type="player",public_text=text)
        memory_proposal=None
        if classification.intent=="clarification_needed":
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=classification.message)
        elif classification.intent=="off_topic":
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text="此事与当前异象关系不明。请围绕受影响者、契物、现场痕迹或炁息说明要查什么。")
            dialogue=dialogue.model_copy(update={"off_track_count":dialogue.off_track_count+1})
        elif classification.intent in {"diagnosis_statement","treatment_statement"}:
            label="辨证" if classification.intent=="diagnosis_statement" else "处置"
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="system",public_text=f"已识别为{label}陈述。请在“辨证与处置”抽屉中核对系统理解并确认；本条消息没有直接执行。")
        elif classification.intent=="mentor_message":
            decision=self.mentor_interventions.decide("player_mentioned_mentor",dialogue)
            reply,_=self.mentor_case_message(player_id,case_id,session_id,text,trigger_type="player_mentioned_mentor",allowed_actions=decision.rule.allowed_action_types)
            dialogue=self.case_dialogues.load(session_id,player_id,case_id)
            response=ChatMessage(speaker_id="mentor",recipient_id="player",message_type="mentor_private",public_text=reply.message)
            memory_proposal=reply.memory_update_proposal
        elif classification.intent=="investigation_action":
            case=self._service(player_id).case_catalog.get(case_id)
            proposal=propose_investigation(text,case.investigations)
            if proposal.kind!="investigation":
                response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=proposal.message)
            else:
                before={x.clue_id for x in resumed.observation.discovered_clues}
                try:self.submit_case_action(ClinicActionInput(player_id=player_id,case_id=case_id,session_id=session_id,operation_id=operation_id,action_type="investigation",selection_id=proposal.selection_id))
                except ClinicError as exc:
                    response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=str(exc))
                    if exc.code in {"skill_locked","insufficient_skill"}:
                        interim=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,player_msg,response)[-16:],"revision":dialogue.revision+1})
                        self.case_dialogues.save(interim);self.mentor_intervention(player_id,case_id,session_id,"action_rejected_for_ability",event_key=operation_id);return response,self.case_dialogues.load(session_id,player_id,case_id)
                else:
                    after=self.resume_case(player_id,case_id,session_id).observation
                    revealed=[x.description for x in after.discovered_clues if x.clue_id not in before]
                    response=ChatMessage(speaker_id="system",recipient_id="player",message_type="clue",public_text=("调查结果："+"；".join(revealed)) if revealed else "这项调查先前已经完成，没有新增线索。")
                    dialogue=dialogue.model_copy(update={"off_track_count":0})
        else:
            case=self._service(player_id).case_catalog.get(case_id)
            participant=next(x for x in participants if x.participant_id==recipient)
            targeted=tuple(x for x in case.investigations if x.target_id==recipient)
            global_proposal=propose_investigation(text,case.investigations)
            if asks_participant_identity(text):
                response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="known_complete_answer",public_text=participant.public_intro)
                dialogue=dialogue.model_copy(update={"off_track_count":0})
            elif any(word in text for word in ("正确辨证","正确处置","直接告诉我真相","替我隐瞒")):
                response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="refuses_to_answer",public_text="这不是我能替你断定或隐瞒的事。你若要查案，请问我亲眼所见的经过。")
            elif not targeted:
                response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="understood_but_unknown",public_text="这件事我没有看清，你可以问某位可能知情的人。")
            else:
                generic=set("我你他她它的是了和与在问询请想要查核对什么如何情况")
                topical=max((len((set(text)-generic)&(set(x.public_description)-generic)) for x in targeted),default=0)
                proposal=propose_investigation(text,targeted) if topical>=2 else None
                if proposal is None or proposal.kind!="investigation":
                    if global_proposal.kind=="investigation":
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="understood_but_unknown",public_text="这件事我没有看清，你可以问某位可能知情的人。")
                    else:
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="clarification_needed",public_text="我没听明白你具体想核对什么。请说明事件、时间或你要确认的事实。")
                        dialogue=dialogue.model_copy(update={"off_track_count":dialogue.off_track_count+1})
                else:
                    before={x.clue_id for x in resumed.observation.discovered_clues}
                    if proposal.selection_id in {x.reference_id for x in self.store.load_case_session(session_id).action_history}:
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="known_complete_answer",public_text="这部分情况先前已经核对过，没有新增事实。")
                    else:
                        try:self.submit_case_action(ClinicActionInput(player_id=player_id,case_id=case_id,session_id=session_id,operation_id=operation_id,action_type="investigation",selection_id=proposal.selection_id))
                        except ClinicError as exc:
                            if exc.code in {"skill_locked","insufficient_skill"}:
                                response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=str(exc))
                                interim=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,player_msg,response)[-16:],"revision":dialogue.revision+1})
                                self.case_dialogues.save(interim);self.mentor_intervention(player_id,case_id,session_id,"action_rejected_for_ability",event_key=operation_id);return response,self.case_dialogues.load(session_id,player_id,case_id)
                            raise
                        after=self.resume_case(player_id,case_id,session_id).observation
                        revealed=[x.description for x in after.discovered_clues if x.clue_id not in before]
                        answer_type="known_complete_answer" if revealed else "known_partial_answer"
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type=answer_type,public_text=("据我所知，"+"；".join(revealed)) if revealed else "我只记得这些，暂时想不起更多细节。")
                    dialogue=dialogue.model_copy(update={"off_track_count":0})
            dialogue=dialogue.model_copy(update={"current_target":recipient})
        updated=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,player_msg,response)[-16:],"revision":dialogue.revision+1})
        self.case_dialogues.save(updated)
        self._update_working_memory(player_id,case_id,session_id,(player_msg,response),recipient,updated.off_track_count,memory_proposal)
        if updated.off_track_count>=2:self.mentor_intervention(player_id,case_id,session_id,"repeated_off_topic",event_key=str(updated.off_track_count))
        return response,self.case_dialogues.load(session_id,player_id,case_id)

    def mentor_case_message(self,player_id:str,case_id:str,session_id:str,message:str,trigger_type="player_mentioned_mentor",allowed_actions=("speak","ask_reflection")):
        resumed,guide,stages,current,dialogue,abilities=self.case_experience(player_id,case_id,session_id)
        session=self.store.load_case_session(session_id);case=self._service(player_id).case_catalog.get(case_id)
        performed=tuple(dict.fromkeys(x.action_type.value for x in session.action_history))
        recent=tuple(DialogueTurn(role=("player" if x.message_type=="player" else "mentor" if x.message_type=="mentor_private" else "case_npc"),text=x.public_text) for x in dialogue.recent_messages[-8:])
        context=MentorCaseContext(player_message=message,case_title=case.title,case_synopsis=case.synopsis,
            learning_goal=guide.learning_goal,current_stage_title=current.title,current_stage_purpose=current.public_purpose,
            completed_investigation_types=performed,discovered_clues=tuple(x.description for x in resumed.observation.discovered_clues),
            ability_statuses=abilities,recent_dialogue=recent,off_track_count=dialogue.off_track_count,
            allowed_hint_texts=tuple(x.text for x in case.hints[:1]),diagnosis_ready=resumed.observation.can_submit_diagnosis,
            treatment_ready=bool(resumed.observation.available_treatments))
        working=self.mentor_working_memory.load(session_id,player_id,case_id)
        public_facts=tuple(x.description for x in resumed.observation.discovered_clues)
        context=context.model_copy(update={"trigger_type":trigger_type,"allowed_mentor_action_types":tuple(allowed_actions),"working_memory":working_memory_view(working,public_facts)})
        forbidden=tuple(x.description for k,x in case.clues.items() if k not in session.discovered_clue_ids)+tuple(x.public_description for x in case.diagnosis_candidates.values())+tuple(x.public_description for x in case.treatments.values())
        try: reply=validate_reply(context,self.case_mentor_agent.respond(context),forbidden)
        except Exception: reply=DeterministicCaseMentor().respond(context.model_copy(update={"off_track_count":max(2,context.off_track_count)}))
        turns=(*dialogue.recent_mentor_turns,DialogueTurn(role="player",text=message),DialogueTurn(role="mentor",text=reply.message))[-8:]
        updated=dialogue.model_copy(update={"recent_mentor_turns":turns,"revision":dialogue.revision+1})
        self.case_dialogues.save(updated)
        return reply,updated

    def mentor_intervention(self,player_id,case_id,session_id,trigger_type,event_key=""):
        dialogue=self.case_dialogues.load(session_id,player_id,case_id)
        decision=self.mentor_interventions.decide(trigger_type,dialogue,event_key)
        if not decision.should_speak:return None,dialogue
        reply,_=self.mentor_case_message(player_id,case_id,session_id,f"规则事件：{trigger_type}",trigger_type=trigger_type,allowed_actions=decision.rule.allowed_action_types)
        dialogue=self.case_dialogues.load(session_id,player_id,case_id)
        msg=ChatMessage(speaker_id="mentor",recipient_id="player",message_type="mentor_private",public_text=reply.message)
        keys=dialogue.intervention_keys+((decision.dedupe_key,) if decision.dedupe_key else ())
        updated=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,msg)[-16:],"intervention_keys":keys,"revision":dialogue.revision+1})
        self.case_dialogues.save(updated)
        self._update_working_memory(player_id,case_id,session_id,(msg,),"player",updated.off_track_count,reply.memory_update_proposal,closed=trigger_type=="case_completed")
        return reply,updated

    def _update_working_memory(self,player_id,case_id,session_id,messages,recipient,off_track,proposal=None,closed=False):
        state=self.mentor_working_memory.load(session_id,player_id,case_id)
        state=update_working_memory(state,messages,recipient_id=recipient,off_track_count=off_track,proposal=proposal,closed=closed)
        self.mentor_working_memory.save(state);return state

    def resume_case(self, player_id: str, case_id: str, session_id: str):
        result = self._service(player_id).resume_episode(ResumeEpisodeInput(player_id=player_id, case_id=case_id, session_id=session_id))
        if not result.ok:
            raise ClinicError(result.error_code or "case_resume_failed", result.message)
        return result

    def submit_player_contribution(self, request: ClinicContributionInput) -> CooperativeTurnResult:
        pending = None
        if request.pending_confirmation_id is not None:
            pending = self.cooperative_pending.get(request.pending_confirmation_id)
            if pending is None:
                raise ClinicError("confirmation_unavailable", "该协商请求已失效，请依据最新病例状态重新讨论。")
            if (pending.player_id, pending.case_id, pending.session_id) != (
                request.player_id, request.case_id, request.session_id
            ):
                raise ClinicError("confirmation_ownership_mismatch", "该协商请求不属于当前玩家或病例。")
        contribution = PlayerContribution(
            contribution_id=request.operation_id,
            player_id=request.player_id,
            case_id=request.case_id,
            session_id=request.session_id,
            contribution_type=request.contribution_type,
            public_text=request.text,
            responds_to_decision_id=request.responds_to_decision_id,
            created_at=self.clock.now(),
        )
        runtime = CooperativeRuntime(
            service=self._service(request.player_id),
            agent=self.game_npc_agent,
        )
        result = runtime.handle(CooperativeTurnInput(contribution=contribution, pending_action=pending))
        if pending is not None:
            self.cooperative_pending.pop(pending.confirmation_id, None)
        if result.pending_action is not None:
            self.cooperative_pending[result.pending_action.confirmation_id] = result.pending_action
        return result

    def submit_case_action(self, request: ClinicActionInput):
        from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
        service = self._service(request.player_id)
        apprenticeship=self.store.load_apprenticeship(request.player_id)
        gate={"diagnosis":"reason_diagnosis","treatment":"apply_treatment"}.get(request.action_type)
        if gate and not apprenticeship.abilities[gate].unlocked:
            raise ClinicError("ability_locked",f"{PUBLIC_PRESENTATION.name('ability',gate)}尚未掌握，请先完成对应入门练习。")
        if request.action_type=="treatment" and not apprenticeship.abilities["ethical_practice"].unlocked:
            raise ClinicError("ability_locked","守则尚未掌握，不能执行不可逆处置。")
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
            if request.action_type=="diagnosis" and result.error_code in {"diagnosis_not_ready","evidence_not_discovered"}:
                self.mentor_intervention(request.player_id,request.case_id,request.session_id,"diagnosis_attempted_without_evidence",event_key=f"{result.error_code}_{self.store.load_case_session(request.session_id).revision}")
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
            self.mentor_intervention(request.player_id,request.case_id,request.session_id,"case_completed",event_key="completed")
        return result
