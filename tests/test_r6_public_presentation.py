import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.test_r6_real_mentor_clinic import CONTEXTS, MockTransport, complete
from tests.test_r5_clinic_http import request
from tests.test_r5_clinic_service import build_clinic
from xuanyi_npc.application.clinic_mentor import ClinicMentorMode, ClinicMentorRuntime
from xuanyi_npc.application.mentor_communication import MentorActionV2
from xuanyi_npc.application.public_presentation import (
    PUBLIC_PRESENTATION, PublicPresentationMapper, PublicTerminologyCatalog,
)
from xuanyi_npc.clinic.server import ClinicHTTPServer
from xuanyi_npc.application.structured_memory import StructuredMentorMemorySelector
from xuanyi_npc.domain import AbilityId
from xuanyi_npc.domain.curriculum import StructuredMemorySourceType, StructuredTeachingMemoryType
from xuanyi_npc.memory.projection import DeterministicMemoryProjector
from xuanyi_npc.storage import SQLiteMemoryRepository
from datetime import datetime, timezone


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in {"script","style"}: self.hidden+=1
    def handle_endtag(self, tag):
        if self.hidden and tag in {"script","style"}: self.hidden-=1
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def visible_text(html):
    parser=_VisibleText(); parser.feed(html); return " ".join(parser.parts)


def test_catalog_freezes_complete_public_vocabulary():
    counts={kind:sum(item.entity_type==kind for item in PUBLIC_PRESENTATION.catalog.entries) for kind in {item.entity_type for item in PUBLIC_PRESENTATION.catalog.entries}}
    for kind, expected in {"ability":6,"lesson":6,"remediation":3,"stage":4,"permission":6,"inheritance":1,"exam":1}.items():
        assert counts[kind]>=expected
    assert PUBLIC_PRESENTATION.name("ability","reason_diagnosis")=="辨证"
    assert PUBLIC_PRESENTATION.name("remediation","remediate_diagnostic_reasoning_v1")=="辨证与诱饵排除补课"
    assert PUBLIC_PRESENTATION.name("remediation","remediate_treatment_alignment_v1")=="处置与守则补课"


def test_duplicate_and_unknown_mapping_fail_closed():
    first=PUBLIC_PRESENTATION.catalog.entries[0]
    with pytest.raises(ValueError,match="duplicate"):
        PublicTerminologyCatalog(catalog_id="public_terminology_v1",version="v1",entries=(first,first))
    assert PublicPresentationMapper(PUBLIC_PRESENTATION.catalog).name("ability","unknown_internal_v9")=="相关内容"
    assert "unknown_internal_v9" not in PUBLIC_PRESENTATION.public_object("ability","unknown_internal_v9").values()


@pytest.mark.parametrize("request_id",tuple(CONTEXTS))
def test_five_mentor_plans_expose_only_public_natural_language(request_id,tmp_path):
    runtime=ClinicMentorRuntime(ClinicMentorMode.FAKE,tmp_path)
    plan=runtime.planner.build(request_id,CONTEXTS[request_id])
    natural_language=" ".join(plan.required_public_facts.values())
    assert not PUBLIC_PRESENTATION.detected_internal_ids(natural_language)


@pytest.mark.parametrize("leak",(
    "reason_diagnosis", "remediate_diagnostic_reasoning_v1", "INNER_DISCIPLE",
    "请修习辨证，再查看 remediate_treatment_alignment_v1。", "unknown_internal_v9",
))
def test_internal_id_in_model_body_uses_public_fallback_without_state_write(leak,tmp_path):
    transport=MockTransport(tmp_path,[]); runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport)
    plan=runtime.planner.build("wrong_diagnosis_remediation_1",CONTEXTS["wrong_diagnosis_remediation_1"])
    action=MentorActionV2(action_type=plan.allowed_action_types[0],message=" ".join(plan.required_public_facts.values())+" "+leak,covered_point_ids=plan.required_public_point_ids)
    transport.scripts=[action.model_dump_json()]
    before={p.name:p.read_bytes() for p in tmp_path.glob("*.json") if "mentor_budget" not in p.name}
    result=runtime.express("wrong_diagnosis_remediation_1",CONTEXTS["wrong_diagnosis_remediation_1"])
    after={p.name:p.read_bytes() for p in tmp_path.glob("*.json") if "mentor_budget" not in p.name}
    assert result.stop_category=="presentation_quality_failure" and result.fallback_used and not result.model_passed
    assert not PUBLIC_PRESENTATION.contains_internal_id(result.message)
    assert before==after and len(transport.calls)==1 and not runtime.budget_state.frozen


