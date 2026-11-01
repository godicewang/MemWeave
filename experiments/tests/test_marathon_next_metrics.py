import json
from pathlib import Path
import pytest
from memweave_eval import marathon_metrics as adapter

GOLD=json.loads((Path(__file__).parents[1]/'cases/marathon-two-tasks-v1.json').read_text())

@pytest.mark.parametrize('task',['zstd-decoder','rust-c-compiler'])
@pytest.mark.parametrize('condition',['positive','negative','missing'])
def test_two_official_task_adapters_have_real_distinct_predicates(tmp_path,monkeypatch,task,condition):
    config=GOLD['tasks'][task]
    agent=tmp_path/'agent';agent.mkdir()
    results=[]
    if condition!='missing':
        files=dict(config['protected_hashes'])
        if condition=='negative':files={k:'changed'for k in files}
        event={'event':'workspace_checkpoint','workspace':{'files':files}}
        (agent/'request-trace.jsonl').write_text(json.dumps(event)+'\n')
        command='bash /app/test.sh'if task=='zstd-decoder'else'bash /app/run_tests.sh'
        results=[({'id':'test-event'},{'isError':condition=='negative','toolCallId':'t'}, {'arguments':{'command':command}})]
    monkeypatch.setattr(adapter,'_originals',lambda _: (results,{}))
    out=adapter.marathon_metrics(agent,GOLD,task_id=task,enabled=True)
    expected=1 if condition=='positive' else 0 if condition=='negative'else None
    assert all(c['value']==expected for c in out['cases'])
    assert out['constraint_retention_proxy']['value']is None


def test_reading_script_is_not_running_it(tmp_path,monkeypatch):
    agent=tmp_path/'agent';agent.mkdir()
    monkeypatch.setattr(adapter,'_originals',lambda _: ([({'id':'r'},{'isError':False},{'arguments':{'command':'cat /app/run_tests.sh'}})],{}))
    out=adapter.marathon_metrics(agent,GOLD,task_id='rust-c-compiler',enabled=False)
    assert out['cases'][0]['value']==0
