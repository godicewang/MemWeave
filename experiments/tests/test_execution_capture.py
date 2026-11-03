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