def test_secret_identifier_upgrades_to_safety_stop(tmp_path):
    runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,MockTransport(tmp_path,["MENTOR_SECRET"]))
    result=runtime.express("initial_lesson_hint_1",CONTEXTS["initial_lesson_hint_1"])
    assert result.stop_category=="safety_stop" and runtime.budget_state.frozen


def test_saved_smoke_observation_is_detected_and_safely_re_evaluated():
    report=(Path(__file__).parents[1]/"docs/R6_REAL_MENTOR_CLINIC_SMOKE_RESULT.md").read_text(encoding="utf-8")
    historical=" ".join(re.findall(r"`([^`]+)`",report))
    assert {"reason_diagnosis","remediate_diagnostic_reasoning_v1","remediate_treatment_alignment_v1"}.issubset(PUBLIC_PRESENTATION.detected_internal_ids(historical))
    rendered=PUBLIC_PRESENTATION.sanitize_legacy_text(historical)
    for old in ("reason_diagnosis","remediate_diagnostic_reasoning_v1","remediate_treatment_alignment_v1","inheritance"):
        assert old not in rendered
    assert "辨证" in rendered and "处置与守则补课" in rendered


def test_visible_html_scanner_ignores_legal_hidden_ids_but_catches_body_text():
    html='<p>当前补课：辨证与诱饵排除补课</p><input type="hidden" value="remediate_diagnostic_reasoning_v1">'
    assert not PUBLIC_PRESENTATION.contains_internal_id(visible_text(html))
    assert PUBLIC_PRESENTATION.contains_internal_id(html)
    assert PUBLIC_PRESENTATION.contains_internal_id(visible_text(html+'<p>reason_diagnosis</p>'))


def test_clean_mock_expression_still_passes_and_fallback_is_public(tmp_path):
    transport=MockTransport(tmp_path,[]); runtime=ClinicMentorRuntime(ClinicMentorMode.DEEPSEEK,tmp_path,transport)
    transport.scripts=[complete(runtime,"exam_failure_explanation_1")]
    result=runtime.express("exam_failure_explanation_1",CONTEXTS["exam_failure_explanation_1"])
    assert result.model_passed and not result.fallback_used
    assert not PUBLIC_PRESENTATION.contains_internal_id(result.message)


def test_clinic_home_visible_text_is_public_while_hidden_internal_values_remain_legal(tmp_path):
    import threading
    clinic=build_clinic(tmp_path); player=clinic.create_player("展示弟子").player_summary.player_id
    server=ClinicHTTPServer(("127.0.0.1",0),clinic); thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":0.01});thread.start()
    try:
        status,_,home=request(server.server_address[1],"GET",f"/clinic?player_id={player}")
        assert status==200
        text=visible_text(home)
        assert "见习弟子" in text and "证据齐备再定证" in text and "公开内容" in text
        assert not PUBLIC_PRESENTATION.contains_internal_id(text)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_legacy_memory_is_publicized_without_rewriting_authoritative_source(tmp_path):
    repository=SQLiteMemoryRepository(tmp_path/"memory.sqlite3");repository.initialize()
    projector=DeterministicMemoryProjector(projection_version="structured_teaching_memory_v1",projection_ordinal=0)
    source,memory=projector.project_structured_teaching_fact(
        player_id="player_memory",source_session_id="episode_old",source_sequence=1,source_revision=1,
        occurred_at=datetime(2026,8,13,tzinfo=timezone.utc),structured_memory_type=StructuredTeachingMemoryType.LEARNING_PATTERN,
        source_type=StructuredMemorySourceType.ABILITY_EVIDENCE,source_reference_id="assessment_old",
        public_summary="你需要完成 remediate_diagnostic_reasoning_v1，并继续改进 reason_diagnosis。",
        reason_code="legacy",source_case_id="old_paper_umbrella",lesson_id="evidence_before_diagnosis_v1",ability_ids=("reason_diagnosis",),
    )
    repository.write_projection(source,memory);before=repository.list_memories(player_id="player_memory")[0].model_dump_json()
    selected=StructuredMentorMemorySelector(repository).select(player_id="player_memory",current_lesson_id="provenance_before_intent_v1",current_case_id="gray_hearth_inn",target_ability_ids=(),unresolved_improvement_areas=(AbilityId.REASON_DIAGNOSIS,),current_teaching_stage="PROBATIONARY",excluded_episode_id="episode_current")
    assert selected and "辨证与诱饵排除补课" in selected[0].public_summary and "reason_diagnosis" not in selected[0].public_summary
    assert repository.list_memories(player_id="player_memory")[0].model_dump_json()==before
