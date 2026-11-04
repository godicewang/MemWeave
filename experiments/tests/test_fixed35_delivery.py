import pytest

from memweave_eval.fixed35_delivery import delivery_metrics


def ready(identity,expected=3,delivered=3):
    message={'role':'user','sha256':'source','tool_call_id':None,'tool_calls':[]}
    return {'event':'request_ready','request_id':identity,'expected_task_id':'task_test',
        'boundary_source':'atomic_journal_before_context_transform',
        'expected_version_at_prepare':expected,'state_blocks':[{'task_id':'task_test','version':delivered}],
        'prepared_messages':[message],'messages':[message], 'unresolved_template':False}


def test_every_stage_contributes_once_and_stale_later_stage_is_not_hidden():
    a,b=ready('stage-1'),ready('stage-2',4,3)
    result=delivery_metrics([a,a,b],{'stage-1','stage-2'},enabled=True)
    assert result['complete'] and result['engineering']['http_attempts']==2
    assert result['state_latest_at_prepare']['value']==.5
    assert result['provider_delivery_integrity']['value']==1
    assert delivery_metrics([a],{'stage-1'},enabled=False)['state_latest_at_prepare']['status']=='not_applicable'


def test_missing_preparation_keeps_denominator_and_conflicting_copies_fail():
    a=ready('a')
    result=delivery_metrics([a],{'a','missing'},enabled=True)
    assert not result['complete'] and result['engineering']['request_ready_coverage']==.5
    assert result['state_latest_at_prepare']['unknown']==1
    assert result['provider_delivery_integrity']['unknown']==1
    with pytest.raises(ValueError,match='conflicting'):
        delivery_metrics([a,dict(a,expected_version_at_prepare=9)],{'a'},enabled=True)


def test_confirmed_receipt_floor_is_distinct_from_full_boundary_freshness():
    a=ready('a',3,3);a['messages'].append({'role':'tool','tool_call_id':'write1'})
    result=delivery_metrics([a],{'a'},enabled=True,confirmed_receipts={'write1':{('task_test',4)}})
    assert result['state_latest_at_prepare']['value']==1
    assert result['state_confirmed_receipt_lower_bound']['value']==0
    assert delivery_metrics([a],{'a'},enabled=True,confirmed_receipts={})['state_confirmed_receipt_lower_bound']['status']=='not_applicable'
    assert delivery_metrics([a],{'a'},enabled=True)['state_confirmed_receipt_lower_bound']['status']=='unknown'
