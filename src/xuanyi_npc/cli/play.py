"""Interactive M5-P1 no-LLM game entry point."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, TextIO

from pydantic import ValidationError

from xuanyi_npc.application import (
    CaseCatalog,
    CaseCatalogEntry,
    CaseCatalogError,
    CasePlayStatus,
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
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.storage import JsonStateStore


class PlayConfigurationError(ValueError):
    """Raised before interaction when explicit local directories are unusable."""


@dataclass(frozen=True)
class PlayConfig:
    case_dir: Path
    state_dir: Path

    @classmethod
    def load(cls, *, case_dir: Path | str, state_dir: Path | str) -> "PlayConfig":
        try:
            resolved_cases = Path(case_dir).resolve(strict=True)
            resolved_state = Path(state_dir).resolve(strict=True)
        except OSError as exc:
            raise PlayConfigurationError("配置目录不存在或不可访问。") from exc
        if not resolved_cases.is_dir():
            raise PlayConfigurationError("病例目录不可用。")
        if not resolved_state.is_dir():
            raise PlayConfigurationError("存档目录不可用。")
        return cls(case_dir=resolved_cases, state_dir=resolved_state)


def create_play_service(config: PlayConfig) -> MultiCaseEpisodeService:
    return MultiCaseEpisodeService(
        state_store=JsonStateStore(config.state_dir),
        case_catalog=CaseCatalog(config.case_dir),
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
    ) -> None:
        self.service = service
        self.input_fn = input_fn
        self.stdout = stdout
        self.stderr = stderr
        self.current_player_id: str | None = None
        self.current_case_id: str | None = None
        self.current_session_id: str | None = None

    def run(self) -> int:
        self._print("玄医问道 · 病例修习")
        self._print("当前为无 LLM 的确定性游玩模式。")
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
            self._print("0. 返回主菜单")
            self._print("99. 保存并退出")
            choice = self._read("请选择：")
            if choice == "1":
                if self._case_catalog_menu(player_id):
                    return True
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
            self._print(f"{index}. {case.title}［{status}］")
            self._print(f"   {case.synopsis}")
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
        if episode.episode_result is not None and episode.episode_result.status.value == "completed":
            self._print_episode_result(episode)
            return False
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
            result = self.service.submit_action(
                SubmitActionInput(
                    player_id=current.player_id or "",
                    case_id=current.case_id or "",
                    session_id=current.session_id or "",
                    action=action,
                )
            )
            self._print(result.message)
            current = result
            if result.episode_result is not None and result.episode_result.status.value == "completed":
                finished = self.service.finish_episode(
                    FinishEpisodeInput(
                        player_id=result.player_id or "",
                        case_id=result.case_id or "",
                        session_id=result.session_id or "",
                    )
                )
                self._print_episode_result(finished)
                return False

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
        required=True,
        help="包含已校验病例 JSON 的目录。",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="用于保存本地玩家和病例进度的现有目录。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = PlayConfig.load(case_dir=args.case_dir, state_dir=args.state_dir)
        service = create_play_service(config)
    except (PlayConfigurationError, CaseCatalogError):
        print("启动失败：病例或存档目录不可用。", file=sys.stderr)
        return 2
    except Exception:
        print("启动失败：无法安全初始化游戏。", file=sys.stderr)
        return 1

    cli = PlayCLI(service)
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


if __name__ == "__main__":
    raise SystemExit(main())
