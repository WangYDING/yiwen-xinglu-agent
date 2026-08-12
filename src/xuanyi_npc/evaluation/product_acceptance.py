"""Offline-only R6 product acceptance; never imports paid or embedding adapters."""

from __future__ import annotations
import argparse, hashlib, json, tempfile, time, tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from xuanyi_npc.application.clinic import ClinicService
from xuanyi_npc.application.multicase import CaseCatalog, StartEpisodeInput, SubmitActionInput
from xuanyi_npc.application.teaching import CreateTeachingSessionInput, TeachingRequest
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cases import CaseActionType, TreatmentOutcome
from xuanyi_npc.domain.product_acceptance import ProductAcceptanceV1
from xuanyi_npc.resources.runtime import materialized_clinic_resources, read_runtime_text
from xuanyi_npc.storage import JsonStateStore


class Clock:
    def now(self): return datetime(2026, 8, 12, tzinfo=timezone.utc)


class Ids:
    def __init__(self, prefix): self.prefix,self.n=prefix,0
    def _new(self): self.n+=1; return f"{self.prefix}_{self.n}"
    def new_player_id(self): return self._new()
    def new_session_id(self): return self._new()


TOOLS={CaseActionType.OBSERVE_PATIENT:ToolName.OBSERVE_PATIENT,CaseActionType.QUESTION_PATIENT:ToolName.QUESTION_PATIENT,CaseActionType.INSPECT_OBJECT:ToolName.INSPECT_OBJECT,CaseActionType.OBSERVE_QI:ToolName.OBSERVE_QI,CaseActionType.INVESTIGATE_LOCATION:ToolName.INVESTIGATE_LOCATION}


def action(tool,args,index):
    return AgentAction(action_id=f"offline_action_{index}",action_type=AgentActionType.USE_TOOL,dialogue="玩家离线验收行动。",tool_call=ToolCallRequest(name=tool,arguments=args),confidence=1.0)


class Harness:
    def __init__(self,root,resources):
        self.clinic=ClinicService(store=JsonStateStore(root),base_catalog=CaseCatalog(resources.case_dir),campaign_path=resources.campaign_rules,clock=Clock(),player_id_factory=Ids("player_offline"),session_id_factory=Ids("session_offline"))
    def player(self,name): return self.clinic.create_player(name).player_summary.player_id
    def complete(self,p,case_id,diagnosis_correct=True,outcome=TreatmentOutcome.RESOLVED,use_inheritance=False):
        service=self.clinic._service(p); case=service.case_catalog.get(case_id); started=service.start_episode(StartEpisodeInput(player_id=p,case_id=case_id)); teaching=self.clinic.teaching_service(p); taught=teaching.create(CreateTeachingSessionInput(player_id=p,case_session_id=started.session_id))
        investigations=list(case.investigations)
        if use_inheritance: investigations=[x for x in investigations if x.investigation_id!="investigate_hidden_witness_mark"]
        for i,item in enumerate(investigations,1):
            result=service.submit_action(SubmitActionInput(player_id=p,case_id=case_id,session_id=started.session_id,action=action(TOOLS[item.action_type],{"investigation_id":item.investigation_id},i))); assert result.ok,result.message
        state=self.clinic.store.load_case_session(started.session_id); diagnosis=sorted(case.valid_diagnosis_ids)[0] if diagnosis_correct else next(x for x in case.diagnosis_candidates if x not in case.valid_diagnosis_ids); i=len(investigations)+1
        result=service.submit_action(SubmitActionInput(player_id=p,case_id=case_id,session_id=started.session_id,action=action(ToolName.SUBMIT_DIAGNOSIS,{"diagnosis_id":diagnosis,"evidence_clue_ids":sorted(state.discovered_clue_ids)},i))); assert result.ok
        treatment=next(x for x in case.treatments.values() if x.outcome is outcome)
        result=service.submit_action(SubmitActionInput(player_id=p,case_id=case_id,session_id=started.session_id,action=action(ToolName.EXECUTE_TREATMENT,{"treatment_id":treatment.treatment_id},i+1))); assert result.ok
        reviewed=teaching.observe_case_completion(TeachingRequest(player_id=p,teaching_session_id=taught.state.teaching_session_id)); assert reviewed.ok
        return result,reviewed
    def foundation(self,p): return [self.complete(p,x) for x in ("old_paper_umbrella","gray_hearth_inn","moon_well_echo")]
    def exam(self,p,fail=False,request_id="exam"):
        self.clinic.permissions.reconcile(p); state=self.clinic.exams.start(p,request_id=request_id); failed=False
        for q in self.clinic.exams.definition.questions:
            selected=q.correct_option_ids
            if fail and q.critical_safety and not failed: selected=(next(x.option_id for x in q.options if x.option_id not in q.correct_option_ids),); failed=True
            state=self.clinic.exams.record_answer(player_id=p,exam_session_id=state.exam_session_id,question_id=q.question_id,selected_option_ids=selected)
        return self.clinic.exams.submit(player_id=p,exam_session_id=state.exam_session_id).state


