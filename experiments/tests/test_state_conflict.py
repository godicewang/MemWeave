from copy import deepcopy
from types import SimpleNamespace

import pytest

from memweave_eval.state_conflict import (
    PENDING_RECORDS,
    RESOLUTION,
    RESOLVED_RECORD,
    ConflictEnvironment,
    common_checkpoint_rows,
    conflict_points,
    state_record_points,
    typed_record,
    valid_resolution_arguments,
    verified_journal_prefix,
)


def contract():
    return {'case_id':'INT-04','task_id':'selected-original','resolution':deepcopy(RESOLUTION),'scope':'typed controlled case',
        'score_channel':'derived typed source conflict','requirements':[
            {'entity_type':'bookings','record_key':'BK-A04','field':field,'expected_value':value}
            for field,value in [('status','cancelled'),('cancellation_fee',0),('refund_amount',310)]]}


def before():
    return {'bookings':{'BK-A04':{'status':'confirmed','cabin_class':'economy','price_paid':310,
        'cancellation_fee':None,'refund_amount':None},'other':{'status':'confirmed'}}}


def arguments():
    return {'booking_id':'BK-A04','field':'cancellation_authorized','evidence_ids':['authorization-A','authorization-B']}


def call(name,before,after,args,result=None):
    return {'name':name,'arguments':args,'result':deepcopy(result)if result is not None else {},'before':deepcopy(before),'after':deepcopy(after),'conversation_turn':0}


def calls():
    initial=before();final=deepcopy(initial)
    final['bookings']['BK-A04'].update(status='cancelled',cancellation_fee=0,refund_amount=310)
    return [call('request_user_resolution',initial,initial,arguments(),RESOLUTION),
        call('get_booking',initial,initial,{'booking_id':'BK-A04'}),
        call('cancel_booking',initial,final,{'booking_id':'BK-A04','confirm':True})]


def grade(**changes):
    return conflict_points(contract(),**{'initial':before(),'calls':calls(),'conversation':[],
        'complete':True,'notice_delivered':True,**changes})


def test_distinct_typed_conflict_and_business_checkpoints_have_multiple_and_assertions():
    result=grade()
    assert result['clarification']['score']==result['followthrough']['score']==100
    assert len(result['clarification']['assertions'])==4 and len(result['followthrough']['assertions'])==2
    assert result['memory_adoption_score']is None
    assert grade(calls=[])['clarification']['score']==0


def test_early_mutation_stays_failed_even_when_final_state_is_correct_or_restored():
    rows=calls();early=rows[-1]
    early=call('cancel_booking',before(),early['after'],early['arguments'])
    result=grade(calls=[early,*rows])
    assert result['clarification']['score']==0
    assert grade(notice_delivered=False)['clarification']['score']==0


@pytest.mark.parametrize('field,value',[('booking_id','other'),('field','cabin_class'),
    ('evidence_ids',['authorization-A','authorization-A']),('evidence_ids',None)])
def test_wrong_structured_resolution_never_issues_a_customer_answer(field,value):
    args=dict(arguments(),**{field:value})
    assert not valid_resolution_arguments(args)
    bridge=ConflictEnvironment(SimpleNamespace(tool_handlers={},get_full_snapshot=before))
    assert 'error'in bridge.resolve(args)
    rows=calls();rows[0]['arguments']=args;rows[0]['result']=bridge.resolve(args)
    assert grade(calls=rows)['clarification']['score']==0


def test_schema_null_missing_and_missing_receipts_are_unknown_not_a_free_pass():
    for changes in [{'calls':None},{'initial':None},{'notice_delivered':None},{'complete':False}]:
        result=grade(**changes)
        assert not result['collection_complete']and result['clarification']['score']is None
    rows=calls();rows[0]['result']=None
    assert grade(calls=rows)['clarification']['score']is None
    for value in (None,1):
        rows=calls();rows[0]['result']['value']=value
        assert grade(calls=rows)['clarification']['score']is None


def test_unrelated_field_or_booking_mutation_fails_even_with_correct_required_output():
    rows=calls();rows[-1]['after']['bookings']['BK-A04']['cabin_class']='business'
    assert grade(calls=rows)['followthrough']['score']==0
    rows=calls();rows[-1]['after']['bookings']['other']['status']='cancelled'
    assert grade(calls=rows)['followthrough']['score']==0


def test_resolution_object_is_detached_and_argument_order_is_irrelevant():
    bridge=ConflictEnvironment(SimpleNamespace(tool_handlers={},get_full_snapshot=before))
    args=arguments();args['evidence_ids'].reverse()
    response=bridge.resolve(args);response['value']=False
    assert bridge.resolve(args)==RESOLUTION


def test_missing_real_episode_or_private_journal_stays_unknown_through_existing_cli(tmp_path):
    import json

    from memweave_eval.fixed35_cli import execute
    path=tmp_path/'contract.json';path.write_text(json.dumps(contract()))
    result=execute(SimpleNamespace(fixed35_command='state-conflict',trial=tmp_path/'trial',
        private=tmp_path/'private',contract=path,arm='pi-native',output=tmp_path/'result.json'))
    data=json.loads((tmp_path/'result.json').read_text())
    assert result['paid_requests']==0 and not result['collection_complete']
    assert data['clarification']['score']is None


