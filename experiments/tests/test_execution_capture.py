import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from harbor.agents.installed.pi import Pi

from memweave_eval.execution_capture import scoped_execution_boundaries
from memweave_eval.pi_agent import ExperimentPi
from memweave_eval.storage import file_digest


def capture(root,identity,stage):
    folder=root/'execution-invocations';folder.mkdir(parents=True,exist_ok=True)
    output=folder/(identity+'.stdout.jsonl')
    output.write_text('\n'.join(json.dumps(r)for r in [{'type':'agent_start'},
        {'type':'tool_execution_start','toolCallId':'reused'},
        {'type':'tool_execution_end','toolCallId':'reused'},{'type':'agent_end'}])+'\n')
    row={'schema_version':1,'invocation_id':identity,'stage_id':stage,'status':'RETURNED',
        'capture_status':'CAPTURED','stdout_file':output.name,
        'stdout_sha256':file_digest(output),'stdout_bytes':output.stat().st_size}
    (folder/(identity+'.json')).write_text(json.dumps(row))
    def event(kind,**extra):return dict(event=kind,execution_invocation_id=identity,stage_id=stage,
        producer_id=identity,timestamp='2026-11-03T00:00:00Z',**extra)
    return [event('workspace_checkpoint',phase='agent_start'),event('tool_call',call_id='reused'),
        event('workspace_checkpoint',phase='tool_end',call_id='reused'),event('workspace_checkpoint',phase='agent_end')]


def test_reused_ids_across_stages_cannot_cover_another_stages_missing_hook(tmp_path):
    events=capture(tmp_path/'a','first','1')+capture(tmp_path/'b','second','2')
    assert scoped_execution_boundaries(tmp_path,events)['expected_tool_calls']==2
    assert scoped_execution_boundaries(tmp_path,events)['complete']
    missing=[e for e in events if not(e['execution_invocation_id']=='second'and e.get('phase')=='tool_end')]
    assert not scoped_execution_boundaries(tmp_path,missing)['complete']
    assert not scoped_execution_boundaries(tmp_path,events[:4])['complete']
    assert not scoped_execution_boundaries(tmp_path,events+[dict(events[1],execution_invocation_id='lost')])['complete']


def test_stdout_binding_requires_hash_and_matching_stage(tmp_path):
    events=capture(tmp_path,'one','1')
    assert not scoped_execution_boundaries(tmp_path,[dict(e,stage_id='other')for e in events])['complete']
    (tmp_path/'execution-invocations/one.stdout.jsonl').write_text('{}\n')
    with pytest.raises(ValueError,match='hash differs'):scoped_execution_boundaries(tmp_path,events)


def test_cumulative_stage_copies_require_explicit_scope_not_inferred_from_remaining_events(tmp_path):
    first=capture(tmp_path/'a','first','1');second=capture(tmp_path/'b','second','2')
    assert scoped_execution_boundaries(tmp_path,second,stage_id='2')['complete']
    assert not scoped_execution_boundaries(tmp_path,second)['complete']
    assert not scoped_execution_boundaries(tmp_path,[],stage_id='2')['complete']
    assert not scoped_execution_boundaries(tmp_path,first,stage_id='nonexistent')['complete']


def test_missing_assistant_callback_is_not_mistaken_for_an_observed_empty_answer(tmp_path):
    events=capture(tmp_path,'one','1');folder=tmp_path/'execution-invocations'
    output=folder/'one.stdout.jsonl';rows=output.read_text().splitlines()
    rows.insert(-1,json.dumps({'type':'message_end','message':{'role':'assistant'}}));output.write_text('\n'.join(rows)+'\n')
    path=folder/'one.json';manifest=json.loads(path.read_text());manifest.update(stdout_sha256=file_digest(output),stdout_bytes=output.stat().st_size)
    path.write_text(json.dumps(manifest))
    assert not scoped_execution_boundaries(tmp_path,events)['complete']
    events.append(dict(events[0],event='assistant_return'))
    assert scoped_execution_boundaries(tmp_path,events)['complete']


def terminated_capture(root,*,external=False):
    events=capture(root,'one','1');folder=root/'execution-invocations'
    output=folder/'one.stdout.jsonl';rows=[json.loads(s)for s in output.read_text().splitlines()]
    output.write_text('\n'.join(json.dumps(r)for r in rows if r['type']not in {'agent_end','tool_execution_end'})+'\n')
    path=folder/'one.json';manifest=json.loads(path.read_text());manifest.update(status='EXECUTION_RAISED',
        error_class='NonZeroAgentExitCodeError',started_at=1793750390,finished_at=1793750401,
        stdout_sha256=file_digest(output),stdout_bytes=output.stat().st_size);path.write_text(json.dumps(manifest))
    events=[e for e in events if e.get('phase')not in {'agent_end','tool_end'}]
    events.append(dict(events[0],event='execution_terminated',phase='execution_terminated',sequence=4,
        timestamp='2026-11-04T00:00:00Z',owner_pid=25,signal='SIGTERM',scheduled_deadline=1793750400,
        observation_source='evaluation_signal_microtask_not_native_agent_end',capture_status='CAPTURED',
        workspace={'files':{},'file_status':{}},registry={'complete':True,'tasks':[]}))
    (root/'request-trace.jsonl').write_text(json.dumps({'event':'local_deadline_stop','pid':25,'timestamp':1793750400})+'\n')
    if external:
        import gzip
        import hashlib
        raw=(root/'request-trace.jsonl').read_bytes();digest=hashlib.sha256(raw).hexdigest()
        p=root/'request-content/objects'/(digest+'.gz');p.parent.mkdir(parents=True);p.write_bytes(gzip.compress(raw))
        event=events[-1];event.pop('signal');event.update(event='execution_deadline_snapshot',phase='execution_deadline_snapshot',
            observation_source='evaluation_external_after_deadline_guard',
            guard_stop_ref={'object':'objects/'+p.name,'sha256':digest,'bytes':len(raw)})
    return events


