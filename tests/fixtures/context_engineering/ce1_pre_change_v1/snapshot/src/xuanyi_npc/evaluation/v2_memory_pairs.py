"""Paired M0/M1/M2 target-episode runner for V2 memory transfer."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import time

from dotenv import load_dotenv

from xuanyi_npc.agents.deepseek import DeepSeekAdapterConfig, DeepSeekChatAdapter
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.clinic import ClinicActionInput, ClinicContributionInput, ClinicService
from xuanyi_npc.application.game_npc_memory import GameNPCMemoryProjectionPolicy, GameNPCMemoryRetrievalService
from xuanyi_npc.application.memory_coordination import V1MemoryCoordinator
from xuanyi_npc.application.memory_retrieval import BasicCosineMemoryRetriever, MemoryIndexService
from xuanyi_npc.application.multicase import CaseCatalog, SystemEpisodeClock
from xuanyi_npc.application.reflection import PublicAssessmentEvidence, PublicOutcomeEvidence, ReflectionProposalGenerator
from xuanyi_npc.application.reflection_lifecycle import ReflectionLifecycleService
from xuanyi_npc.application.reflection_memory import ReflectionMemoryConsolidationService
from xuanyi_npc.domain.cases import CaseSessionStatus
from xuanyi_npc.domain.cooperation import CooperativeTurnStatus, PlayerContributionType
from xuanyi_npc.domain.reflection import ReflectionTrigger, ReflectionTriggerType
from xuanyi_npc.evaluation.costing import load_deepseek_pilot_pricing
from xuanyi_npc.evaluation.v2_contracts import ArtifactKind, V2RunArtifact
from xuanyi_npc.evaluation.v2_graders import regrade
from xuanyi_npc.evaluation.v2_runner import (
    PRICE_PATH, ProfileDriver, _event, _load_public_agent_state, _now,
    _write_artifact, _write_new, aggregate, append_diagnostic_turn_events,
    append_exception_turn_events, append_turn_context_event,
    provider_budget_snapshot, turn_usage_incomplete,
)
from xuanyi_npc.evaluation.v2_scenarios import digest, resolve_scenarios
from xuanyi_npc.memory import MemoryRetrievalConfig
from xuanyi_npc.resources.runtime import materialized_clinic_resources
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository
from xuanyi_npc.evaluation.request_ledger import DurableRequestLedger, EvidenceRecordingLLMAdapter, reconcile_request_ledger
from xuanyi_npc.evaluation.v21_scenarios import memory_scenarios
from xuanyi_npc.evaluation.v21_pool_control import blocking_reason, write_execution_status


ROOT = Path(__file__).resolve().parents[3]
PAIRINGS = {
    "M01": ("old_paper_umbrella", "gray_hearth_inn", "same_owner_related"),
    "M02": ("moon_well_echo", "old_paper_umbrella", "same_owner_unrelated"),
    "M03": (None, "old_paper_umbrella", "empty"),
    "M04": ("old_paper_umbrella", "gray_hearth_inn", "inactive"),
    "M05": ("old_paper_umbrella", "gray_hearth_inn", "other_owner"),
    "M06": ("old_paper_umbrella", "returning_contract_nameless_shrine", "similar_different"),
    "MV01": ("old_paper_umbrella", "gray_hearth_inn", "same_owner_related"),
    "MV06": ("old_paper_umbrella", "returning_contract_nameless_shrine", "similar_different"),
}


def _embedding_adapter():
    from xuanyi_npc.memory import (
        BGE_M3_VERIFIED_MANIFEST_SHA256, BgeM3LocalEmbeddingAdapter,
        BgeM3LocalEmbeddingConfig, bge_m3_embedding_space_id,
    )
    model_dir = ROOT / "runtime_models" / "bge-m3-142964af7e05"
    manifest = ROOT / "tools" / "experiments" / "model_manifests" / "bge_m3_142964af7e05_dense_fp32_verified.json"
    space = bge_m3_embedding_space_id(device="cpu", max_input_length=512)
    adapter = BgeM3LocalEmbeddingAdapter(config=BgeM3LocalEmbeddingConfig(
        model_directory=model_dir, manifest_path=manifest,
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256, device="cpu",
        max_input_length=512, batch_size=8, embedding_space_id=space,
    ))
    adapter.load()
    return adapter


def _memory_parts(state_dir: Path, embedding):
    store = JsonStateStore(state_dir)
    repository = SQLiteMemoryRepository(state_dir / "memories.sqlite3"); repository.initialize()
    index = MemoryIndexService(repository=repository, adapter=embedding)
    retrieval = GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=embedding),
        retrieval_config=MemoryRetrievalConfig(top_k=8, min_similarity=0.35,
            embedding_space_id=embedding.embedding_space_id, query_template_version="memory_query_v1"),
        projection_policy=GameNPCMemoryProjectionPolicy(repository=repository),
    )
    return store, repository, index, retrieval, V1MemoryCoordinator(state_store=store, memory_repository=repository)


def _clinic(*, state_dir, resources, agent, embedding, retrieval_enabled=True):
    store, repository, index, retrieval, coordinator = _memory_parts(state_dir, embedding)
    clinic = ClinicService(
        store=store, base_catalog=CaseCatalog(resources.case_dir), campaign_path=resources.campaign_rules,
        clock=SystemEpisodeClock(), game_npc_agent=agent,
        cooperative_memory_service=retrieval if retrieval_enabled else None,
        memory_coordinator=coordinator, memory_index_service=index,
        memory_mode="semantic" if retrieval_enabled else "disabled", reflection_service=None,
    )
    return clinic, repository, index


def _complete_source(clinic, player_id: str, case_id: str):
    opened = clinic.start_case(player_id, case_id, cooperative=True)
    case = clinic.base_catalog.get(case_id)
    done = set()
    while True:
        observation = clinic.resume_case(player_id, case_id, opened.session_id).observation
        available = [item for item in observation.available_investigations if item.investigation_id not in done]
        if not available: break
        for item in available:
            clinic.submit_case_action(ClinicActionInput(
                player_id=player_id, case_id=case_id, session_id=opened.session_id,
                operation_id=f"src_inv_{len(done):02d}", action_type="investigation", selection_id=item.investigation_id,
            )); done.add(item.investigation_id)
    observation = clinic.resume_case(player_id, case_id, opened.session_id).observation
    clinic.submit_case_action(ClinicActionInput(
        player_id=player_id, case_id=case_id, session_id=opened.session_id,
        operation_id="src_diagnosis", action_type="diagnosis", selection_id=sorted(case.valid_diagnosis_ids)[0],
        evidence_clue_ids=tuple(item.clue_id for item in observation.discovered_clues),
    ))
    treatment = next(item for item in case.treatments.values() if item.outcome.value == "resolved")
    clinic.submit_case_action(ClinicActionInput(
        player_id=player_id, case_id=case_id, session_id=opened.session_id,
        operation_id="src_treatment", action_type="treatment", selection_id=treatment.treatment_id,
    ))
    return opened


def _invalidate_all(repository, player_id: str):
    # Use the public lifecycle boundary; do not edit SQLite rows directly.
    from xuanyi_npc.memory.contracts import (
        LifecycleAction, MemoryInvalidationOperation, MemoryLifecycleReason,
        TrustedMemoryBoundary, stable_lifecycle_operation_id,
    )
    for index, memory in enumerate(repository.list_memories(player_id=player_id, include_inactive=False)):
        request_id = f"v2_invalidate_{index:03d}"
        repository.invalidate_memory(MemoryInvalidationOperation(
            operation_id=stable_lifecycle_operation_id("invalidate", player_id, memory.memory_id, request_id),
            request_id=request_id, action=LifecycleAction.INVALIDATE, player_id=player_id,
            target_memory_id=memory.memory_id,
            reason=MemoryLifecycleReason.ADMINISTRATIVE_INVALIDATION,
            trusted_boundary=TrustedMemoryBoundary.ADMINISTRATOR, occurred_at=_now(),
        ))


def _run_reflection(repository, index, adapter, player_id: str, source_session: str, source_case: str):
    trigger = ReflectionTrigger.create(
        trigger_type=ReflectionTriggerType.EPISODE_COMPLETED, episode_id=source_session,
        case_id=source_case, lifecycle_event_id=f"v2_source_complete_{source_session}",
        reason="Frozen public source episode completed before the target episode.",
    )
    outcome = PublicOutcomeEvidence(
        outcome_id=f"outcome_{source_session}",
        public_summary="The public source episode completed after reversible evidence gathering and an authorized resolution.",
    )
    assessment = PublicAssessmentEvidence(
        assessment_id=f"assessment_{source_session}",
        public_summary="The final public state records that evidence gathering preceded diagnosis and treatment.",
    )
    result = ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(adapter),
        consolidation_service=ReflectionMemoryConsolidationService(repository=repository, index_service=index),
        receipt_repository=repository,
    ).process(trigger=trigger, player_id=player_id, tool_outcomes=(outcome,), assessments=(assessment,))
    return result


def _target_episode(*, clinic, repository, scenario, condition, repeat, experiment_id,
                    player_id, expected_ids, forbidden_ids, source_group, oracle,
                    source_reflection=None, source_reflection_cost=0.0,
                    per_episode_budget_cny=None, deadline_seconds=None):
    run_id = f"{scenario['id'].lower()}_{condition.lower()}_r{repeat:02d}"
    started_at, started = _now(), time.perf_counter(); events = [_event(run_id, 1, "run_started", "memory_pair_runner", source_group=source_group)]
    starting_cost = float(clinic.game_npc_agent.adapter.request_budget.known_cost_cny)
    usages = []; failure = None; usage_unknown = False
    if source_reflection is not None:
        events.append(_event(run_id, len(events)+1, "reflection_finished", "source_reflection",
            stage="reflection", provider_request_id=source_reflection.provider_request_id,
            input_tokens=source_reflection.input_tokens, output_tokens=source_reflection.output_tokens,
            written_memory_ids=list(source_reflection.written_memory_ids), status=source_reflection.status.value))
    opened = clinic.start_case(player_id, PAIRINGS[scenario["id"]][1], cooperative=True)
    initial = opened.observation
    fingerprint = digest({"case_id": initial.case_id, "revision": initial.session_revision,
                          "investigations": [i.investigation_id for i in initial.available_investigations],
                          "diagnoses": [i.diagnosis_id for i in initial.diagnosis_candidates]})
    task_scenario = {"id": scenario["id"], "profile": "cooperative", "stimulus": "请和我一起处理这个病例，你来判断下一步需要做什么。"}
    driver = ProfileDriver(task_scenario); pending = None
    for turn in range(1, 17):
        if deadline_seconds is not None and time.perf_counter() - started > deadline_seconds:
            failure = "episode_deadline_exceeded"; break
        observation = clinic.resume_case(player_id, opened.case_id, opened.session_id).observation
        if observation.session_status is CaseSessionStatus.COMPLETED: break
        pre_agent_state = _load_public_agent_state(
            clinic.store, player_id=player_id, case_id=opened.case_id,
            session_id=opened.session_id,
        )
        append_turn_context_event(
            events, run_id=run_id, turn=turn,
            observation=observation, agent_state=pre_agent_state,
        )
        _, contribution = driver.next(player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
                                      turn=turn, observation=observation, pending=pending)
        events.append(_event(run_id, len(events)+1, "public_input_built", "player_driver", turn=turn,
                             public_text=contribution.text,
                             text_hash=sha256(contribution.text.encode()).hexdigest(), pre_world_revision=observation.session_revision))
        prior = pending
        if contribution.contribution_type is PlayerContributionType.APPROVAL and prior:
            events.append(_event(run_id, len(events)+1, "confirmation_received", "clinic", turn=turn, valid=True,
                                 action_digest=digest(prior.action.tool_call.model_dump(mode="json"))))
        try: result = clinic.submit_player_contribution(contribution)
        except Exception as exc:
            failure = str(getattr(exc, "code", type(exc).__name__))[:120]
            recovered, incomplete = append_exception_turn_events(
                events, run_id=run_id, turn=turn,
                agent=clinic.game_npc_agent, error=exc,
            )
            usages.extend(recovered)
            usage_unknown = usage_unknown or incomplete
            break
        usages.extend(usage for usage in result.decision.usages if usage is not None)
        usage_unknown = usage_unknown or turn_usage_incomplete(clinic.game_npc_agent, result)
        episode_budget_exceeded = (per_episode_budget_cny is not None and
            float(clinic.game_npc_agent.adapter.request_budget.known_cost_cny) - starting_cost > per_episode_budget_cny)
        post_observation = clinic.resume_case(
            player_id, opened.case_id, opened.session_id
        ).observation
        post_agent_state = _load_public_agent_state(
            clinic.store, player_id=player_id, case_id=opened.case_id,
            session_id=opened.session_id,
        )
        append_diagnostic_turn_events(
            events, run_id=run_id, turn=turn, agent=clinic.game_npc_agent,
            result=result, pre_observation=observation,
            post_observation=post_observation,
            pre_agent_state=pre_agent_state,
            post_agent_state=post_agent_state,
            prior_pending=prior,
        )
        trace = result.memory_usage_trace
        if trace:
            events.append(_event(run_id, len(events)+1, "memory_retrieved", "memory_service", turn=turn,
                candidate_ids=list(trace.candidate_memory_ids), selected_ids=list(trace.selected_memory_ids),
                input_exposed_ids=list(trace.selected_memory_ids), declared_ids=list(trace.declared_used_memory_ids),
                accepted_ids=list(trace.accepted_used_memory_ids)))
        if result.selected_tool is not None: events.append(_event(run_id, len(events)+1, "tool_attempted", "runtime", turn=turn, tool=result.selected_tool.value))
        if result.status is CooperativeTurnStatus.ACTION_EXECUTED:
            controlled = result.selected_tool.value in {"submit_diagnosis", "execute_treatment"}
            events.append(_event(run_id, len(events)+1, "world_committed", "case_engine", turn=turn, controlled=controlled,
                tool=result.selected_tool.value,
                action_digest=digest(prior.action.tool_call.model_dump(mode="json")) if controlled and prior else None))
        pending = result.pending_action
        if pending: events.append(_event(run_id, len(events)+1, "confirmation_created", "runtime", turn=turn,
            action_digest=digest(pending.action.tool_call.model_dump(mode="json"))))
        events.append(_event(
            run_id, len(events)+1, "turn_completed", "memory_pair_runner", turn=turn,
            status=result.status.value,
            pre_world_revision=observation.session_revision,
            post_world_revision=post_observation.session_revision,
            pre_agent_state=pre_agent_state, post_agent_state=post_agent_state,
        ))
        if episode_budget_exceeded:
            failure = "episode_budget_exceeded"; break
    session = clinic.store.load_case_session(opened.session_id)
    if session.status is not CaseSessionStatus.COMPLETED and failure is None: failure = "max_turns_exceeded"
    terminal = {"terminal_status":session.status.value, "submitted_diagnosis_id":session.submitted_diagnosis_id,
                "selected_treatment_id":session.selected_treatment_id, "treatment_outcome":session.outcome.value if session.outcome else None,
                "premature_abort":failure is not None, "condition":condition,
                "expected_relevant_memory_ids":list(expected_ids), "forbidden_memory_ids":list(forbidden_ids),
                "source_group_id":source_group}
    events.append(_event(run_id, len(events)+1, "run_ended", "memory_pair_runner", terminal_status=session.status.value, failure_code=failure))
    costs=[float(u.estimated_cost) for u in usages if u.estimated_cost is not None]
    base=V2RunArtifact(trace_schema_version="v2_diagnostic",run_id=run_id,experiment_id=experiment_id,scenario_id=scenario["id"],suite="memory_transfer",
        condition=condition,repeat_index=repeat,artifact_kind=ArtifactKind.REAL_MODEL_TRIAL,started_at=started_at,finished_at=_now(),
        status="finished" if failure is None else "aborted",model=usages[-1].provider_model if usages else None,provider="deepseek",
        input_tokens=None if usage_unknown else sum(u.input_tokens for u in usages)+(source_reflection.input_tokens or 0 if source_reflection else 0),
        output_tokens=None if usage_unknown else sum(u.output_tokens for u in usages)+(source_reflection.output_tokens or 0 if source_reflection else 0),
        known_cost_cny=(sum(costs)+source_reflection_cost) if not usage_unknown and len(costs)==len(usages) else None,duration_ms=(time.perf_counter()-started)*1000,
        terminal_snapshot=terminal,public_input_fingerprint=fingerprint,non_memory_input_fingerprint=fingerprint,
        events=tuple(events),failure_code=failure)
    return base.model_copy(update={"grades":regrade(base,oracle)})


def run(args) -> int:
    offline_agent = getattr(args, "offline_agent", None)
    if not offline_agent and not args.confirm_paid_agent:
        raise ValueError("real memory pairs require --confirm-paid-agent")
    load_dotenv(ROOT / ".env"); os.environ["DEEPSEEK_MODEL"]="deepseek-flash"
    resolved, oracle = resolve_scenarios(); scenarios={i["id"]:i for i in resolved["scenarios"] if i["suite"]=="memory_transfer"}
    scenarios.update(memory_scenarios())
    root=args.output_root/args.experiment_id/"real_model_memory_pairs"; root.mkdir(parents=True,exist_ok=False)
    selected_sids = tuple(args.scenario_id or ("M01", "M02", "M03", "M04", "M05", "M06"))
    unknown = set(selected_sids) - set(PAIRINGS)
    if unknown: raise ValueError(f"unknown memory scenario ids: {sorted(unknown)}")
    selected_repeats = tuple(args.repeat or (1,2,3))
    selected_conditions = tuple(args.condition or ("M0", "M1", "M2"))
    frozen_sequence=getattr(args,"execution_sequence",None)
    if frozen_sequence is None:
        pair_order=[(sid,r) for sid in selected_sids for r in selected_repeats]
        random.Random(20260918).shuffle(pair_order)
        grouped_order=[(sid,repeat,selected_conditions) for sid,repeat in pair_order]
        flat_order=[(sid,repeat,condition) for sid,repeat,conditions in grouped_order for condition in conditions]
    else:
        flat_order=[(entry["task_id"],int(entry["repeat"]),entry["condition"]) for entry in frozen_sequence]
        if any(sid not in selected_sids or repeat not in selected_repeats or condition not in selected_conditions
               for sid,repeat,condition in flat_order):
            raise ValueError("invalid frozen M execution sequence")
        grouped_order=[]
        index=0
        while index < len(flat_order):
            sid,repeat,_=flat_order[index]; conditions=[]
            while index < len(flat_order) and flat_order[index][:2] == (sid,repeat):
                conditions.append(flat_order[index][2]); index += 1
            if set(conditions) != set(selected_conditions) or len(conditions) != len(selected_conditions):
                raise ValueError(f"invalid frozen M condition group: {sid}/r{repeat}: {conditions}")
            grouped_order.append((sid,repeat,tuple(conditions)))
    _write_new(root/"protocol.json",json.dumps({"model":"deepseek-flash","conditions":list(selected_conditions),"repeats":list(selected_repeats),
        "scenario_ids":list(selected_sids),"execution_order":flat_order,
        "target_reflection":False,"source_history":"fixture_prepared_public_execution","hard_budget_cny":args.budget_cny},ensure_ascii=False,indent=2)+"\n")
    artifacts=[]; started=[]; stop_reason=None; base_adapter=None; adapter=None
    try:
      embedding=getattr(args,"offline_embedding",None) or _embedding_adapter()
      if offline_agent:
        agent=offline_agent; adapter=getattr(args,"offline_adapter")
      else:
        config=DeepSeekAdapterConfig.from_env().model_copy(update={"model":"deepseek-flash","max_output_tokens":2048,"pilot_max_cost_cny":Decimal(str(args.budget_cny))})
        base_adapter=DeepSeekChatAdapter(config,pricing=load_deepseek_pilot_pricing(PRICE_PATH)); base_adapter.require_configured_model()
        adapter=EvidenceRecordingLLMAdapter(base_adapter,DurableRequestLedger(root/"request_ledger.jsonl")); agent=GameNPCAgent(adapter)
      with materialized_clinic_resources() as resources:
       for sid,repeat,pair_conditions in grouped_order:
        source_case,target_case,kind=PAIRINGS[sid]; source_group=f"{sid.lower()}_r{repeat:02d}"
        with tempfile.TemporaryDirectory(prefix=f"v2_seed_{source_group}_") as raw:
            seed=Path(raw)/"seed"; seed.mkdir(); seed_clinic,seed_repo,_=_clinic(state_dir=seed,resources=resources,agent=agent,embedding=embedding)
            if kind=="other_owner":
                source_player=seed_clinic.create_player("V2 source owner").player_summary.player_id
                source_opened=_complete_source(seed_clinic,source_player,source_case)
                target_player=None
            else:
                source_player=seed_clinic.create_player("V2 paired owner").player_summary.player_id
                source_opened=_complete_source(seed_clinic,source_player,source_case) if source_case else None
                target_player=source_player
            source_ids=tuple(m.memory_id for m in seed_repo.list_memories(player_id=source_player,include_inactive=False))
            if kind=="inactive": _invalidate_all(seed_repo,source_player)
            for condition in pair_conditions:
                dest=Path(raw)/condition; shutil.copytree(seed,dest)
                clinic,repo,index=_clinic(state_dir=dest,resources=resources,agent=agent,embedding=embedding,retrieval_enabled=condition!="M0")
                actual_player=target_player
                if actual_player is None: actual_player=clinic.create_player("V2 target owner").player_summary.player_id
                derived=(); rr=None; reflection_cost=0.0
                if condition=="M2" and source_opened is not None and kind not in {"inactive","other_owner"}:
                    before_cost=adapter.request_budget.known_cost_cny
                    rr=_run_reflection(repo,index,adapter,actual_player,source_opened.session_id,source_case); derived=tuple(rr.written_memory_ids)
                    reflection_cost=float(adapter.request_budget.known_cost_cny-before_cost)
                expected=source_ids+derived if kind in {"same_owner_related","similar_different"} and condition!="M0" else ()
                forbidden=source_ids if kind in {"inactive","other_owner"} else ()
                try:
                    artifact=_target_episode(clinic=clinic,repository=repo,scenario=scenarios[sid],condition=condition,
                        repeat=repeat,experiment_id=args.experiment_id,player_id=actual_player,expected_ids=expected,
                        forbidden_ids=forbidden,source_group=source_group,oracle=oracle["cases"][target_case],
                        source_reflection=rr,source_reflection_cost=reflection_cost,
                        per_episode_budget_cny=getattr(args,"per_episode_budget_cny",None),
                        deadline_seconds=getattr(args,"deadline_seconds",None))
                    _write_artifact(root,artifact)
                except Exception as exc:
                    stop_reason=f"artifact_or_contract_failure:{type(exc).__name__}"
                    break
                artifacts.append(artifact); started.append({"task_id":sid,"repeat":repeat,"condition":condition})
                stop_reason=blocking_reason(artifact)
                if stop_reason: break
                if not adapter.request_budget.can_start_episode:
                    stop_reason=adapter.request_budget.stop_reason or "pool_budget_halt"; break
            if stop_reason: break
    except Exception as exc:
        stop_reason=f"pool_initialization_or_execution_failure:{type(exc).__name__}"
    finally:
        if adapter is not None:
            budget=provider_budget_snapshot(adapter)
            _write_new(root/"provider_budget.json",json.dumps(budget,ensure_ascii=False,indent=2)+"\n")
            ledger=root/"request_ledger.jsonl"
            if ledger.exists():
                _write_new(root/"request_ledger_reconciliation.json",json.dumps(reconcile_request_ledger(ledger,budget),ensure_ascii=False,indent=2)+"\n")
        if base_adapter is not None: base_adapter.close()
    planned=len(flat_order)
    planned_items=[{"task_id":sid,"repeat":repeat,"condition":condition} for sid,repeat,condition in flat_order]
    write_execution_status(root,planned=planned_items,started=started,stop_reason=stop_reason)
    result=aggregate(args.experiment_id,ArtifactKind.REAL_MODEL_TRIAL,planned,artifacts);_write_new(root/"aggregate.json",result.model_dump_json(indent=2)+"\n")
    print(json.dumps({"status":"completed" if len(artifacts)==planned else "budget_halted","started":len(artifacts),"known_cost_cny":result.known_cost_cny,"artifact_root":str(root)},ensure_ascii=False))
    return 0 if len(artifacts)==planned else 3


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--experiment-id",required=True);p.add_argument("--budget-cny",type=float,required=True)
    p.add_argument("--output-root",type=Path,default=Path("evaluation_results/v2"))
    p.add_argument("--confirm-paid-agent",action="store_true")
    p.add_argument("--scenario-id",action="append")
    p.add_argument("--repeat",type=int,choices=(1,2,3),action="append")
    p.add_argument("--condition",choices=("M0","M1","M2"),action="append")
    return run(p.parse_args(argv))


if __name__=="__main__":raise SystemExit(main())