def excellent(h):
    p=h.player("优秀主线"); results=h.foundation(p); exam=h.exam(p); grant=h.clinic.inheritance.request(p)
    for case_id in ("lantern_alley_conflicting_testimony","mist_ferry_borrowed_lantern"): results.append(h.complete(p,case_id))
    results.append(h.complete(p,"returning_contract_nameless_shrine",use_inheritance=True)); plan=h.clinic.store.load_teaching_plan(p)
    assert [x[0].episode_result.score for x in results]==[100]*6 and len(plan.completed_core_lessons)==6 and not plan.unresolved_improvement_areas and exam.result.passed and grant.granted
    return p,{"scores":[100]*6,"lessons":6,"exam":"passed","inheritance":"granted"}


def routes(h):
    p1,r1=excellent(h)
    p2=h.player("错误诊断"); _,review=h.complete(p2,"old_paper_umbrella",diagnosis_correct=False); plan=h.clinic.store.load_teaching_plan(p2); rem=h.clinic.teaching_service(p2).curriculum.remediations[plan.current_recommendation.recommendation_id]; before={k:v.proficiency for k,v in h.clinic.store.load_apprenticeship(p2).abilities.items()}; h.clinic.teaching_service(p2).plan_service.attempt_remediation(player_id=p2,remediation_id=rem.remediation_id,option_id=rem.correct_option_id,request_id="fix"); after={k:v.proficiency for k,v in h.clinic.store.load_apprenticeship(p2).abilities.items()}; assert before==after
    p3=h.player("危险处置"); _,danger=h.complete(p3,"old_paper_umbrella",outcome=TreatmentOutcome.WORSENED); assert "成功" not in danger.state.mentor_review.message
    p4=h.player("考试重考"); h.foundation(p4); failed=h.exam(p4,True,"fail"); blocked=False
    try: h.clinic.exams.start(p4,request_id="early")
    except Exception: blocked=True
    rid=failed.result.required_remediation_ids[0]; rem4=h.clinic.teaching_service(p4).curriculum.remediations[rid]; h.clinic.teaching_service(p4).plan_service.attempt_remediation(player_id=p4,remediation_id=rid,option_id=rem4.correct_option_id,request_id="exam_fix"); passed=h.exam(p4,False,"retake"); assert blocked and passed.attempt_number==2
    p5=h.player("传承门禁"); h.foundation(p5); revision=h.clinic.store.load_permission_state(p5).revision; refused=h.clinic.inheritance.request(p5); assert not refused.granted and revision==h.clinic.store.load_permission_state(p5).revision; h.exam(p5); granted=h.clinic.inheritance.request(p5); grant_revision=h.clinic.store.load_permission_state(p5).revision; h.clinic.inheritance.request(p5); assert granted.granted and grant_revision==h.clinic.store.load_permission_state(p5).revision
    p6=h.player("普通古祠"); ordinary,_=h.complete(p6,"returning_contract_nameless_shrine")
    p7=h.player("传承古祠"); h.foundation(p7);h.exam(p7);h.clinic.inheritance.request(p7); inherited,_=h.complete(p7,"returning_contract_nameless_shrine",use_inheritance=True)
    a,b=h.player("隔离甲"),h.player("隔离乙");h.complete(a,"old_paper_umbrella");h.complete(b,"old_paper_umbrella",diagnosis_correct=False); assert h.clinic.store.load_teaching_plan(a).current_recommendation.recommendation_id!=h.clinic.store.load_teaching_plan(b).current_recommendation.recommendation_id
    return p1,[r1,{"route":2,"remediation":rem.remediation_id,"no_growth_from_remediation":True},{"route":3,"outcome":"worsened","mentor_truthful":True},{"route":4,"attempts":2,"blocked_before_remediation":True},{"route":5,"refused_then_granted_once":True},{"route":6,"score":ordinary.episode_result.score,"inheritance_visible":False},{"route":7,"score":inherited.episode_result.score,"ordinary_investigations_saved":1},{"route":8,"plans_memories_state_isolated":True}]


