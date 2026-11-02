
import pytest

from memweave_eval.fixed35_campaign import validate_admission
from memweave_eval.fixed35_collection import unique_sessions


def test_cumulative_session_copies_count_once_and_require_prefix(tmp_path):
    a=tmp_path/'one/sessions';b=tmp_path/'two/sessions';a.mkdir(parents=True);b.mkdir(parents=True)
    (a/'session.jsonl').write_text('one\n')
    (b/'session.jsonl').write_text('one\ntwo\n')
    assert unique_sessions(tmp_path)==[b/'session.jsonl']
    (a/'session.jsonl').write_text('wrong\n')
    with pytest.raises(ValueError,match='conflicting'):
        unique_sessions(tmp_path)


def test_zero_tool_opportunities_require_complete_independent_execution_coverage():
    from memweave_eval.fixed35_collection import known_zero_tools
    assert known_zero_tools({},complete=False)=={}
    known=known_zero_tools({},complete=True)
    assert known['bash']['attempts']==0 and known['bash']['executions']==0
    from memweave_eval.normalized_scores import normalize_trial_scores
    scores=normalize_trial_scores({'engineering_metrics':{'tools':known}})
    point=next(m for m in scores['metrics']if m['id']=='Q1.tool.bash.error_rate')
    assert point['status']=='not_applicable'and point['score']is None


def test_no_admission_without_frozen_real_preflight_and_contract():
    with pytest.raises(ValueError,match='missing admission'):
        validate_admission({'case_id':'MAB-01'})


def test_long_qualification_counts_only_successful_unique_main_api_returns():
    from memweave_eval.fixed35_collection import qualified_actor_calls
    request={'tools':[{'function':{'name':'bash'}}]}
    response={'http_status':200,'stream_done':True,'successful_finish':True,'assistant_payload_present':True,
        'provider_error':False,'usage':{'prompt_tokens':100,'completion_tokens':1}}
    assert qualified_actor_calls({'main':request},{'main':response})==['main']
    for change in [{'http_status':500},{'successful_finish':False},{'assistant_payload_present':False},
        {'provider_error':True},{'usage':{'prompt_tokens':0,'completion_tokens':0}},{'stream_done':False}]:
        assert qualified_actor_calls({'main':request},{'main':dict(response,**change)})==[]
    assert qualified_actor_calls({'aux':{'tools':[]}},{'aux':response})==[]


def test_real_admission_requires_matching_two_arm_settled_canary(tmp_path):
    import json

    from memweave_eval.fixed35_campaign import validate_paid_canary
    from memweave_eval.storage import file_digest
    ledger=tmp_path/'ledger.json';ledger.write_text(json.dumps({'requests':{
        'native':{'status':'settled','arm':'preflight'},'plugin':{'status':'settled','arm':'preflight'}}}))
    proof=tmp_path/'canary.json';evidence={'passed':True,'evaluator_commit':'a'*40,'runtime_plan_sha256':'b'*64,
        'per_arm':{a:{'actor_request_ids':[identity],'guard_negative_upstream_requests':0}
            for a,identity in [('pi-native','native'),('pi-memweave','plugin')]}}
    proof.write_text(json.dumps(evidence));record={'admission_status':'ADMITTED','family':'tb4','evaluator_commit':'a'*40,
        'runtime_plan_sha256':'b'*64,'paid_canary':{'path':str(proof),'sha256':file_digest(proof)}}
    validate_paid_canary(record,ledger)
    with pytest.raises(ValueError,match='not admitted'):validate_paid_canary(dict(record,admission_status='PENDING'),ledger)
    with pytest.raises(ValueError,match='frozen'):validate_paid_canary(dict(record,evaluator_commit='c'*40),ledger)
    ledger.write_text(json.dumps({'requests':{'native':{'status':'reserved','arm':'preflight'}}}))
    with pytest.raises(ValueError,match='not settled'):validate_paid_canary(record,ledger)
