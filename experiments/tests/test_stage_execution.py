import json

from memweave_eval.stage_execution import stage_execution


def fixture(tmp_path,steps):
    (tmp_path/'experiment-setup.json').write_text(json.dumps({'expected_actor_stage_names':['one','two','three']}))
    (tmp_path/'result.json').write_text(json.dumps({'step_results':steps}))
    return [{'event':'workspace_checkpoint','phase':phase,'stage_id':'1'}for phase in ['agent_start','agent_end']]


def test_known_pre_pi_abort_is_not_a_claim_that_all_stages_executed_or_that_logs_were_lost(tmp_path):
    events=fixture(tmp_path,[{'step_name':'one'},{'step_name':'two','exception_info':{'exception_type':'NonZeroAgentExitCodeError'}}])
    result=stage_execution(tmp_path,events)
    assert [r['status']for r in result['stages']]==['EXECUTED','FAILED_BEFORE_PI','NOT_STARTED_AFTER_ABORT']
    assert result['evidence_complete']is True and result['protocol_execution_complete']is False


def test_entire_missing_stage_cannot_pass_because_other_stages_have_logs(tmp_path):
    events=fixture(tmp_path,[{'step_name':'one'},{'step_name':'two'},{'step_name':'three'}])
    assert stage_execution(tmp_path,events)['evidence_complete']is False
    for identity in ['2','3']:
        events.extend({'event':'workspace_checkpoint','phase':phase,'stage_id':identity}for phase in ['agent_start','agent_end'])
    assert stage_execution(tmp_path,events)['protocol_execution_complete']is True


def test_unregistered_expected_sequence_stays_unknown(tmp_path):
    result=stage_execution(tmp_path,[])
    assert result['evidence_complete']is None and result['protocol_execution_complete']is None


def test_dynamic_conversation_does_not_miscount_user_turns_as_missing_source_steps(tmp_path):
    (tmp_path/'experiment-setup.json').write_text(json.dumps({'expected_actor_stage_names':[]}))
    events=[{'event':'workspace_checkpoint','phase':'agent_start','stage_id':str(i)}for i in range(1,5)]
    result=stage_execution(tmp_path,events)
    assert result['status']=='NO_FIXED_SOURCE_STAGE_SEQUENCE'and result['protocol_execution_complete']is None
    assert result['evidence_complete']is True


def test_unregistered_stage_denominator_cannot_pass_episode_collection(tmp_path,monkeypatch):
    from memweave_eval.fixed35_collection import collect_episode
    ledger=tmp_path/'quota.json';ledger.write_text('{"requests":{}}')
    monkeypatch.setattr('memweave_eval.fixed35_business.execution_boundaries',lambda *a,**kw:{'complete':True})
    monkeypatch.setattr('memweave_eval.fixed35_delivery.delivery_metrics',lambda *a,**kw:{'complete':True})
    monkeypatch.setattr('memweave_eval.fixed35_references.grade_known_references',lambda *a,**kw:{})
    monkeypatch.setattr('memweave_eval.fixed35_collection.task_state_metrics',lambda *a,**kw:{})
    assert collect_episode(tmp_path,arm='pi-native',ledger=ledger)['collection_complete']is False
    (tmp_path/'experiment-setup.json').write_text(json.dumps({'expected_actor_stage_names':[]}))
    assert collect_episode(tmp_path,arm='pi-native',ledger=ledger)['collection_complete']is True
