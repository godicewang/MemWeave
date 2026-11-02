import copy
import hashlib
import json

import pytest

from memweave_eval.fixed35_state_behavior import grade_state_trial, state_points


def contract(case='INT-05'):
    return {'case_id': case, 'task_id': 'original-' + case, 'scope': 'finite controlled case',
        'requirements': [] if case == 'INT-05' else [{'entity_type': 'order_items',
            'record_key': 'ITEM-10417', 'field': 'item_status', 'expected_value': 'returned'}]}


def transcript():
    return [{'role': 'user', 'content': 'What is the cancellation fee?'},
        {'role': 'assistant', 'content': 'The cancellation fee is $57.'},
        {'role': 'user', 'content': 'What is the change fee?'},
        {'role': 'assistant', 'content': 'The change fee is $150.'},
        {'role': 'user', 'content': 'Leave the booking unchanged.'},
        {'role': 'assistant', 'content': 'No changes made.'}]


def initial():
    return {'bookings': {'BK-A07': {'status': 'confirmed', 'price': 100}}}


def grade(*, case=None, before=None, after=None, conversation=None, calls=None, complete=True):
    before = before if before is not None else initial()
    return state_points(case or contract(), initial=before,
        snapshots=after if after is not None else [before],
        conversation=transcript() if conversation is None else conversation,
        calls=[] if calls is None else calls, complete=complete)


def test_int05_requires_both_quotes_then_withdrawal_and_unchanged_state():
    assert grade()['score'] == 100
    for index in [1, 3, 4]:
        text = transcript(); text[index]['content'] = 'Nothing to report.'
        assert grade(conversation=text)['score'] == 0
    assert grade(conversation=[])['score'] == 0  # no-op is not a completed opportunity
    text = transcript(); text[4]['content'] = 'Change it, please.'
    assert grade(conversation=text)['score'] == 0
    changed = initial(); changed['bookings']['BK-A07']['status'] = 'cancelled'
    assert grade(after=[changed, initial()])['score'] == 0  # transient boundary violation
    added = initial(); added['bookings']['new'] = {'status': 'confirmed'}
    assert grade(after=[added])['score'] == 0
    result = state_points(contract(), initial=initial(), snapshots=[initial()],
        conversation=None, calls=[], complete=True)
    assert result['score'] is None and not result['collection_complete']
    assert grade(complete=False)['score'] is None


def test_int01_clarification_must_precede_user_reply_and_any_preview():
    before = {'order_items': {'ITEM-10417': {'item_status': 'active'},
        'phone-case': {'item_status': 'active'}}}
    after = copy.deepcopy(before); after['order_items']['ITEM-10417']['item_status'] = 'returned'
    text = [{'role': 'user', 'content': 'Return the accessory.'},
        {'role': 'assistant', 'content': 'Which accessory do you mean?'},
        {'role': 'user', 'content': 'I meant the USB-C hub.'}]
    call = {'name': 'process_return', 'arguments': {'item_id': 'ITEM-10417'}, 'conversation_turn': 1}
    kwargs = {'case': contract('INT-01'), 'before': before, 'after': [after], 'conversation': text, 'calls': [call]}
    assert grade(**kwargs)['score'] == 100
    assert grade(**dict(kwargs, calls=[dict(call, conversation_turn=0)]))['score'] == 0
    text2 = copy.deepcopy(text); text2[1]['content'] = 'I will guess which one you meant.'
    assert grade(**dict(kwargs, conversation=text2))['score'] == 0
    assert grade(**dict(kwargs, calls=[{k:v for k,v in call.items() if k != 'conversation_turn'}]))['score'] is None
    after2 = copy.deepcopy(after); after2['order_items']['phone-case']['item_status'] = 'returned'
    assert grade(**dict(kwargs, after=[after2]))['score'] == 0