@pytest.mark.parametrize('external',[False,True])
def test_verified_deadline_retains_cancellation_instead_of_fabricating_result(tmp_path,external):
    events=terminated_capture(tmp_path,external=external);result=scoped_execution_boundaries(tmp_path,events)
    assert result['complete']and result['terminal_execution_observed']
    assert result['native_terminal_execution_observed']is False
    assert result['completed_tool_calls']==0 and len(result['deadline_cancelled_tool_calls'])==1
    assert result['deadline_cancelled_tool_calls'][0]['call_id']=='reused'


def test_external_snapshot_requires_actual_guard_object_and_matching_run(tmp_path):
    events=terminated_capture(tmp_path,external=True)
    events[-1]['guard_stop_ref']['sha256']='0'*64
    assert not scoped_execution_boundaries(tmp_path,events)['complete']


@pytest.mark.parametrize('mode',['no_guard','wrong_pid','early','failed_capture','wrong_stage',
    'missing_registry','incomplete_tree','missing_tool_hook','missing_assistant','missing_completed_post'])
def test_signal_does_not_waive_missing_or_unrelated_evidence(tmp_path,mode):
    events=terminated_capture(tmp_path);end=events[-1]
    if mode=='no_guard':(tmp_path/'request-trace.jsonl').unlink()
    elif mode=='wrong_pid':end['owner_pid']=26
    elif mode=='early':end['scheduled_deadline']+=60
    elif mode=='failed_capture':end['capture_status']='FAILED'
    elif mode=='wrong_stage':end['stage_id']='2'
    elif mode=='missing_registry':end.pop('registry')
    elif mode=='incomplete_tree':end['workspace']['tree_projections']={'tree':{'complete':False}}
    elif mode=='missing_tool_hook':events=[e for e in events if e['event']!='tool_call']
    elif mode in {'missing_assistant','missing_completed_post'}:
        path=tmp_path/'execution-invocations/one.json';m=json.loads(path.read_text());out=path.parent/m['stdout_file']
        row={'type':'message_end','message':{'role':'assistant'}}if mode=='missing_assistant'else{'type':'tool_execution_end','toolCallId':'reused'}
        out.write_text(out.read_text()+json.dumps(row)+'\n');m.update(stdout_sha256=file_digest(out),stdout_bytes=out.stat().st_size);path.write_text(json.dumps(m))
    assert not scoped_execution_boundaries(tmp_path,events)['complete']


@pytest.mark.parametrize('line,accepted',[
    ('[MemWeave] MODEL_CAPACITY_UNVERIFIED: provider metadata could not be verified',True),
    ('[MemWeave] arbitrary output',False),('{"type":"message_end"',False),
    ('ordinary program text',False)])
def test_exact_native_fail_closed_diagnostic_is_retained_not_mistaken_for_truncated_json(tmp_path,line,accepted):
    events=capture(tmp_path,'one','1');folder=tmp_path/'execution-invocations';output=folder/'one.stdout.jsonl'
    output.write_text(line+'\n'+output.read_text());path=folder/'one.json';manifest=json.loads(path.read_text())
    manifest.update(stdout_sha256=file_digest(output),stdout_bytes=output.stat().st_size);path.write_text(json.dumps(manifest))
    result=scoped_execution_boundaries(tmp_path,events)
    assert result['complete']is accepted
    if accepted:assert result['native_diagnostics'][0]['code']=='MODEL_CAPACITY_UNVERIFIED'


