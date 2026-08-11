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
)
from xuanyi_npc.domain import (
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


class PlayConfigurationError(ValueError):
    """Raised before interaction when explicit local directories are unusable."""


@dataclass(frozen=True)
class PlayConfig:
    case_dir: Path
    state_dir: Path
    campaign_rules_path: Path | None = None
    gameplay_mode: GameplayMode = GameplayMode.MANUAL
    semantic_shadow_mode: SemanticShadowMode = SemanticShadowMode.OFF

    @classmethod
    def load(
        cls,
        *,
        case_dir: Path | str,
        state_dir: Path | str,
        campaign_rules_path: Path | str | None = None,
        gameplay_mode: GameplayMode = GameplayMode.MANUAL,
        semantic_shadow_mode: SemanticShadowMode = SemanticShadowMode.OFF,
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
        self.current_player_id: str | None = None
        self.current_case_id: str | None = None
        self.current_session_id: str | None = None

    def run(self) -> int:
        self._print("玄医问道 · 病例修习")
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
            self._print(f"{index}. {player.display_name}（{player.player_id}）")
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
            self._print("0. 返回主菜单")
            self._print("99. 保存并退出")
            choice = self._read("请选择：")
            if choice == "1":
                if self._case_catalog_menu(player_id):
                    return True
            elif choice == "2":
                self._show_campaign(player_id)
            elif choice == "0":
                self.current_player_id = None
                return False
            elif choice in {"99", "q", "quit"}:
                self.safe_quit()
                return True
            else:
                self._print("请输入菜单中的编号。")

    def _case_catalog_menu(self, player_id: str) -> bool:
        result = self.service.list_cases(ListCasesInput(player_id=player_id))
        if not result.ok:
            self._print(result.message)
            return False
        self._print("\n病例目录")
        for index, case in enumerate(result.cases, start=1):
            status = {
                CasePlayStatus.AVAILABLE: "可开始",
                CasePlayStatus.ACTIVE: "可继续",
                CasePlayStatus.COMPLETED: "已完成",
            }[case.play_status]
            recommendation = "｜推荐下一案" if case.is_recommended_next else ""
            self._print(f"{index}. {case.title}［{status}{recommendation}］")
            self._print(f"   {case.synopsis}")
            if case.recommendation_reason is not None:
                self._print(f"   推荐理由：{case.recommendation_reason}")
            for knowledge in case.related_knowledge:
                self._print(f"   相关知识：{knowledge.public_description}")
        self._print("0. 返回")
        choice = self._read("请选择病例：")
        index = self._menu_index(choice, len(result.cases))
        if index is None:
            if choice != "0":
                self._print("病例编号无效。")
            return False
        case = result.cases[index]
        episode = self._open_case(player_id, case)
        if episode is None:
            return False
        if (
            episode.episode_result is not None
            and episode.episode_result.status.value == "completed"
        ):
            self._print_episode_result(episode)
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
        return result

    def _case_loop(self, current: MultiCaseServiceResult) -> bool:
        while True:
            self._print_observation(current)
            menu: list[tuple[str, AgentAction]] = []
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
                return False

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
            tool = (
                step.action.tool_call.name.value
                if step.action.tool_call is not None
                else step.action.action_type.value
            )
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
                    f"- {case.title}｜结局：{case.outcome.value}｜得分：{case.score}"
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
            self._print("三个病例均已完成。")

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
        self._print(f"状态：{episode.status.value}")
        if episode.outcome is not None:
            self._print(f"结局：{episode.outcome.value}")
        if episode.score is not None:
            self._print(f"得分：{episode.score}")
        if episode.submitted_diagnosis_id is not None:
            self._print(f"已提交诊断：{episode.submitted_diagnosis_id}")
        if episode.selected_treatment_id is not None:
            self._print(f"已执行处置：{episode.selected_treatment_id}")

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
        description="交互式游玩玄医问道的确定性病例。",
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=None,
        help="可选的病例 JSON 目录；默认使用安装包内置的三个病例。",
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
