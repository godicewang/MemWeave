import io
import json
import tarfile

from memweave_eval.contract_evidence import task_contract_metrics
from memweave_eval.state_metrics import stable_id


def test_real_shaped_receipt_and_journal_bound_actual_request(tmp_path):
    agent = tmp_path/'agent'
    sessions = agent/'pi/sessions'
    sessions.mkdir(parents=True)
    task, session, assistant, call = 'task_a', 'session', 'a', 'call'
    base = stable_id(task, session, assistant, call)
    journal = [{'op':'update_goal','op_id':'initial','goal':'g','evidence':{}},
               {'op':'append_fact','op_id':stable_id(base,0),'id':'F1','fact':'f','evidence':{'U1':'u'}}]
    with tarfile.open(agent/'memory.tar.gz', 'w:gz') as archive:
        data = ''.join(json.dumps(e)+'\n' for e in journal).encode()
        member = tarfile.TarInfo('memory/project/tasks/task_a/state.json')
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    entries = [{'type':'session','id':session},
        {'id':assistant,'message':{'role':'assistant','content':[{'type':'toolCall','id':call,'name':'state_append','arguments':{'items':[{}]}}]}},
        {'id':'r','parentId':assistant,'message':{'role':'toolResult','toolCallId':call,'toolName':'state_append','isError':False,'content':[{'type':'text','text':'State updated: v2'}]}}]
    (sessions/'s.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in entries))
    request = {'event':'request_ready','request_id':'req','messages':[{'role':'tool','tool_call_id':call}],
               'state_blocks':[{'task_id':task,'version':2}]}
    (agent/'request-trace.jsonl').write_text(json.dumps(request)+'\n')
    (agent/'pi.txt').write_text('')
    result = task_contract_metrics(agent, enabled=True)
    assert result['state_confirmed_receipt_lower_bound']['value'] == 1
    assert result['state_latest_at_prepare']['value'] is None
    request['state_blocks'][0]['version'] = 1
    (agent/'request-trace.jsonl').write_text(json.dumps(request)+'\n')
    assert task_contract_metrics(agent, enabled=True)['state_confirmed_receipt_lower_bound']['value'] == 0
    assert result['reference_integrity']['status'] == 'not_applicable'
    assert result['window_integrity']['status'] == 'unknown'


def test_absent_sources_are_unknown_and_native_State_is_na(tmp_path):
    result = task_contract_metrics(tmp_path, enabled=True)
    assert result['state_latest_at_prepare']['status'] == 'unknown'
    assert result['reference_integrity']['status'] == 'unknown'
    native = task_contract_metrics(tmp_path, enabled=False)
    assert native['state_latest_at_prepare']['status'] == 'not_applicable'
    sessions = tmp_path/'pi/sessions'
    sessions.mkdir(parents=True)
    (sessions/'legacy.jsonl').write_text(json.dumps({'message':{'role':'assistant','usage':{}}})+'\n')
    (tmp_path/'request-trace.jsonl').write_text(json.dumps({'event':'workspace_checkpoint'})+'\n')
    (tmp_path/'pi.txt').write_text('legacy log without execution events\n')
    legacy = task_contract_metrics(tmp_path, enabled=True)
    assert legacy['state_latest_at_prepare']['status'] == 'unknown'
    assert legacy['reference_integrity']['status'] == 'unknown'
