"""Two-arm paid continuation probe for the V2 post-diagnosis stall.

This is an exploratory diagnostic and is intentionally separate from formal T/M
evaluation.  Both arms clone one production-built public checkpoint and share a
single provider budget guard.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from xuanyi_npc.application.clinic import ClinicActionInput, ClinicContributionInput, ClinicService
from xuanyi_npc.application.multicase import CaseCatalog, SystemEpisodeClock
from xuanyi_npc.domain.cases import CaseSessionStatus
from xuanyi_npc.domain.cooperation import CooperativeTurnStatus, PlayerContributionType
from xuanyi_npc.evaluation.v2_contracts import ArtifactKind, V2Event, V2RunArtifact
from xuanyi_npc.evaluation.v2_runner import (
    PRICE_PATH, ROOT, _event, _load_public_agent_state, _model_dump,
    _write_artifact, _write_new, append_diagnostic_turn_events,
    append_turn_context_event,
)
from xuanyi_npc.evaluation.v2_scenarios import digest
from xuanyi_npc.storage import JsonStateStore


EXPERIMENT_ID = "v2_stall_probe_v1_20260919_01"
MODEL = "deepseek-flash"
MAX_TURNS = 7
HARD_BUDGET_CNY = Decimal("0.25")
CASE_ID = "old_paper_umbrella"
DIAGNOSIS_ID = "rain_vow_breach"
EVIDENCE_IDS = (
    "fading_shadow", "forgotten_faces", "umbrella_night_water",
    "vow_knot_trace", "hidden_wooden_token", "broken_promise",
)
REFERENCE_INVESTIGATIONS = (
    "observe_scholar", "ask_about_memory", "inspect_umbrella",
    "observe_contract_trace", "search_book_chest", "ask_about_promise",
)
CONDITIONS = (
    ("A_neutral", "请依据当前公开状态继续推进，不要让我提示下一步骤。"),
    ("B_stage_prompt", "当前公开状态已进入处置阶段。请继续评估公开可选处置并推进；我不会提供处置答案。"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tree_hash(root: Path) -> str:
    h = sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _git_identity() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout
        return {"commit": commit, "dirty": bool(status), "dirty_tree_hash": sha256(status.encode()).hexdigest()}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "dirty_tree_hash": sha256(b"git-unavailable").hexdigest()}


def build_checkpoint(path: Path, *, resources: Any, agent: Any) -> dict[str, Any]:
    """Create one diagnosis-submitted checkpoint through production case APIs."""
    path.mkdir(parents=True, exist_ok=False)
    clinic = ClinicService(
        store=JsonStateStore(path), base_catalog=CaseCatalog(resources.case_dir),
        campaign_path=resources.campaign_rules, clock=SystemEpisodeClock(),
        game_npc_agent=agent, memory_mode="disabled",
    )
    player = clinic.create_player("V2 stall probe checkpoint").player_summary
    opened = clinic.start_case(player.player_id, CASE_ID, cooperative=True)
    for index, investigation_id in enumerate(REFERENCE_INVESTIGATIONS, 1):
        clinic.submit_case_action(ClinicActionInput(
            player_id=player.player_id, case_id=CASE_ID, session_id=opened.session_id,
            operation_id=f"checkpoint_investigation_{index}", action_type="investigation",
            selection_id=investigation_id,
        ))
    clinic.submit_case_action(ClinicActionInput(
        player_id=player.player_id, case_id=CASE_ID, session_id=opened.session_id,
        operation_id="checkpoint_submit_diagnosis", action_type="diagnosis",
        selection_id=DIAGNOSIS_ID, evidence_clue_ids=EVIDENCE_IDS,
    ))
    observation = clinic.resume_case(player.player_id, CASE_ID, opened.session_id).observation
    session = clinic.store.load_case_session(opened.session_id)
    if session.submitted_diagnosis_id != DIAGNOSIS_ID or session.selected_treatment_id is not None:
        raise RuntimeError("checkpoint does not satisfy post-diagnosis pre-treatment invariant")
    return {
        "player_id": player.player_id, "case_id": CASE_ID,
        "session_id": opened.session_id, "world_revision": observation.session_revision,
        "submitted_diagnosis_id": session.submitted_diagnosis_id,
        "selected_treatment_id": session.selected_treatment_id,
        "public_observation_fingerprint": digest(observation.model_dump(mode="json")),
        "checkpoint_tree_hash": _tree_hash(path),
    }


def _usage_key(usage: Any) -> tuple[Any, ...]:
    return (usage.provider_request_id, usage.input_tokens, usage.output_tokens)


def execute_arm(
    *, condition: str, continuation: str, state_root: Path, checkpoint: dict[str, Any],
    resources: Any, agent: Any, adapter: Any,
) -> V2RunArtifact:
    run_id = f"stall_probe_{condition.lower()}"
    started_at, started = _now(), time.perf_counter()
    events: list[V2Event] = [_event(
        run_id, 1, "run_started", "v2_stall_probe", condition=condition,
        checkpoint_tree_hash=checkpoint["checkpoint_tree_hash"],
        checkpoint_public_fingerprint=checkpoint["public_observation_fingerprint"],
        exploratory_only=True, excluded_from_formal_scores=True,
    )]
    usages: list[Any] = []
    seen_usage: set[tuple[Any, ...]] = set()
    failure: str | None = None
    pending = None
    raw_diagnostics: list[tuple[str, dict[str, Any]]] = []
    agent.diagnostic_hook = lambda name, data: raw_diagnostics.append((name, dict(data)))
    agent.structured_output.diagnostic_hook = agent.diagnostic_hook
    clinic = ClinicService(
        store=JsonStateStore(state_root), base_catalog=CaseCatalog(resources.case_dir),
        campaign_path=resources.campaign_rules, clock=SystemEpisodeClock(),
        game_npc_agent=agent, memory_mode="disabled",
    )
    player_id, session_id = checkpoint["player_id"], checkpoint["session_id"]
    for offset in range(MAX_TURNS):
        turn = 10 + offset
        observation = clinic.resume_case(player_id, CASE_ID, session_id).observation
        if observation.session_status is CaseSessionStatus.COMPLETED:
            break
        pre_state = _load_public_agent_state(
            clinic.store, player_id=player_id, case_id=CASE_ID, session_id=session_id,
        )
        append_turn_context_event(
            events, run_id=run_id, turn=turn, observation=observation, agent_state=pre_state,
        )
        events.append(_event(
            run_id, len(events) + 1, "budget_precheck", "deepseek_budget_guard", turn=turn,
            hard_budget_cny=str(adapter.request_budget.max_cost_cny),
            known_cost_cny=str(adapter.request_budget.known_cost_cny),
            remaining_known_budget_cny=str(
                adapter.request_budget.max_cost_cny - adapter.request_budget.known_cost_cny
            ),
            can_start_episode=adapter.request_budget.can_start_episode,
            reservation_enforced_before_each_provider_request=True,
        ))
        if not adapter.request_budget.can_start_episode:
            failure = adapter.request_budget.stop_reason or "budget_halted"
            break
        if pending is None:
            text = continuation
            contribution_type = PlayerContributionType.SUGGESTION
            responds_to = confirmation_id = None
            branch = condition
        else:
            text = "我批准当前这项具体行动，请依据最新公开状态再次判断。"
            contribution_type = PlayerContributionType.APPROVAL
            responds_to = pending.decision_id
            confirmation_id = pending.confirmation_id
            branch = "approve_pending"
        contribution = ClinicContributionInput(
            player_id=player_id, case_id=CASE_ID, session_id=session_id,
            operation_id=f"{run_id}_{turn}", text=text,
            contribution_type=contribution_type,
            responds_to_decision_id=responds_to,
            pending_confirmation_id=confirmation_id,
        )
        events.append(_event(
            run_id, len(events) + 1, "public_input_built", "probe_driver", turn=turn,
            branch=branch, contribution_type=contribution_type.value,
            public_text=text, text_hash=sha256(text.encode()).hexdigest(),
            pre_world_revision=observation.session_revision,
        ))
        prior_pending = pending
        if prior_pending is not None:
            events.append(_event(
                run_id, len(events) + 1, "confirmation_received", "clinic", turn=turn,
                valid=True, action_digest=digest(prior_pending.action.tool_call.model_dump(mode="json")),
                bound_revision=prior_pending.case_revision,
            ))
        diagnostic_start = len(raw_diagnostics)
        try:
            result = clinic.submit_player_contribution(contribution)
        except Exception as exc:
            failure = str(getattr(exc, "code", type(exc).__name__))[:120]
            for usage in (*getattr(exc, "prior_usages", ()), *(() if getattr(exc, "usage", None) is None else (exc.usage,))):
                if _usage_key(usage) not in seen_usage:
                    seen_usage.add(_usage_key(usage)); usages.append(usage)
            events.append(_event(
                run_id, len(events) + 1, "model_request_failed", "provider", turn=turn,
                stage="planning", error_code=failure, exception_class=type(exc).__name__,
                prior_usage=[_model_dump(item) for item in usages],
                diagnostics=[{"event": name, **data} for name, data in raw_diagnostics[diagnostic_start:]],
                budget_known_cost_cny=str(adapter.request_budget.known_cost_cny),
                budget_stop_reason=adapter.request_budget.stop_reason,
            ))
            break
        for usage in result.decision.usages:
            if usage is not None and _usage_key(usage) not in seen_usage:
                seen_usage.add(_usage_key(usage)); usages.append(usage)
        post_observation = clinic.resume_case(player_id, CASE_ID, session_id).observation
        post_state = _load_public_agent_state(
            clinic.store, player_id=player_id, case_id=CASE_ID, session_id=session_id,
        )
        append_diagnostic_turn_events(
            events, run_id=run_id, turn=turn, agent=agent, result=result,
            pre_observation=observation, post_observation=post_observation,
            pre_agent_state=pre_state, post_agent_state=post_state,
            prior_pending=prior_pending,
        )
        if result.selected_tool is not None:
            events.append(_event(
                run_id, len(events) + 1, "tool_attempted", "cooperative_runtime", turn=turn,
                tool=result.selected_tool.value,
                authority_mode=result.authority_mode.value if result.authority_mode else None,
            ))
        if result.status is CooperativeTurnStatus.ACTION_EXECUTED:
            controlled = result.selected_tool.value in {"submit_diagnosis", "execute_treatment"}
            action_digest = (
                digest(prior_pending.action.tool_call.model_dump(mode="json"))
                if controlled and prior_pending is not None else None
            )
            events.append(_event(
                run_id, len(events) + 1, "world_committed", "case_engine", turn=turn,
                tool=result.selected_tool.value if result.selected_tool else None,
                event_sequences=list(result.event_sequences), controlled=controlled,
                action_digest=action_digest,
                authority_mode=result.authority_mode.value if result.authority_mode else None,
            ))
        elif result.status is CooperativeTurnStatus.ACTION_REJECTED:
            events.append(_event(
                run_id, len(events) + 1, "proposal_rejected", "cooperative_runtime", turn=turn,
                error_code=result.error_code,
            ))
        pending = result.pending_action
        if pending is not None:
            events.append(_event(
                run_id, len(events) + 1, "confirmation_created", "cooperative_runtime", turn=turn,
                action_digest=digest(pending.action.tool_call.model_dump(mode="json")),
                bound_revision=pending.case_revision, authority_mode=pending.authority_mode.value,
            ))
        events.append(_event(
            run_id, len(events) + 1, "turn_completed", "v2_stall_probe", turn=turn,
            status=result.status.value,
            pre_world_revision=observation.session_revision,
            post_world_revision=post_observation.session_revision,
            pre_agent_state=pre_state, post_agent_state=post_state,
            budget_known_cost_cny=str(adapter.request_budget.known_cost_cny),
        ))
    session = clinic.store.load_case_session(session_id)
    terminal = {
        "terminal_status": session.status.value,
        "submitted_diagnosis_id": session.submitted_diagnosis_id,
        "selected_treatment_id": session.selected_treatment_id,
        "treatment_outcome": session.outcome.value if session.outcome else None,
        "score": session.score,
        "pending_confirmation": pending is not None,
        "budget_stop_reason": adapter.request_budget.stop_reason,
    }
    if session.status is not CaseSessionStatus.COMPLETED and failure is None:
        failure = "continuation_turn_limit_reached"
    events.append(_event(
        run_id, len(events) + 1, "run_ended", "v2_stall_probe",
        terminal_status=session.status.value, failure_code=failure,
        known_shared_budget_cost_cny=str(adapter.request_budget.known_cost_cny),
    ))
    costs = [float(item.estimated_cost) for item in usages if item.estimated_cost is not None]
    return V2RunArtifact(
        trace_schema_version="v2_diagnostic", run_id=run_id,
        experiment_id=EXPERIMENT_ID, scenario_id="T01", suite="stall_probe",
        condition=condition, repeat_index=1, artifact_kind=ArtifactKind.REAL_MODEL_TRIAL,
        started_at=started_at, finished_at=_now(),
        status="finished" if session.status is CaseSessionStatus.COMPLETED else "aborted",
        model=(usages[-1].provider_model if usages else MODEL), provider="deepseek",
        system_fingerprints=tuple(dict.fromkeys(
            item.system_fingerprint for item in usages if item.system_fingerprint
        )),
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
        known_cost_cny=sum(costs) if len(costs) == len(usages) else None,
        duration_ms=(time.perf_counter() - started) * 1000,
        terminal_snapshot=terminal,
        public_input_fingerprint=digest({"checkpoint": checkpoint["public_observation_fingerprint"], "text": continuation}),
        non_memory_input_fingerprint=checkpoint["public_observation_fingerprint"],
        events=tuple(events), failure_code=failure,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid-agent", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("evaluation_results/v2"))
    parser.add_argument("--budget-cny", type=Decimal, default=HARD_BUDGET_CNY)
    args = parser.parse_args(argv)
    if not args.confirm_paid_agent:
        raise ValueError("paid probe requires --confirm-paid-agent")
    if args.budget_cny != HARD_BUDGET_CNY:
        raise ValueError("v2_stall_probe_v1 hard budget is frozen at CNY 0.25")
    root = args.output_root / EXPERIMENT_ID / "real_model_continuations"
    root.mkdir(parents=True, exist_ok=False)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from xuanyi_npc.agents.deepseek import DeepSeekAdapterConfig, DeepSeekChatAdapter
    from xuanyi_npc.agents.game_npc import GameNPCAgent
    from xuanyi_npc.evaluation.costing import load_deepseek_pilot_pricing
    from xuanyi_npc.resources.runtime import materialized_clinic_resources
    artifacts: list[V2RunArtifact] = []
    with ExitStack() as stack:
        base = DeepSeekAdapterConfig.from_env()
        config = DeepSeekAdapterConfig.model_validate({
            **base.model_dump(), "model": MODEL, "max_output_tokens": 2048,
            "pilot_max_cost_cny": HARD_BUDGET_CNY,
        })
        adapter = DeepSeekChatAdapter(config, pricing=load_deepseek_pilot_pricing(PRICE_PATH))
        stack.callback(adapter.close)
        discovery = adapter.require_configured_model()
        agent = GameNPCAgent(adapter)
        resources = stack.enter_context(materialized_clinic_resources())
        checkpoint_root = root / "checkpoint_source"
        checkpoint = build_checkpoint(checkpoint_root, resources=resources, agent=agent)
        manifest = {
            "schema_version": "v2_stall_probe_manifest_v1", "experiment_id": EXPERIMENT_ID,
            "created_at": _now().isoformat(), "artifact_kind": "real_model_trial",
            "evaluation_scope": "exploratory_stage_prompt_dependency_only",
            "excluded_from_formal_T_M_scores": True,
            "not_a_fix_before_after_comparison": True,
            "model": MODEL, "provider": "deepseek", "temperature": 0.0,
            "max_output_tokens": 2048, "max_continuation_turns_per_arm": MAX_TURNS,
            "hard_budget_cny": str(HARD_BUDGET_CNY),
            "price_snapshot": json.loads(PRICE_PATH.read_text(encoding="utf-8")),
            "model_discovery": discovery.model_dump(mode="json"),
            "conditions": [{"id": key, "continuation": text} for key, text in CONDITIONS],
            "run_order": [key for key, _ in CONDITIONS], "checkpoint": checkpoint,
            "source_reference_run": "v2_task_full_20260918_01/t01_r01",
            "git": _git_identity(),
            "runtime_hashes": {
                str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
                for path in (
                    ROOT / "src/xuanyi_npc/application/cooperative_runtime.py",
                    ROOT / "src/xuanyi_npc/agents/game_npc.py",
                    ROOT / "src/xuanyi_npc/agents/bounded_output.py",
                    ROOT / "src/xuanyi_npc/evaluation/v2_stall_probe.py",
                )
            },
        }
        _write_new(root / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for condition, continuation in CONDITIONS:
            if not adapter.request_budget.can_start_episode:
                break
            arm_root = root / f"state_{condition.lower()}"
            shutil.copytree(checkpoint_root, arm_root)
            artifact = execute_arm(
                condition=condition, continuation=continuation, state_root=arm_root,
                checkpoint=checkpoint, resources=resources, agent=agent, adapter=adapter,
            )
            _write_artifact(root, artifact)
            artifacts.append(artifact)
    aggregate = {
        "schema_version": "v2_stall_probe_aggregate_v1", "experiment_id": EXPERIMENT_ID,
        "planned_arms": 2, "started_arms": len(artifacts),
        "known_cost_cny": str(adapter.request_budget.known_cost_cny),
        "hard_budget_cny": str(HARD_BUDGET_CNY),
        "budget_halted": adapter.request_budget.halted,
        "budget_stop_reason": adapter.request_budget.stop_reason,
        "runs": [{
            "run_id": item.run_id, "condition": item.condition, "status": item.status,
            "failure_code": item.failure_code, "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens, "known_cost_cny": item.known_cost_cny,
            "terminal_snapshot": item.terminal_snapshot,
        } for item in artifacts],
    }
    _write_new(root / "aggregate.json", json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(aggregate, ensure_ascii=False))
    return 0 if len(artifacts) == 2 else 3


if __name__ == "__main__":
    raise SystemExit(main())
