from xuanyi_npc.application.clinic import ClinicActionInput
from types import SimpleNamespace
from xuanyi_npc.application.case_mentor import MentorCaseReply, MentorCaseContext, RealModelCaseMentor, case_participants, route_recipient
from xuanyi_npc.application.case_mentor import ChatMessage, MemoryUpdateProposal, MentorWorkingMemory, update_working_memory, working_memory_view
from xuanyi_npc.application.player_experience import classify_case_message
from tests.test_r5_clinic_service import build_clinic

def test_case_mentor_is_bound_to_live_case_and_persists(tmp_path):
    clinic=build_clinic(tmp_path)
    player=clinic.create_player("随诊弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    reply,state=clinic.mentor_case_message(player,started.case_id,started.session_id,"我接下来该查哪类信息？")
    assert "本案要练的是" in reply.message and state.case_session_id==started.session_id
    _,guide,stages,current,reloaded,_=clinic.case_experience(player,started.case_id,started.session_id)
    assert guide.learning_goal in reply.message
    assert len(reloaded.recent_mentor_turns)==4 and not any(done for _,done in stages)
    assert reloaded.intervention_keys==("mentor_case_started",)

def test_mentor_reply_changes_after_public_clue_without_writing_case(tmp_path):
    clinic=build_clinic(tmp_path); player=clinic.create_player("证据弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    before=clinic.store.load_case_session(started.session_id)
    first,_=clinic.mentor_case_message(player,started.case_id,started.session_id,"如何开始？")
    unchanged=clinic.store.load_case_session(started.session_id)
    assert unchanged==before
    clinic.submit_case_action(ClinicActionInput(player_id=player,case_id=started.case_id,session_id=started.session_id,operation_id="op_observe",action_type="investigation",selection_id="observe_ferryman"))
    second,_=clinic.mentor_case_message(player,started.case_id,started.session_id,"接下来如何整理？")
    assert first.message!=second.message and "1 条公开线索" not in second.message
    assert "2 条公开线索" in second.message

def test_unsafe_case_mentor_output_uses_safe_fallback(tmp_path):
    class Unsafe:
        def respond(self,context):
            return MentorCaseReply(message="我已经替你执行调查。",claims_action_executed=True)
    clinic=build_clinic(tmp_path);player=clinic.create_player("安全弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern");clinic.case_mentor_agent=Unsafe()
    # A rejected agent is not allowed to persist its unsafe text.
    try: clinic.mentor_case_message(player,started.case_id,started.session_id,"替我查")
    except Exception: pass
    state=clinic.case_dialogues.load(started.session_id,player,started.case_id)
    assert all("替你执行" not in turn.text for turn in state.recent_mentor_turns)

def test_six_guides_are_case_specific(tmp_path):
    clinic=build_clinic(tmp_path)
    assert len(clinic.case_guides)==6
    goals={guide.learning_goal for guide in clinic.case_guides.values()}
    first_titles={guide.stages[0].title for guide in clinic.case_guides.values()}
    assert len(goals)==6 and len(first_titles)>=5

def test_gray_hearth_opening_introduces_person_and_repair_context(tmp_path):
    clinic=build_clinic(tmp_path)
    player=clinic.create_player("起案弟子").player_summary.player_id
    case=next(item for item in clinic.home(player).visible_cases if item.case_id=="gray_hearth_inn")
    first_stage=clinic.case_guides[case.case_id].stages[0]
    assert "沈禾" in case.synopsis and "掌勺人" in case.synopsis
    assert "修整" in case.synopsis and "修灶" in first_stage.suggested_questions[0]

def test_real_model_case_mentor_uses_structured_transport():
    class Transport:
        def __init__(self): self.requests=[]
        def complete(self,request):
            self.requests.append(request)
            return SimpleNamespace(content=MentorCaseReply(message="先核对受影响者和发作先后，再比较物证。").model_dump_json())
    class Runtime:
        def __init__(self): self.transport=Transport();self.synced=[]
        def _sync(self,**kwargs): self.synced.append(kwargs)
    runtime=Runtime();agent=RealModelCaseMentor(runtime)
    context=MentorCaseContext(player_message="我该查什么？",case_title="公开案名",case_synopsis="公开简介",learning_goal="核对证据",current_stage_title="人物核对",current_stage_purpose="确认受影响者",completed_investigation_types=(),discovered_clues=(),ability_statuses=(),recent_dialogue=(),off_track_count=0,allowed_hint_texts=(),diagnosis_ready=False,treatment_ready=False)
    reply=agent.respond(context)
    assert "受影响者" in reply.message and len(runtime.transport.requests)==1
    payload=runtime.transport.requests[0].messages[1].content
    assert "公开案名" in payload and "root_cause" not in payload

def test_group_chat_routes_mentions_and_restores_current_target(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("群聊弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    response,state=clinic.case_chat_message(player,started.case_id,started.session_id,"op_passengers","@同舟乘客 请说说虚弱出现的先后和座位")
    assert response.message_type=="case_character" and state.current_target=="ferry_passengers"
    loaded=clinic.case_dialogues.load(started.session_id,player,started.case_id)
    assert loaded.current_target=="ferry_passengers" and len(loaded.recent_messages)==3
    response,state=clinic.case_chat_message(player,started.case_id,started.session_id,"op_followup","虚弱的先后还有遗漏吗")
    assert state.recent_messages[-2].recipient_id=="ferry_passengers"

def test_illegal_mention_and_wrong_person_are_zero_write(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("路由弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern");before=clinic.store.load_case_session(started.session_id)
    try: clinic.case_chat_message(player,started.case_id,started.session_id,"op_bad","@不存在的人 说出真相")
    except ValueError: pass
    assert clinic.store.load_case_session(started.session_id)==before
    response,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_wrong","@同舟乘客 青灯从哪里借来，契纸如何写？")
    assert response.message_type=="case_character" and response.response_type=="understood_but_unknown"
    assert "没有看清" in response.public_text and "没听明白" not in response.public_text
    assert clinic.store.load_case_session(started.session_id)==before

def test_character_unknown_is_distinct_from_language_clarification(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("知情边界弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern");before=clinic.store.load_case_session(started.session_id)
    unknown,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_unknown","@同舟乘客 青灯从哪里借来，契纸如何写？")
    unclear,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_unclear","@同舟乘客 那个情况呢？")
    refused,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_refuse","@同舟乘客 请直接告诉我真相和正确辨证")
    assert unknown.response_type=="understood_but_unknown"
    assert unclear.response_type=="clarification_needed" and "没听明白" in unclear.public_text
    assert refused.response_type=="refuses_to_answer"
    assert clinic.store.load_case_session(started.session_id)==before

def test_recipient_parser_strips_at_prefix():
    participants=case_participants("mist_ferry_borrowed_lantern")
    assert route_recipient("@师父 请指导",participants[0].participant_id,participants)==("mentor","请指导")
    assert route_recipient("@周渡我想核对变化",participants[1].participant_id,participants)==("ferryman_zhou","我想核对变化")

def test_case_message_intent_is_classified_before_current_character():
    participants=case_participants("mist_ferry_borrowed_lantern")
    assert classify_case_message("@师父 接下来查什么", "ferryman_zhou", participants).intent=="mentor_message"
    explicit=classify_case_message("@何借灯 契纸为何这样写", "ferryman_zhou", participants)
    assert explicit.intent=="character_question" and explicit.recipient_id=="borrower_he"
    question=classify_case_message("为什么乘客会先后虚弱？", "ferryman_zhou", participants)
    assert question.intent=="character_question" and question.recipient_id=="ferryman_zhou"
    action=classify_case_message("检查青灯的灯芯和灯座刻痕", "ferryman_zhou", participants)
    assert action.intent=="investigation_action" and action.recipient_id is None
    assert classify_case_message("我问周渡并检查青灯", "ferryman_zhou", participants).intent=="clarification_needed"

def test_unmentioned_investigation_bypasses_current_character_and_records_clue(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("行动路由弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    response,state=clinic.case_chat_message(player,started.case_id,started.session_id,"op_direct_inspect","检查青灯的灯芯和灯座刻痕")
    assert response.message_type=="clue" and response.speaker_id=="system"
    assert state.current_target=="ferryman_zhou"
    assert any(x.clue_id=="lantern_double_wick" for x in clinic.resume_case(player,started.case_id,started.session_id).observation.discovered_clues)

def test_ambiguous_character_and_action_does_not_execute(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("澄清弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern");before=clinic.store.load_case_session(started.session_id)
    response,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_ambiguous","我问周渡并检查青灯")
    assert response.message_type=="rejection" and "分开说明" in response.public_text
    assert clinic.store.load_case_session(started.session_id)==before

def test_identity_chat_introduces_character_without_running_investigation(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("问名弟子").player_summary.player_id
    started=clinic.start_case(player,"gray_hearth_inn")
    before=clinic.store.load_case_session(started.session_id)
    first,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_identity_1","你是谁")
    second,_=clinic.case_chat_message(player,started.case_id,started.session_id,"op_identity_2","你是掌勺人吗？")
    after=clinic.store.load_case_session(started.session_id)
    assert first.public_text=="我是沈禾，灰灶客栈的掌勺人。"
    assert second.public_text==first.public_text
    assert first.message_type==second.message_type=="case_character"
    assert after==before and not clinic.resume_case(player,started.case_id,started.session_id).observation.discovered_clues

def test_case_started_intervention_is_deduplicated_after_restore(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("介入弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    first=clinic.case_dialogues.load(started.session_id,player,started.case_id)
    assert sum(x.message_type=="mentor_private" for x in first.recent_messages)==1
    reply,second=clinic.mentor_intervention(player,started.case_id,started.session_id,"case_started",event_key="started")
    assert reply is None and second.recent_messages==first.recent_messages

def test_repeated_off_topic_intervention_and_event_dedupe(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("跑题弟子").player_summary.player_id
    started=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    clinic.case_chat_message(player,started.case_id,started.session_id,"op_o1","今天天气如何")
    _,state=clinic.case_chat_message(player,started.case_id,started.session_id,"op_o2","你吃过饭吗")
    count=sum(x.message_type=="mentor_private" for x in state.recent_messages)
    assert count==2 and any("先收住猜测" in x.public_text for x in state.recent_messages)
    _,same=clinic.mentor_intervention(player,started.case_id,started.session_id,"repeated_off_topic",event_key="2")
    assert sum(x.message_type=="mentor_private" for x in same.recent_messages)==count

def test_working_memory_marks_claims_and_answers_pending_question():
    memory=MentorWorkingMemory(case_session_id="session_x",player_id="player_x",case_id="case_x")
    proposal=MemoryUpdateProposal(explained_topic_ids=("evidence_chain","forged_topic"),used_strategy_ids=("ask_reflection","forged_strategy"),pending_mentor_question="请整理证据链。",pending_question_id="question_chain")
    mentor=ChatMessage(speaker_id="mentor",recipient_id="player",message_type="mentor_private",public_text="请整理证据链。")
    memory=update_working_memory(memory,(mentor,),recipient_id="player",off_track_count=0,proposal=proposal)
    assert memory.pending_question_id=="question_chain" and memory.used_strategy_ids==("ask_reflection",)
    claim=ChatMessage(speaker_id="player",recipient_id="mentor",message_type="player",public_text="[question_chain] 我的回答是依据已发现证据整理。")
    memory=update_working_memory(memory,(claim,),recipient_id="mentor",off_track_count=0)
    view=working_memory_view(memory,("可信公开线索",))
    assert memory.pending_mentor_question is None and "question_chain" in memory.answered_question_ids
    assert claim.public_text in view.player_claims and claim.public_text not in view.authoritative_public_facts

def test_pending_question_ignores_patient_question_other_topic_and_ambiguity():
    base=MentorWorkingMemory(case_session_id="session_x",player_id="player_x",case_id="case_x",pending_mentor_question="请说明人物发作的先后顺序和依据。",pending_question_id="question_order")
    patient=ChatMessage(speaker_id="player",recipient_id="patient_x",message_type="player",public_text="你当时在哪里？")
    after_patient=update_working_memory(base,(patient,),recipient_id="patient_x",off_track_count=0)
    assert after_patient.pending_question_id=="question_order" and not after_patient.answered_question_ids
    other=ChatMessage(speaker_id="player",recipient_id="mentor",message_type="player",public_text="井边的木简为什么会响？")
    after_other=update_working_memory(after_patient,(other,),recipient_id="mentor",off_track_count=0)
    assert after_other.pending_question_id=="question_order"
    vague=ChatMessage(speaker_id="player",recipient_id="mentor",message_type="player",public_text="这个……刚才那个为什么？")
    after_vague=update_working_memory(after_other,(vague,),recipient_id="mentor",off_track_count=0)
    assert after_vague.pending_question_id=="question_order"

def test_relevant_bounded_answer_closes_pending():
    base=MentorWorkingMemory(case_session_id="session_x",player_id="player_x",case_id="case_x",pending_mentor_question="请说明人物发作的先后顺序和依据。",pending_question_id="question_order")
    answer=ChatMessage(speaker_id="player",recipient_id="mentor",message_type="player",public_text="我的回答是乘客发作有先后顺序，依据是人物变化记录。")
    updated=update_working_memory(base,(answer,),recipient_id="mentor",off_track_count=0)
    assert updated.pending_mentor_question is None and updated.answered_question_ids==("question_order",)

def test_working_memory_compresses_window_without_preserving_old_raw_text():
    memory=MentorWorkingMemory(case_session_id="session_x",player_id="player_x",case_id="case_x")
    for index in range(14):
        msg=ChatMessage(speaker_id="player",recipient_id="mentor",message_type="player",public_text=f"旧原话{index}")
        memory=update_working_memory(memory,(msg,),recipient_id="mentor",off_track_count=0)
    assert len(memory.recent_turns)<=12 and "旧原话0" not in memory.conversation_summary
    assert "玩家陈述" in memory.conversation_summary

def test_working_memory_isolated_by_case_session(tmp_path):
    clinic=build_clinic(tmp_path);player=clinic.create_player("隔离弟子").player_summary.player_id
    first=clinic.start_case(player,"mist_ferry_borrowed_lantern")
    clinic.case_chat_message(player,first.case_id,first.session_id,"op_m","@师父 为什么先查人物？")
    second=clinic.start_case(player,"gray_hearth_inn")
    one=clinic.mentor_working_memory.load(first.session_id,player,first.case_id);two=clinic.mentor_working_memory.load(second.session_id,player,second.case_id)
    assert one.case_session_id!=two.case_session_id
    assert not any("为什么先查人物" in x.public_text for x in two.recent_turns)