def rejected_capture(root,*,duration=False,wrong_error=False,missing_result=False,error_text=None):
    import gzip
    import hashlib
    folder=root/'execution-invocations';folder.mkdir(parents=True)
    call={'type':'toolCall','id':'bad-json','name':'state_append','arguments':{}}
    start={'type':'tool_execution_start','toolCallId':'bad-json','toolName':'state_append','args':{}}
    text='ordinary execute failure'if wrong_error else'Invalid arguments for tool "state_append": invalid JSON'
    if error_text is not None:text=error_text
    end={'type':'tool_execution_end','toolCallId':'bad-json','toolName':'state_append',
        'isError':True,'result':{'content':[{'type':'text','text':text}]}}
    if duration:end['durationMs']=0
    result={'type':'message_end','message':{'role':'toolResult','toolCallId':'bad-json',
        'toolName':'state_append','isError':True,'content':end['result']['content']}}
    rows=[{'type':'agent_start'},{'type':'message_end','message':{'role':'assistant','content':[call]}},
        start,end,*([]if missing_result else[result]),{'type':'agent_end'}]
    output=folder/'one.stdout.jsonl';output.write_text('\n'.join(json.dumps(r)for r in rows)+'\n')
    (folder/'one.json').write_text(json.dumps({'schema_version':1,'invocation_id':'one','stage_id':'1',
        'capture_status':'CAPTURED','status':'RETURNED','stdout_file':output.name,
        'stdout_sha256':file_digest(output),'stdout_bytes':output.stat().st_size}))
    def event(kind,**extra):return {'event':kind,'execution_invocation_id':'one','stage_id':'1',
        'producer_id':'one','timestamp':'2026-11-04T00:00:00Z',**extra}
    events=[event('workspace_checkpoint',phase='agent_start'),event('assistant_return')]
    for record in [start,end]:
        raw=json.dumps(record).encode();digest=hashlib.sha256(raw).hexdigest()
        store=root/'request-content';p=store/'objects'/(digest+'.gz');p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(gzip.compress(raw));ref={'object':'objects/'+p.name,'sha256':digest,'bytes':len(raw)}
        events.append(event(record['type'],tool='state_append',call_id='bad-json',record_ref=ref))
    events.extend([event('workspace_checkpoint',phase='tool_end',call_id='bad-json'),
        event('workspace_checkpoint',phase='agent_end')])
    return events


def test_actual_preparation_rejection_has_no_tool_call_hook_but_complete_independent_proof(tmp_path):
    events=rejected_capture(tmp_path)
    result=scoped_execution_boundaries(tmp_path,events)
    assert result['complete']and result['expected_tool_calls']==1
    assert len(result['pre_execution_rejections'])==1
    assert result['pre_execution_rejections'][0]['tool']=='state_append'


@pytest.mark.parametrize('text',[
    'Validation failed for tool "state_append":\nmissing field',
    'Tool state_append not found',
    'Tool call "state_append" was not executed: the response hit the output token limit, so its arguments may be truncated. Re-issue the tool call with complete arguments.'])
def test_other_exact_pi_preparation_paths_have_the_same_strict_proof(tmp_path,text):
    assert scoped_execution_boundaries(tmp_path,rejected_capture(tmp_path,error_text=text))['complete']


def test_unknown_tool_suffix_is_not_an_exact_native_rejection(tmp_path):
    events=rejected_capture(tmp_path,error_text='Tool state_append not found in my output')
    assert not scoped_execution_boundaries(tmp_path,events)['complete']


@pytest.mark.parametrize('mode',['duration','wrong_error','missing_result','missing_start','missing_post','missing_object'])
def test_arbitrary_execute_error_or_missing_proof_cannot_waive_a_lost_hook(tmp_path,mode):
    events=rejected_capture(tmp_path,**{mode:True}if mode in {'duration','wrong_error','missing_result'}else{})
    if mode=='missing_start':events=[e for e in events if e['event']!='tool_execution_start']
    if mode=='missing_post':events=[e for e in events if e.get('phase')!='tool_end']
    if mode=='missing_object':next((tmp_path/'request-content/objects').iterdir()).unlink()
    assert not scoped_execution_boundaries(tmp_path,events)['complete']


@pytest.mark.parametrize('raise_execution',[False,True])
def test_public_pi_exec_capture_also_runs_after_execution_exception(tmp_path,raise_execution):
    agent=ExperimentPi(logs_dir=tmp_path,model_name='deepseek/deepseek-flash',version='1.4.0',
        node_version='24.22.0',variant='pi-native',package_path='/tmp/a',package_sha256='a'*64,
        auth_path='',protocol='fixed35',evaluation_deadline=2000000000,evaluation_content_evidence=True)
    agent._asset_root='/opt/runtime';agent._experiment_home='/root';agent._evaluation_task_id='case'
    agent._evaluation_task_config={};agent._evaluation_sealed=False;agent._evaluation_stage=2
    async def execute(self,environment,command,**kwargs):
        assert kwargs['env']['MEMWEAVE_EVAL_INVOCATION_ID']
        assert 'pi --print --mode json'in command
        if raise_execution:raise TimeoutError('fixture interruption')
        return SimpleNamespace(return_code=0)
    class Environment:
        async def download_file(self,source,target):
            assert str(source)=='/logs/agent/pi.txt';Path(target).write_text('{"type":"agent_end"}\n')
    with patch.object(Pi,'exec_as_agent',execute):
        if raise_execution:
            with pytest.raises(TimeoutError):asyncio.run(agent.exec_as_agent(Environment(),'pi --print --mode json x'))
        else:asyncio.run(agent.exec_as_agent(Environment(),'pi --print --mode json x'))
    rows=list((tmp_path/'execution-invocations').glob('*.json'));assert len(rows)==1
    row=json.loads(rows[0].read_text())
    assert row['stage_id']=='2'and row['capture_status']=='CAPTURED'
    assert row['status']==('EXECUTION_RAISED'if raise_execution else'RETURNED')
