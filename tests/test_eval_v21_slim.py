import inspect
from pathlib import Path

from xuanyi_npc.agents import ScriptedFakeLLM, SimpleActionGameNPCAgent
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import AuthorityMode
from xuanyi_npc.evaluation.v2_scenarios import _reachable_investigations
from xuanyi_npc.evaluation.v21_freeze import execution_order
from xuanyi_npc.evaluation.v21_execute import main as execute_main
from xuanyi_npc.evaluation.v21_preflight import run as preflight_run
from xuanyi_npc.evaluation.v21_schedule import build_execution_order, track_sequence, validate_execution_order


ROOT = Path(__file__).parents[1]
CASE_ROOT = ROOT / "src/xuanyi_npc/evaluation/fixtures/v21/cases"


def _action(tool: ToolName, arguments: dict) -> AgentAction:
    return AgentAction(action_id="action_test", action_type=AgentActionType.USE_TOOL,
                       dialogue="公开提案。", tool_call=ToolCallRequest(name=tool, arguments=arguments), confidence=1.0)


def test_a0_is_model_backed_and_cannot_enter_planning_branch():
    agent = SimpleActionGameNPCAgent(ScriptedFakeLLM([]))
    assert agent.runtime_kind.value == "real_llm"
    assert not hasattr(agent, "propose_turn")
    assert agent.architecture_id == "A0"


def test_a0_and_a1_join_before_contract_authority_and_commit_gates():
    source = inspect.getsource(CooperativeRuntime.handle)
    branch = source.index("if planning_supported:")
    contract = source.index("self._resolve_contract", branch)
    authority = source.index("self.authority_policy.evaluate", contract)
    commit = source.index("submit_action_with_receipt", authority)
    assert source.count("self._resolve_contract") == 1
    assert branch < contract < authority < commit


def test_shared_authority_counterexamples_are_architecture_independent():
    policy = NPCAuthorityPolicy()
    investigation = _action(ToolName.INSPECT_OBJECT, {"investigation_id":"public_id"})
    diagnosis = _action(ToolName.SUBMIT_DIAGNOSIS, {"diagnosis_id":"public_id", "evidence_clue_ids":[]})
    treatment = _action(ToolName.EXECUTE_TREATMENT, {"treatment_id":"public_id"})
    assert policy.evaluate(investigation).mode is AuthorityMode.AUTONOMOUS
    assert policy.evaluate(diagnosis).mode is AuthorityMode.PROPOSAL_ONLY
    assert policy.evaluate(treatment).mode is AuthorityMode.CONFIRMATION_REQUIRED
    assert policy.evaluate(treatment, decision_id="d", confirmed_decision_id="other").mode is AuthorityMode.CONFIRMATION_REQUIRED


def test_new_confirmation_cases_are_reachable_with_independent_dependency_graphs():
    skills = {key:100 for key in ("observe_form","ask_cause","inspect_evidence","inspect_object","observe_qi")}
    catalog = CaseCatalog(CASE_ROOT)
    graphs = []
    for case_id in ("c01_crossed_bell_testimony","c02_red_ink_decoy","c09_three_lock_cistern","c10_ink_gate_sequence"):
        case = catalog.get(case_id)
        investigations, clues = _reachable_investigations(case, skills)
        assert len(investigations) == len(case.investigations)
        resolved = [item for item in case.treatments.values() if item.outcome.value == "resolved"]
        assert len(resolved) == 1 and set(resolved[0].required_clue_ids).issubset(clues)
        graphs.append(tuple((item.investigation_id, tuple(sorted(item.required_clue_ids))) for item in case.investigations))
    assert len(set(graphs)) == 4


def test_frozen_order_has_requested_54_episode_denominators_and_pairs():
    order = execution_order()
    assert len(order) == 54
    assert sum(item["track"] == "G" for item in order) == 18
    assert sum(item["track"] == "C" for item in order) == 24
    assert sum(item["track"] == "M" for item in order) == 12
    for track, expected in (("C", {"A0","A1"}), ("M", {"M0","M1"})):
        pairs = {}
        for item in order:
            if item["track"] == track: pairs.setdefault(item["pair_id"], set()).add(item["condition"])
        assert pairs and all(value == expected for value in pairs.values())


def test_shared_schedule_is_complete_unique_and_exact_for_all_entrypoints():
    order=build_execution_order()
    assert validate_execution_order(order) == []
    identities={(item["track"],item["task_id"],item["condition"],item["repeat"]) for item in order}
    assert len(identities) == 54
    plan={"execution_order":order}
    for track,count in (("G",18),("C",24),("M",12)):
        expanded=track_sequence(plan,track)
        assert len(expanded) == count
        assert expanded == [item for item in order if item["track"] == track]


def test_order_drift_is_rejected_before_provider_initialization(tmp_path, monkeypatch):
    order=build_execution_order(); order[18],order[19]=order[19],order[18]
    plan={"execution_order":order,"runtime_hashes":{},"experiment_id":"tampered_schedule",
          "budget":{"hard_caps":{"G":4.5,"C":6.0,"M":4.0,"total":14.5}},"model":{"name":"deepseek-flash"}}
    path=tmp_path/"tampered.json"; path.write_text(__import__("json").dumps(plan),encoding="utf-8")
    monkeypatch.setattr("xuanyi_npc.evaluation.v21_execute.v2_runner.run_real",
                        lambda *_args,**_kwargs: (_ for _ in ()).throw(AssertionError("provider path reached")))
    import pytest
    with pytest.raises(ValueError,match="schedule order differs"):
        execute_main(["--plan",str(path),"--track","G","--confirm-paid-agent"])
    result=preflight_run(path)
    assert result["status"] == "FAIL"
    assert any("schedule order differs" in error for error in result["errors"])
    assert result["paid_model_calls"] == 0