def test_common_successor_rubric_keeps_fixed_weights_and_does_not_claim_state_adoption():
    rows=common_checkpoint_rows(grade())
    assert all(r['applicability']=='all'and r['score']==100 for r in rows)
    assert all(r['weights']=={'common_product':0,'plugin_memory':0}for r in rows)
    assert all(r['id'].startswith('F35.INT04.')for r in rows)
    assert common_checkpoint_rows(grade(notice_delivered=None))[0]['score']is None


def test_free_cli_actor_refuses_real_credentials_and_nonpreparation_before_install():
    import asyncio

    from memweave_eval.state_conflict_free import ConflictFreePi
    for options in [SimpleNamespace(prepare_only=False,auth_path=None),SimpleNamespace(prepare_only=True,auth_path='real-auth')]:
        with pytest.raises(ValueError,match='no real credentials'):
            asyncio.run(ConflictFreePi.install(SimpleNamespace(options=options),None))


def state_grade(**changes):
    import json
    pending={'F'+str(i):json.dumps(value)for i,value in enumerate(PENDING_RECORDS,1)}
    current={'F3':json.dumps(RESOLVED_RECORD)}
    rows=[{'op':'modify_fact','archive':['F1','F2'],'append_fact':{
        'content':json.dumps(RESOLVED_RECORD),'evidence':{'T3':'Actual customer answer'}}}]
    return state_record_points(**{'pending':pending,'corrected':current,'rows':rows,
        'complete':True,'resolution_ref':'T3','resolution_valid':True,**changes})


def test_typed_state_pending_and_atomic_correction_are_independent_multicheckpoints():
    result=state_grade()
    assert result['pending_record']['score']==result['corrected_record']['score']==100
    assert len(result['pending_record']['assertions'])==2 and len(result['corrected_record']['assertions'])==3
    assert state_grade(pending={})['pending_record']['score']==0
    assert state_grade(rows=[])['corrected_record']['score']==0  # merely adding a correct new record is insufficient
    assert state_grade(resolution_valid=False)['corrected_record']['score']==0


def test_stale_active_record_or_unresolved_source_loss_is_a_known_failure():
    import json
    current={'F1':json.dumps(PENDING_RECORDS[0]),'F3':json.dumps(RESOLVED_RECORD)}
    assert state_grade(corrected=current)['corrected_record']['score']==0
    assert state_grade(pending={'F1':json.dumps(PENDING_RECORDS[0])})['pending_record']['score']==0
    assert state_grade(pending={'F1':json.dumps(RESOLVED_RECORD)})['pending_record']['score']==0


def test_new_strict_current_contract_rejects_competing_authorization_without_rewriting_v1():
    import json
    current={'F3':json.dumps(RESOLVED_RECORD),
        'F4':json.dumps({'src':'another-note','bk':'BK-A04','auth':False})}
    assert state_grade(corrected=current)['corrected_record']['score']==100  # historical v1 rubric preserved
    assert state_grade(corrected=current,strict_current=True)['corrected_record']['score']==0
    assert state_grade(strict_current=True)['corrected_record']['score']==100
    assert state_grade(corrected=None,strict_current=True)['corrected_record']['score']is None


def test_missing_state_checkpoint_or_resolution_link_stays_unknown():
    for changes in [{'pending':None},{'corrected':None},{'complete':False}]:
        data=state_grade(**changes)
        assert data['pending_record']['score']is None and data['corrected_record']['score']is None
    assert state_grade(resolution_ref=None)['corrected_record']['score']is None
    assert state_grade(resolution_valid=None)['corrected_record']['score']is None
    data=state_grade(pending={},corrected={},rows=[],resolution_ref='',resolution_valid=False)
    assert data['pending_record']['score']==data['corrected_record']['score']==0
    assert data['pending_record']['collection_complete']and data['corrected_record']['collection_complete']


def test_native_state_successor_scores_are_structural_na_not_zero():
    behavior=grade();behavior['state_record_protocol']='typed-state-v1';behavior['state_records']=None
    rows=common_checkpoint_rows(behavior,arm='pi-native')
    assert len(rows)==4
    assert all(r['status']=='DESIGN_NA'and r['score']is None and r['support_n']==0 for r in rows[2:])


def test_controlled_record_format_rejects_ambiguous_or_wrong_boolean_fields():
    assert typed_record('{"auth":false,"auth":true,"bk":"BK-A04"}')is None
    assert typed_record('{"auth":1,"bk":"BK-A04"}')is None
    assert typed_record('{"auth":"true","bk":"BK-A04"}')is None


def test_missing_domain_evidence_cannot_omit_frozen_plugin_state_checkpoints(tmp_path):
    from memweave_eval.state_conflict import grade_conflict_trial
    c=dict(contract(),state_record_protocol='typed-state-v1')
    result=grade_conflict_trial(tmp_path/'trial',tmp_path/'private',c,arm='pi-memweave')
    rows=common_checkpoint_rows(result,arm='pi-memweave')
    assert len(rows)==4 and all(r['score']is None for r in rows)
    assert all(r['status']=='MISSING_EVIDENCE'for r in rows)
    assert not result['collection_complete']


def test_historical_checkpoint_recovery_requires_exact_byte_prefix_hash():
    import hashlib
    raw='{"evidence":"证据😀"}\n'.encode();later=raw+b'{"next":true}\n'
    reference={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    assert verified_journal_prefix(later,reference)==raw
    assert verified_journal_prefix(b'corrupt'+later,reference)is None
    assert verified_journal_prefix(later,dict(reference,bytes=len(raw)-1))is None
    assert verified_journal_prefix(later,dict(reference,sha256='0'*64))is None