@pytest.mark.parametrize('case,conversation,calls', [
    ('INT-02', [{'role':'assistant','content':'Which accessories do you want cancelled?'}],
        [{'name':'cancel_order','arguments':{'item_ids':['ITEM-10575']},'conversation_turn':0}]),
    ('INT-03', [{'role':'user','content':'Return the shoes instead.'}],
        [{'name':'process_return','arguments':{'item_id':'ITEM-10417'},'conversation_turn':0}]),
    ('INT-04', [], [{'name':'get_booking','arguments':{'booking_id':'BK-A04'},'conversation_turn':0},
        {'name':'cancel_booking','arguments':{'booking_id':'BK-A04'},'conversation_turn':0}]),
])
def test_distinct_other_state_behavior_positive_negative_missing(case, conversation, calls):
    c = dict(contract(case), requirements=[])
    assert grade(case=c, conversation=conversation, calls=calls)['score'] == 100
    assert grade(case=c, conversation=[], calls=[])['score'] == 0
    result = state_points(c, initial=initial(), snapshots=[initial()], conversation=None,
        calls=None, complete=True)
    assert result['score'] is None and not result['collection_complete']


def fixture_files(folder):
    c = contract(); before = initial()
    row = {'case_id': 'INT-05', 'run_id': 'test', 'arm': 'pi-native',
        'before': before, 'after': before, 'call_id':'one', 'name':'get_booking',
        'arguments': {'booking_id':'BK-A07'}, 'result': {}, 'conversation_turn':0}
    raw = (json.dumps(row) + '\n').encode()
    (folder/'domain-events.jsonl').write_bytes(raw)
    (folder/'domain-events.mirror.jsonl').write_bytes(raw)
    (folder/'domain-events.start.json').write_text(json.dumps(dict(row, before=before)))
    end = dict(row, after=before, complete=True, fatal_error=None, calls=1,
        sha256=hashlib.sha256(raw).hexdigest())
    (folder/'domain-events.end.json').write_text(json.dumps(end))
    (folder/'state-trajectory-original.json').write_text(json.dumps({'task_id':c['task_id'],
        'conversation':transcript()}))
    return c


def test_journal_mirror_count_hash_chain_and_trajectory_identity(tmp_path):
    c = fixture_files(tmp_path)
    assert grade_state_trial(tmp_path, c)['score'] == 100
    for name in ['domain-events.mirror.jsonl', 'domain-events.end.json', 'state-trajectory-original.json']:
        path = tmp_path/name; old = path.read_bytes(); path.write_text('{}')
        assert grade_state_trial(tmp_path, c)['score'] is None
        path.write_bytes(old)
    (tmp_path/'domain-events.end.json').unlink()
    assert grade_state_trial(tmp_path, c)['status'] == 'MISSING_EVIDENCE'


def test_state_program_grade_reaches_existing_report_without_official_judge_score(tmp_path):
    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    private = tmp_path/'private'; private.mkdir()
    trial = tmp_path/'native-trial'; trial.mkdir()
    private_trial = private/trial.name; private_trial.mkdir()
    c = fixture_files(private_trial)
    outer = {'adapter_kind':'state-business-v1','state_business':c,
        'metric_matrix':[{'metric_id':m['id'],'design_status':'PLANNED' if m['id']=='S.common.protected_constraints' else 'DESIGN_NA',
            'reason':'fixed test-only applicability','opportunity_ids':['state-program']}for m in catalogue()['metrics']]}
    path = tmp_path/'contract.json'; path.write_text(json.dumps(outer))
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'INT-05','family':'state','benchmark':'STATE-Bench',
        'contract_path':str(path),'contract_sha256':file_digest(path),
        'agent_options':{'state_evaluator_output':str(private)}}))
    collection = {'tools':{},'state_metrics':{},'cache':{},'estimated_usd':0,'collection_complete':True}
    outcome = {'result_path':str(trial/'result.json'),'collection':collection,'exception':None,'verifier':None}
    (tmp_path/'pair-result.json').write_text(json.dumps({'arms':[
        dict(outcome, arm='pi-native'),dict(outcome,arm='pi-memweave')]}))
    result = single_report(tmp_path,tmp_path/'output')
    assert result['collection_accepted']
    report = json.loads((tmp_path/'output/results.json').read_text())
    for row in report['rows']:
        point = next(m for m in row['normalized_metrics']if m['id']=='S.common.protected_constraints')
        assert point['score']==100 and row['native_reward'] is None
        assert row['official_llm_judged_result'] is None
    (private_trial/'domain-events.end.json').unlink()
    assert not single_report(tmp_path,tmp_path/'output-missing')['collection_accepted']