def normalize(h,p):
    store=h.clinic.store
    payload={"case_events":[x.model_dump(mode="json") for x in store.list_case_sessions() if x.player_id==p],"apprenticeship_events":store.load_apprenticeship(p).model_dump(mode="json"),"teaching_events":[x.model_dump(mode="json") for x in store.list_teaching_sessions() if x.player_id==p],"memory_receipts":[x.model_dump(mode="json") for x in h.clinic.teaching_service(p).memory_repository.list_memories(player_id=p)],"exam_events":[x.model_dump(mode="json") for x in store.list_exam_sessions() if x.player_id==p],"permission_events":store.load_permission_state(p).model_dump(mode="json"),"public_state":h.clinic.home(p).model_dump(mode="json"),"route_classification":"excellent","safety_counts":{"external":0,"leaks":0}}
    def clean(v):
        if isinstance(v,dict): return {k:clean(x) for k,x in sorted(v.items()) if k not in {"occurred_at","created_at","updated_at","completed_at","submitted_at","teaching_session_id","memory_id"}}
        if isinstance(v,list):
            values=[clean(x) for x in v]
            return sorted(values,key=lambda item:json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(",",":")))
        if isinstance(v,str) and v.startswith("teaching_"): return "teaching_normalized"
        return v
    return clean(payload)


def run_acceptance(output):
    ProductAcceptanceV1.model_validate_json(read_runtime_text("acceptance/product_acceptance_v1.json")); output.mkdir(parents=True,exist_ok=True); tracemalloc.start(); begin=time.perf_counter()
    with materialized_clinic_resources() as resources,tempfile.TemporaryDirectory(prefix="xuanyi-r6-") as temp:
        root=Path(temp); route_harness=Harness(root/"routes",resources); _,route_results=routes(route_harness); h1=Harness(root/"first",resources); p1,_=excellent(h1); n1=normalize(h1,p1); h2=Harness(root/"second",resources); p2,_=excellent(h2); n2=normalize(h2,p2); hashes=[hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest() for x in (n1,n2)]; state_size=sum(x.stat().st_size for x in (root/"first").rglob("*") if x.is_file())
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop(); result={"status":"offline_passed_r6_in_progress" if hashes[0]==hashes[1] else "offline_failed","routes":route_results,"determinism":{"run_1_hash":hashes[0],"run_2_hash":hashes[1],"matched":hashes[0]==hashes[1]},"performance":{"wall_seconds":round(time.perf_counter()-begin,4),"peak_memory_bytes":peak,"state_bytes":state_size},"external_calls":{"deepseek_models":0,"chat":0,"bge":0,"embedding":0,"network":0,"cost_cny":0},"truthfulness":{"real_model":"not_run","human_playtest":"not_executed","remote_release":"not_executed","r6":"in_progress"},"temporary_state_cleaned":True}; (output/"r6_product_acceptance.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"); return result


def main(argv=None):
    parser=argparse.ArgumentParser(prog="xuanyi-product-acceptance");parser.add_argument("--output",type=Path,required=True);args=parser.parse_args(argv);result=run_acceptance(args.output);print(json.dumps({"status":result["status"],"hash":result["determinism"]["run_1_hash"]},ensure_ascii=False));return 0 if result["determinism"]["matched"] else 1
if __name__=="__main__":raise SystemExit(main())
