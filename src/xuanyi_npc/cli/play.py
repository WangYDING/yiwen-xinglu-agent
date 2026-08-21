"""Interactive M5-P1 no-LLM game entry point."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Sequence, TextIO

from pydantic import ValidationError

from xuanyi_npc.application import (
    CaseCatalog,
    CaseCatalogEntry,
    CaseCatalogError,
    CasePlayStatus,
    CampaignPlayerInput,
    CampaignProjectionStatus,
    CampaignRuleConfigurationError,
    CampaignRuleSet,
    CreatePlayerInput,
    FinishEpisodeInput,
    ListCasesInput,
    ListPlayersInput,
    MultiCaseEpisodeService,
    MultiCaseServiceResult,
    QuitInput,
    ResumeEpisodeInput,
    StartEpisodeInput,
    SubmitActionInput,
    CreateTeachingSessionInput,
    MentorTeachingService,
    SubmitReflectionInput,
    TeachingRequest,
    ExamService,
    ExamServiceError,
    InheritanceService,
    PermissionAccessError,
    PermissionCoordinator,
)
from xuanyi_npc.application.gameplay_modes import (
    GameplayMode,
    GameplayModeConfig,
    ModeAwareEpisodeRunner,
    ModeRunInput,
    SemanticShadowMode,
)
from xuanyi_npc.application.semantic_shadow import (
    EmptyMockShadowSearch,
    RecordingSemanticShadowObserver,
)
from xuanyi_npc.agents import (
    DeepSeekChatAdapter,
    DeepSeekGameplayAuthorization,
    DoctorAgentInterface,
    build_authorized_deepseek_v0_agent,
    build_reference_fake_agent,
    DeterministicFakeMentor,
)
from xuanyi_npc.domain import (
    AbilityId,
    AgentAction,
    AgentActionType,
    CaseActionType,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.storage import JsonStateStore
from xuanyi_npc.resources.runtime import (
    PackageResourceError,
    materialized_runtime_resources,
)
from xuanyi_npc.application.public_presentation import PUBLIC_PRESENTATION


class PlayConfigurationError(ValueError):
    """Raised before interaction when explicit local directories are unusable."""


@dataclass(frozen=True)
class PlayConfig:
    case_dir: Path
    state_dir: Path
    campaign_rules_path: Path | None = None
    gameplay_mode: GameplayMode = GameplayMode.MANUAL
    semantic_shadow_mode: SemanticShadowMode = SemanticShadowMode.OFF
    mentor_mode: str = "off"

    @classmethod
    def load(
        cls,
        *,
        case_dir: Path | str,
        state_dir: Path | str,
        campaign_rules_path: Path | str | None = None,
        gameplay_mode: GameplayMode = GameplayMode.MANUAL,
        semantic_shadow_mode: SemanticShadowMode = SemanticShadowMode.OFF,
        mentor_mode: str = "off",
    ) -> "PlayConfig":
        try:
            resolved_cases = Path(case_dir).resolve(strict=True)
            resolved_state = Path(state_dir).resolve(strict=True)
        except OSError as exc:
            raise PlayConfigurationError("配置目录不存在或不可访问。") from exc
        if not resolved_cases.is_dir():
            raise PlayConfigurationError("病例目录不可用。")
        if not resolved_state.is_dir():
            raise PlayConfigurationError("存档目录不可用。")
        resolved_rules: Path | None = None
        if campaign_rules_path is not None:
            try:
                resolved_rules = Path(campaign_rules_path).resolve(strict=True)
            except OSError as exc:
                raise PlayConfigurationError("跨案规则文件不存在或不可访问。") from exc
            if not resolved_rules.is_file():
                raise PlayConfigurationError("跨案规则文件不可用。")
        else:
            candidate = resolved_cases.parent / "campaign" / "cross_episode_rules_v1.json"
            if candidate.is_file():
                resolved_rules = candidate.resolve(strict=True)
        return cls(
            case_dir=resolved_cases,
            state_dir=resolved_state,
            campaign_rules_path=resolved_rules,
            gameplay_mode=gameplay_mode,
            semantic_shadow_mode=semantic_shadow_mode,
            mentor_mode=mentor_mode,
        )


def create_play_service(config: PlayConfig) -> MultiCaseEpisodeService:
    catalog = CaseCatalog(config.case_dir)
    rules = (
        CampaignRuleSet.load(config.campaign_rules_path, catalog)
        if config.campaign_rules_path is not None
        else CampaignRuleSet.empty(catalog)
    )
    return MultiCaseEpisodeService(
        state_store=JsonStateStore(config.state_dir),
        case_catalog=catalog,
        campaign_rules=rules,
        # The legacy numbered CLI has no foundation-practice screens; keep its
        # historical scripted journeys viable. The web clinic uses explicit exercises.
        legacy_auto_foundation=True,
    )


INVESTIGATION_TOOL_BY_ACTION: dict[CaseActionType, ToolName] = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


class PlayCLI:
    """Chinese numbered menus over the injectable application service."""

    def __init__(
        self,
        service: MultiCaseEpisodeService,
        *,
        input_fn: Callable[[str], str] = input,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        config: PlayConfig | None = None,
        doctor_agent: DoctorAgentInterface | None = None,
        shadow_observer: RecordingSemanticShadowObserver | None = None,
        paid_confirmed: bool = False,
        teaching_service: MentorTeachingService | None = None,
        permission_coordinator: PermissionCoordinator | None = None,
        exam_service: ExamService | None = None,
        inheritance_service: InheritanceService | None = None,
    ) -> None:
        self.service = service
        self.input_fn = input_fn
        self.stdout = stdout
        self.stderr = stderr
        self.config = config or PlayConfig(
            case_dir=Path("."),
            state_dir=Path("."),
        )
        self.doctor_agent = doctor_agent
        self.shadow_observer = shadow_observer
        self.paid_confirmed = paid_confirmed
        self.teaching_service = teaching_service
        self.permission_coordinator = permission_coordinator or PermissionCoordinator(
            service.state_store, service.clock
        )
        self.exam_service = exam_service or ExamService(
            service.state_store, self.permission_coordinator, service.clock
        )
        self.inheritance_service = inheritance_service or InheritanceService(
            service.state_store, self.permission_coordinator, service.clock
        )
        self.current_player_id: str | None = None
        self.current_case_id: str | None = None
        self.current_session_id: str | None = None
        self.current_teaching_session_id: str | None = None

    def run(self) -> int:
        self._print("异闻行录 · 三案兼容玩法入口")
        mode_label = {
            GameplayMode.MANUAL: "manual（玩家操作，无 LLM）",
            GameplayMode.FAKE: "fake（离线演示 Agent）",
            GameplayMode.DEEPSEEK_V0: "deepseek-v0",
        }[self.config.gameplay_mode]
        shadow_label = (
            "关闭"
            if self.config.semantic_shadow_mode is SemanticShadowMode.OFF
            else "record-only（离线 Mock，不注入行动）"
        )
        self._print(f"行动模式：{mode_label}")
        self._print(f"语义 shadow：{shadow_label}")
        if self.teaching_service is not None:
            self._print("导师教学：fake（玄医先生，固定课程）")
        if self.config.gameplay_mode is GameplayMode.DEEPSEEK_V0:
            self._print(f"付费确认：{'已确认' if self.paid_confirmed else '未确认'}")
        else:
            self._print("本模式无需 API Key。")
        while True:
            self._print("\n主菜单")
            self._print("1. 创建玩家")
            self._print("2. 选择玩家")
            self._print("0. 保存并退出")
            choice = self._read("请选择：")
            if choice == "1":
                player_id = self._create_player()
                if player_id is not None and self._player_menu(player_id):
                    return 0
            elif choice == "2":
                player_id = self._select_player()
                if player_id is not None and self._player_menu(player_id):
                    return 0
            elif choice in {"0", "99", "q", "quit"}:
                self.safe_quit()
                return 0
            else:
                self._print("请输入菜单中的编号。")

    def safe_quit(self) -> None:
        try:
            request = (
                QuitInput(
                    player_id=self.current_player_id,
                    case_id=self.current_case_id,
                    session_id=self.current_session_id,
                )
                if all(
                    value is not None
                    for value in (
                        self.current_player_id,
                        self.current_case_id,
                        self.current_session_id,
                    )
                )
                else QuitInput()
            )
            result = self.service.quit(request)
            self._print(result.message)
        except Exception:
            self._print("进度已按最后一次成功行动保存。")

    def _create_player(self) -> str | None:
        raw_name = self._read("请输入玩家显示名：")
        try:
            request = CreatePlayerInput(display_name=raw_name)
        except ValidationError:
            self._print("显示名无效：不能为空、不能含控制字符，且最多 40 个字符。")
            return None
        result = self.service.create_player(request)
        self._print(result.message)
        return result.player_id if result.ok else None

    def _select_player(self) -> str | None:
        result = self.service.list_players(ListPlayersInput())
        if not result.ok:
            self._print(result.message)
            return None
        if not result.players:
            self._print("尚未创建玩家，请先选择“创建玩家”。")
            return None
        self._print("\n玩家列表")
        for index, player in enumerate(result.players, start=1):
            self._print(f"{index}. {player.display_name}")
        self._print("0. 返回")
        choice = self._read("请选择玩家：")
        index = self._menu_index(choice, len(result.players))
        if index is None:
            if choice != "0":
                self._print("玩家编号无效。")
            return None
        return result.players[index].player_id

    def _player_menu(self, player_id: str) -> bool:
        self.current_player_id = player_id
        while True:
            self._print("\n玩家菜单")
            self._print("1. 查看病例目录")
            self._print("2. 查看玩家历程")
            self._print("3. 查看教学阶段与权限")
            self._print("4. 正式考试")
            self._print("5. 申请或查看传承")
            self._print("0. 返回主菜单")
            self._print("99. 保存并退出")
            choice = self._read("请选择：")
            if choice == "1":
                if self._case_catalog_menu(player_id):
                    return True
            elif choice == "2":
                self._show_campaign(player_id)
            elif choice == "3":
                self._show_r4_status(player_id)
            elif choice == "4":
                self._run_exam_menu(player_id)
            elif choice == "5":
                self._run_inheritance_menu(player_id)
            elif choice == "0":
                self.current_player_id = None
                return False
            elif choice in {"99", "q", "quit"}:
                self.safe_quit()
                return True
            else:
                self._print("请输入菜单中的编号。")

    def _show_r4_status(self, player_id: str) -> None:
        view = self.permission_coordinator.public_view(player_id)
        self._print("\n师门进度")
        self._print(f"教学阶段：{PUBLIC_PRESENTATION.name('stage',view.teaching_stage.value)}")
        self._print(f"考试资格：{'已获得' if view.exam_eligible else '尚未获得'}")
        self._print("当前权限：" + "、".join(PUBLIC_PRESENTATION.name('permission',item.value) for item in view.permissions))
        self._print(f"当前认可（含考试认可）：{view.effective_recognition}")
        if view.granted_inheritance_ids:
            self._print("已授予传承：" + "、".join(PUBLIC_PRESENTATION.name('inheritance',item) for item in view.granted_inheritance_ids))
        else:
            self._print("已授予传承：暂无")

    def _run_exam_menu(self, player_id: str) -> None:
        try:
            state = self.exam_service.start(
                player_id, request_id=f"cli_exam_{len(self.service.state_store.list_exam_sessions()) + 1}"
            )
            questions = self.exam_service.public_questions(player_id)
            for question in questions:
                if question.question_id in state.submitted_answers:
                    continue
                self._print(f"\n{question.public_scenario}")
                for index, option in enumerate(question.options, start=1):
                    self._print(f"{index}. {option['public_text']}")
                choice = self._read("请选择答案（0 保存并退出考试）：")
                if choice == "0":
                    self._print("考试进度已保存，可稍后继续。")
                    return
                index = self._menu_index(choice, len(question.options))
                if index is None:
                    self._print("答案编号无效；考试进度已保存。")
                    return
                state = self.exam_service.record_answer(
                    player_id=player_id, exam_session_id=state.exam_session_id,
                    question_id=question.question_id,
                    selected_option_ids=(question.options[index]["option_id"],),
                )
            result = self.exam_service.submit(
                player_id=player_id, exam_session_id=state.exam_session_id
            )
            public = self.exam_service.public_result(player_id, state.exam_session_id)
            self._print(result.message)
            self._print(f"考试得分：{public.total_score}｜结果：{'通过' if public.passed else '未通过'}")
            if public.required_remediation_ids:
                self._print("重考前补课：" + "、".join(PUBLIC_PRESENTATION.name('remediation',item) for item in public.required_remediation_ids))
        except ExamServiceError as exc:
            self._print(str(exc))

    def _run_inheritance_menu(self, player_id: str) -> None:
        result = self.inheritance_service.request(player_id)
        self._print(result.message)
        if not result.granted:
            self._print("公开原因类别：" + "、".join(result.decision.missing_requirement_categories))
            return
        try:
            content = self.inheritance_service.read_content(
                player_id, "trace_vow_restore_teaching_v1"
            )
            self._print(f"{content.title}：{content.description}")
        except PermissionAccessError:
            self._print("传承已提交；内容权限尚待协调。")

    def _case_catalog_menu(self, player_id: str) -> bool:
        result = self.service.list_cases(ListCasesInput(player_id=player_id))
        if not result.ok:
            self._print(result.message)
            return False
        self._print("\n病例目录")
        visible_cases = result.cases
        teaching_plan = None
        recommended_lesson_id = None
        if self.teaching_service is not None:
            teaching_plan = self.teaching_service.plan_service.ensure(player_id)
            recommendation = teaching_plan.current_recommendation
            if recommendation is not None:
                self._print(f"教学推荐：{PUBLIC_PRESENTATION.recommendation_name(recommendation.kind.value,recommendation.recommendation_id)}")
                self._print("推荐原因：" + "、".join(PUBLIC_PRESENTATION.name('reason',item,fallback='根据当前学习进度安排') for item in recommendation.reason_codes))
                if recommendation.kind.value == "core_lesson":
                    recommended_lesson_id = recommendation.recommendation_id
                elif recommendation.kind.value == "remediation":
                    self._print("未解决补课：" + PUBLIC_PRESENTATION.name('remediation',recommendation.recommendation_id))
            completed = set(teaching_plan.completed_core_lessons)
            self._print("三门核心课程：")
            for lesson_id in self.teaching_service.curriculum.policy.core_lesson_order:
                marker = "已完成" if lesson_id in completed else "未完成"
                self._print(f"- {PUBLIC_PRESENTATION.name('lesson',lesson_id)}：{marker}")
        for index, case in enumerate(visible_cases, start=1):
            status = {
                CasePlayStatus.AVAILABLE: "可开始",
                CasePlayStatus.ACTIVE: "可继续",
                CasePlayStatus.COMPLETED: "已完成",
            }[case.play_status]
            lesson = (
                self.teaching_service.curriculum.lessons_by_case.get(case.case_id)
                if self.teaching_service is not None else None
            )
            is_teaching_recommended = lesson is not None and lesson.lesson_id == recommended_lesson_id
            recommendation = "｜推荐课程" if is_teaching_recommended else ("｜推荐下一案" if case.is_recommended_next else "")
            self._print(f"{index}. {case.title}［{status}{recommendation}］")
            self._print(f"   {case.synopsis}")
            if case.recommendation_reason is not None:
                self._print(f"   推荐理由：{case.recommendation_reason}")
            for knowledge in case.related_knowledge:
                self._print(f"   相关知识：{knowledge.public_description}")
        self._print("0. 返回")
        if (
            teaching_plan is not None
            and teaching_plan.current_recommendation is not None
            and teaching_plan.current_recommendation.kind.value == "remediation"
        ):
            self._print("R. 进行推荐补课")
        choice = self._read("请选择病例：")
        if choice.lower() == "r" and teaching_plan is not None:
            self._run_remediation(player_id, teaching_plan.current_recommendation.recommendation_id)
            return False
        index = self._menu_index(choice, len(visible_cases))
        if index is None:
            if choice != "0":
                self._print("病例编号无效。")
            return False
        case = visible_cases[index]
        episode = self._open_case(player_id, case)
        if episode is None:
            return False
        if (
            episode.episode_result is not None
            and episode.episode_result.status.value == "completed"
        ):
            self._print_episode_result(episode)
            if self.teaching_service is not None:
                teaching = self.teaching_service.observe_case_completion(
                    TeachingRequest(
                        player_id=episode.player_id or "",
                        teaching_session_id=self.current_teaching_session_id or "",
                    )
                )
                self._print_teaching_review(teaching)
            return False
        if self.config.gameplay_mode is not GameplayMode.MANUAL:
            return self._run_agent_episode(episode)
        return self._case_loop(episode)

    def _open_case(
        self,
        player_id: str,
        case: CaseCatalogEntry,
    ) -> MultiCaseServiceResult | None:
        if case.play_status is CasePlayStatus.ACTIVE and case.active_session_id:
            result = self.service.resume_episode(
                ResumeEpisodeInput(
                    player_id=player_id,
                    case_id=case.case_id,
                    session_id=case.active_session_id,
                )
            )
        elif case.play_status is CasePlayStatus.COMPLETED and case.completed_session_id:
            result = self.service.resume_episode(
                ResumeEpisodeInput(
                    player_id=player_id,
                    case_id=case.case_id,
                    session_id=case.completed_session_id,
                )
            )
        else:
            result = self.service.start_episode(
                StartEpisodeInput(player_id=player_id, case_id=case.case_id)
            )
        self._print(result.message)
        if not result.ok:
            return None
        self.current_case_id = result.case_id
        self.current_session_id = result.session_id
        self._print_case_history_context(result)
        if self.teaching_service is not None:
            teaching = self.teaching_service.create(
                CreateTeachingSessionInput(
                    player_id=player_id,
                    case_session_id=result.session_id or "",
                )
            )
            if not teaching.ok or teaching.state is None:
                self._print(teaching.message)
                return None
            self.current_teaching_session_id = teaching.state.teaching_session_id
            lesson = self.teaching_service.curriculum.lessons[teaching.state.lesson_id]
            self._print(f"\n导师课程：{lesson.title}")
            self._print(lesson.public_description)
            self._print("课程目标：")
            for objective in lesson.learning_objectives:
                self._print(f"- {objective.description}")
            remaining = lesson.maximum_hints - len(teaching.state.used_hint_ids)
            self._print(f"可用提示次数：{remaining}")
            if teaching.mentor_action is not None:
                self._print(f"玄医先生：{teaching.mentor_action.message}")
        return result

    def _case_loop(self, current: MultiCaseServiceResult) -> bool:
        while True:
            self._print_observation(current)
            menu: list[tuple[str, AgentAction | None]] = []
            options = current.action_options
            if options is None or current.observation is None:
                self._print("公开病例状态暂时不可用。")
                return False

            for option in options.investigations:
                tool_name = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
                menu.append(
                    (
                        f"调查：{option.public_description}",
                        self._tool_action(
                            current,
                            tool_name,
                            {"investigation_id": option.investigation_id},
                        ),
                    )
                )
            for option in options.diagnoses:
                evidence = [
                    clue.clue_id for clue in current.observation.discovered_clues
                ]
                menu.append(
                    (
                        f"提交诊断：{option.public_description}",
                        self._tool_action(
                            current,
                            ToolName.SUBMIT_DIAGNOSIS,
                            {
                                "diagnosis_id": option.diagnosis_id,
                                "evidence_clue_ids": evidence,
                            },
                        ),
                    )
                )
            for option in options.treatments:
                menu.append(
                    (
                        f"执行处置：{option.public_description}",
                        self._tool_action(
                            current,
                            ToolName.EXECUTE_TREATMENT,
                            {"treatment_id": option.treatment_id},
                        ),
                    )
                )

            if self.teaching_service is not None:
                menu.append(("主动请求导师提示", None))

            self._print("\n可执行行动")
            for index, (label, _) in enumerate(menu, start=1):
                self._print(f"{index}. {label}")
            self._print("90. 重新查看状态")
            self._print("0. 返回病例目录")
            self._print("99. 保存并退出")
            choice = self._read("请选择行动：")
            if choice == "90":
                continue
            if choice == "0":
                return False
            if choice in {"99", "q", "quit"}:
                self.safe_quit()
                return True
            index = self._menu_index(choice, len(menu))
            if index is None:
                self._print("行动编号无效。")
                continue

            action = menu[index][1]
            if action is None:
                hint = self.teaching_service.request_hint(
                    TeachingRequest(
                        player_id=current.player_id or "",
                        teaching_session_id=self.current_teaching_session_id or "",
                    )
                )
                self._print(hint.message)
                if hint.mentor_action is not None:
                    self._print(f"玄医先生：{hint.mentor_action.message}")
                if hint.state is not None:
                    lesson = self.teaching_service.curriculum.lessons[hint.state.lesson_id]
                    remaining = lesson.maximum_hints - len(hint.state.used_hint_ids)
                    self._print(f"可用提示次数：{remaining}")
                continue
            receipt = self.service.submit_action_with_receipt(
                SubmitActionInput(
                    player_id=current.player_id or "",
                    case_id=current.case_id or "",
                    session_id=current.session_id or "",
                    action=action,
                )
            )
            result = receipt.result
            if receipt.events and self.shadow_observer is not None:
                self.shadow_observer.observe(result, receipt.events)
            self._print(result.message)
            self._print_new_knowledge(result)
            current = result
            if self.teaching_service is not None and result.ok:
                reflection = self.teaching_service.request_reflection(
                    TeachingRequest(
                        player_id=result.player_id or "",
                        teaching_session_id=self.current_teaching_session_id or "",
                    )
                )
                if reflection.ok and reflection.mentor_action is not None:
                    self._print(f"玄医先生：{reflection.mentor_action.message}")
                    answer = self._read("你的反思：")
                    try:
                        submitted = self.teaching_service.submit_reflection(
                            SubmitReflectionInput(
                                player_id=result.player_id or "",
                                teaching_session_id=self.current_teaching_session_id or "",
                                reflection_text=answer,
                            )
                        )
                        self._print(submitted.message)
                    except ValidationError:
                        self._print("反思不能为空；本次尚未保存，可稍后继续回答。")
            if (
                result.episode_result is not None
                and result.episode_result.status.value == "completed"
            ):
                finished = self.service.finish_episode(
                    FinishEpisodeInput(
                        player_id=result.player_id or "",
                        case_id=result.case_id or "",
                        session_id=result.session_id or "",
                    )
                )
                display_result = (
                    finished
                    if finished.ability_changes
                    or finished.relationship_changes
                    or result.apprenticeship_status is not None
                    and result.apprenticeship_status.value == "pending"
                    else result
                )
                self._print_episode_result(display_result)
                self._print_growth(display_result)
                if self.teaching_service is not None:
                    teaching = self.teaching_service.observe_case_completion(
                        TeachingRequest(
                            player_id=result.player_id or "",
                            teaching_session_id=self.current_teaching_session_id or "",
                        )
                    )
                    self._print_teaching_review(teaching)
                return False

    def _print_teaching_review(self, result) -> None:
        self._print(f"\n{result.message}")
        if result.state is None or result.state.assessment is None:
            return
        report = result.state.assessment
        self._print("结构化师评")
        self._print(f"结局：{PUBLIC_PRESENTATION.name('outcome',report.outcome.value)}｜得分：{report.final_score}")
        self._print(f"使用提示：{len(report.hints_used)} 次")
        if report.completed_objectives:
            self._print("完成目标：" + "、".join(report.completed_objectives))
        if report.missed_objectives:
            self._print("待改进目标：" + "、".join(report.missed_objectives))
        self._print("R1 能力变化：")
        for change in report.ability_changes:
            self._print(f"- {PUBLIC_PRESENTATION.name('ability',change.ability_id.value)}：{change.proficiency_before} → {change.proficiency_after}")
        self._print("R1 关系变化：")
        for change in report.relationship_changes:
            self._print(f"- {PUBLIC_PRESENTATION.name('relationship',change.dimension.value)}：{change.value_before} → {change.value_after}")
        if result.state.mentor_review is not None:
            self._print(f"玄医先生：{result.state.mentor_review.message}")
        review_event = next(
            (event for event in result.state.events if event.event_type == "mentor_review_issued"),
            None,
        )
        if review_event is not None:
            self._print(f"下一步：{review_event.fixed_next_step_action.message}")
        if self.teaching_service is not None:
            plan = self.teaching_service.plan_service.ensure(report.player_id)
            if plan.current_recommendation is not None:
                self._print(f"当前推荐：{PUBLIC_PRESENTATION.recommendation_name(plan.current_recommendation.kind.value,plan.current_recommendation.recommendation_id)}")
                self._print("推荐原因：" + "、".join(PUBLIC_PRESENTATION.name('reason',item,fallback='根据当前学习进度安排') for item in plan.recommendation_reason_codes))

    def _run_remediation(self, player_id: str, remediation_id: str) -> None:
        definition = self.teaching_service.curriculum.remediations[remediation_id]
        self._print(f"\n补课：{definition.title}")
        self._print(definition.public_explanation)
        self._print(definition.structured_question)
        for index, option in enumerate(definition.answer_options, start=1):
            self._print(f"{index}. {option.public_text}")
        choice = self._read("请选择答案：")
        index = self._menu_index(choice, len(definition.answer_options))
        if index is None:
            self._print("补课答案编号无效，本次未记录。")
            return
        option = definition.answer_options[index]
        request_id = f"cli_{self.teaching_service.plan_service.ensure(player_id).revision + 1}"
        state, correct = self.teaching_service.plan_service.attempt_remediation(
            player_id=player_id,
            remediation_id=remediation_id,
            option_id=option.option_id,
            request_id=request_id,
        )
        if correct:
            event = next(
                item for item in reversed(state.events)
                if item.event_type == "remediation_completed"
            )
            try:
                self.teaching_service.memory_projector.project_remediation(
                    player_id=player_id,
                    remediation_id=remediation_id,
                    attempt_id=event.attempt_id,
                    occurred_at=event.occurred_at,
                    ability_ids=event.target_ability_ids,
                )
            except Exception:
                self._print("补课已提交；结构化记忆尚待协调。")
            self._print(definition.completion_feedback)
        else:
            self._print("这是一次合法教学尝试，但补课尚未完成，能力不会增加。")

    def _run_agent_episode(self, current: MultiCaseServiceResult) -> bool:
        case_id = current.case_id or ""
        session_id = current.session_id or ""
        player_id = current.player_id or ""
        if self.config.gameplay_mode is GameplayMode.FAKE:
            case = self.service.case_catalog.get(case_id)
            if case is None:
                self._print("病例无法安全加载。")
                return False
            session = self.service.state_store.load_case_session(session_id)
            agent, _ = build_reference_fake_agent(
                case,
                completed_event_count=len(session.action_history),
            )
        else:
            agent = self.doctor_agent
        if agent is None:
            self._print("Agent 模式尚未通过启动门禁。")
            return False
        runner = ModeAwareEpisodeRunner(
            service=self.service,
            doctor_agent=agent,
            config=GameplayModeConfig(
                gameplay_mode=self.config.gameplay_mode,
                semantic_shadow_mode=self.config.semantic_shadow_mode,
                max_steps=8,
            ),
            shadow_observer=self.shadow_observer,
        )
        result = runner.run(
            ModeRunInput(
                player_id=player_id,
                case_id=case_id,
                session_id=session_id,
            )
        )
        for step in result.episode_result.steps:
            tool_names = {
                "investigate": "调查",
                "submit_diagnosis": "提交辨证",
                "execute_treatment": "执行处置",
                "respond": "回应",
                "use_tool": "执行病例行动",
            }
            internal_tool = (step.action.tool_call.name.value if step.action.tool_call is not None else step.action.action_type.value)
            tool = tool_names.get(internal_tool, "病例行动")
            outcome = "已执行" if step.accepted else f"被拒绝：{step.error_code}"
            self._print(f"第 {step.step_index} 步｜{tool}｜{outcome}")
        self._print_episode_result(result.public_result)
        self._print_growth(result.public_result)
        return False

    def _show_campaign(self, player_id: str) -> None:
        result = self.service.get_campaign_view(
            CampaignPlayerInput(player_id=player_id)
        )
        if not result.ok or result.campaign_view is None:
            self._print(result.message)
            return
        view = result.campaign_view
        self._print("\n玩家历程")
        if view.completed_cases:
            self._print("已完成病例：")
            for case in view.completed_cases:
                self._print(
                    f"- {case.title}｜结局：{PUBLIC_PRESENTATION.name('outcome',case.outcome.value)}｜得分：{case.score}"
                )
        else:
            self._print("已完成病例：暂无")
        if view.unlocked_knowledge:
            self._print("已解锁知识：")
            for knowledge in view.unlocked_knowledge:
                self._print(f"- {knowledge.public_description}")
        else:
            self._print("已解锁知识：暂无")
        if view.recommended_next_case is not None:
            recommended = view.recommended_next_case
            self._print(f"推荐下一案：{recommended.title}")
            self._print(f"推荐理由：{recommended.public_reason}")
        else:
            self._print("该兼容入口的三案均已完成。")

    def _print_case_history_context(self, result: MultiCaseServiceResult) -> None:
        if result.history_reaction is not None:
            self._print(f"历程反应：{result.history_reaction}")
        if result.investigation_recommendation_reason is not None:
            self._print(
                f"调查建议：{result.investigation_recommendation_reason}"
            )
        if result.campaign_status is CampaignProjectionStatus.PENDING:
            self._print("玩家历程尚待补齐，但病例进度已经安全保存。")

    def _print_new_knowledge(self, result: MultiCaseServiceResult) -> None:
        for knowledge in result.newly_unlocked_knowledge:
            self._print(f"新解锁知识：{knowledge.public_description}")

    def _tool_action(
        self,
        current: MultiCaseServiceResult,
        tool_name: ToolName,
        arguments: dict[str, object],
    ) -> AgentAction:
        revision = current.session_revision or 0
        return AgentAction(
            action_id=f"cli_action_{revision + 1}",
            action_type=AgentActionType.USE_TOOL,
            dialogue="玩家通过公开菜单选择了病例行动。",
            tool_call=ToolCallRequest(name=tool_name, arguments=arguments),
            confidence=1.0,
        )

    def _print_observation(self, result: MultiCaseServiceResult) -> None:
        observation = result.observation
        if observation is None:
            return
        self._print(f"\n病例：{observation.title}")
        self._print(f"患者：{observation.patient_name}｜{observation.patient_public_profile}")
        self._print(f"会话修订：{observation.session_revision}")
        if observation.discovered_clues:
            self._print("已发现线索：")
            for clue in observation.discovered_clues:
                self._print(f"- {clue.description}")
        else:
            self._print("已发现线索：暂无")

    def _print_episode_result(self, result: MultiCaseServiceResult) -> None:
        episode = result.episode_result
        if episode is None:
            self._print(result.message)
            return
        self._print("\n病例公开结果")
        self._print(f"状态：{PUBLIC_PRESENTATION.name('case_status', episode.status.value, fallback='状态已更新')}")
        if episode.outcome is not None:
            self._print(f"结局：{PUBLIC_PRESENTATION.name('outcome', episode.outcome.value)}")
        if episode.score is not None:
            self._print(f"得分：{episode.score}")
        if episode.submitted_diagnosis_id is not None:
            diagnosis = next((item.public_description for item in (result.action_options.diagnoses if result.action_options else ()) if item.diagnosis_id == episode.submitted_diagnosis_id), "已记录的公开辨证")
            self._print(f"已提交辨证：{diagnosis}")
        if episode.selected_treatment_id is not None:
            treatment = next((item.public_description for item in (result.action_options.treatments if result.action_options else ()) if item.treatment_id == episode.selected_treatment_id), "已记录的公开处置")
            self._print(f"已执行处置：{treatment}")

    def _print_growth(self, result: MultiCaseServiceResult) -> None:
        if (
            result.apprenticeship_status is not None
            and result.apprenticeship_status.value == "pending"
        ):
            self._print("长期成长尚待协调，但病例结果已经安全保存。")
            return
        if not result.ability_changes and not result.relationship_changes:
            return
        self._print("\n本次成长")
        for change in result.ability_changes:
            self._print(
                f"- {change.display_name}：{change.proficiency_before} → "
                f"{change.proficiency_after}（+{change.delta}）"
            )
        labels = {"affinity": "亲近", "trust": "信任", "recognition": "认可"}
        for change in result.relationship_changes:
            sign = "+" if change.delta > 0 else ""
            self._print(
                f"- {labels[change.dimension.value]}：{change.value_before} → "
                f"{change.value_after}（{sign}{change.delta}）"
            )

    def _read(self, prompt: str) -> str:
        return self.input_fn(prompt).strip()

    def _print(self, message: str) -> None:
        print(message, file=self.stdout)

    @staticmethod
    def _menu_index(choice: str, count: int) -> int | None:
        try:
            index = int(choice)
        except ValueError:
            return None
        if index < 1 or index > count:
            return None
        return index - 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xuanyi-play",
        description="异闻行录保留的三案手动/演示兼容入口；正式产品入口为六异案 Clinic Web。",
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=None,
        help="可选的病例 JSON 目录；默认使用保留的三案兼容资源。",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="用于保存本地玩家和病例进度的现有目录。",
    )
    parser.add_argument(
        "--campaign-rules",
        type=Path,
        default=None,
        help="可选的严格跨案规则 JSON；使用内置病例时默认加载内置规则。",
    )
    parser.add_argument(
        "--mode",
        choices=("manual", "fake", "deepseek-v0"),
        default="manual",
        help="行动模式；默认 manual，不调用模型。",
    )
    parser.add_argument(
        "--mentor-mode",
        choices=("off", "fake"),
        default="off",
        help="导师教学模式；默认 off，fake 仅用于玩家手动完成旧纸伞。",
    )
    parser.add_argument(
        "--semantic-shadow",
        choices=("off", "record-only"),
        default="off",
        help="语义召回旁路；record-only 仅写脱敏 Mock 记录。",
    )
    parser.add_argument(
        "--confirm-paid-agent",
        action="store_true",
        help="显式确认 DeepSeek V0 可能产生费用。",
    )
    parser.add_argument(
        "--max-cost-cny",
        type=Decimal,
        default=None,
        help="DeepSeek V0 的严格人民币预算上限。",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="DeepSeek 结果目录，必须位于 results 或 runtime_data。",
    )
    return parser


def _run_with_arguments(
    args: argparse.Namespace,
    *,
    default_case_dir: Path | None = None,
    default_campaign_rules: Path | None = None,
) -> int:
    gameplay_mode = {
        "manual": GameplayMode.MANUAL,
        "fake": GameplayMode.FAKE,
        "deepseek-v0": GameplayMode.DEEPSEEK_V0,
    }[args.mode]
    shadow_mode = {
        "off": SemanticShadowMode.OFF,
        "record-only": SemanticShadowMode.RECORD_ONLY,
    }[args.semantic_shadow]
    deepseek_adapter: DeepSeekChatAdapter | None = None
    if args.mentor_mode == "fake" and gameplay_mode is not GameplayMode.MANUAL:
        print("启动失败：导师教学模式要求玩家使用 manual 亲自行动。", file=sys.stderr)
        return 2
    if gameplay_mode is not GameplayMode.DEEPSEEK_V0 and (
        args.confirm_paid_agent
        or args.max_cost_cny is not None
        or args.results_dir is not None
    ):
        print("启动失败：付费参数只适用于 deepseek-v0 模式。", file=sys.stderr)
        return 2
    try:
        config = PlayConfig.load(
            case_dir=args.case_dir or default_case_dir,
            state_dir=args.state_dir,
            campaign_rules_path=args.campaign_rules or default_campaign_rules,
            gameplay_mode=gameplay_mode,
            semantic_shadow_mode=shadow_mode,
            mentor_mode=args.mentor_mode,
        )
        service = create_play_service(config)
        shadow_observer = (
            RecordingSemanticShadowObserver(
                EmptyMockShadowSearch(),
                config.state_dir / "shadow" / "semantic_shadow.jsonl",
            )
            if shadow_mode is SemanticShadowMode.RECORD_ONLY
            else None
        )
        doctor_agent: DoctorAgentInterface | None = None
        teaching_service = (
            MentorTeachingService(
                case_service=service,
                mentor_agent=DeterministicFakeMentor(),
            )
            if args.mentor_mode == "fake"
            else None
        )
        if gameplay_mode is GameplayMode.DEEPSEEK_V0:
            if (
                not args.confirm_paid_agent
                or args.max_cost_cny is None
                or args.results_dir is None
            ):
                raise PlayConfigurationError(
                    "DeepSeek 模式缺少付费确认、预算或安全结果目录。"
                )
            authorization = DeepSeekGameplayAuthorization(
                confirm_paid=True,
                max_cost_cny=args.max_cost_cny,
                results_dir=args.results_dir,
            )
            doctor_agent, deepseek_adapter, _ = build_authorized_deepseek_v0_agent(
                authorization
            )
    except (
        PlayConfigurationError,
        CaseCatalogError,
        CampaignRuleConfigurationError,
    ):
        print("启动失败：病例或存档目录不可用。", file=sys.stderr)
        return 2
    except Exception:
        print("启动失败：无法安全初始化游戏。", file=sys.stderr)
        return 1

    cli = PlayCLI(
        service,
        config=config,
        doctor_agent=doctor_agent,
        shadow_observer=shadow_observer,
        paid_confirmed=args.confirm_paid_agent,
        teaching_service=teaching_service,
    )
    try:
        return cli.run()
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stdout)
        cli.safe_quit()
        return 0
    except Exception:
        cli.safe_quit()
        print("游戏发生内部错误，已按最后一次成功行动保留进度。", file=sys.stderr)
        return 1
    finally:
        if deepseek_adapter is not None:
            deepseek_adapter.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.case_dir is not None:
        return _run_with_arguments(args)
    try:
        with materialized_runtime_resources() as resources:
            return _run_with_arguments(
                args,
                default_case_dir=resources.case_dir,
                default_campaign_rules=resources.campaign_rules,
            )
    except PackageResourceError:
        print("启动失败：安装包运行数据不可用。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
