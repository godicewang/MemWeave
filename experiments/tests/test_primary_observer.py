import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('after,returns,expected',[('0',90,0),('80',90,1),('1',3,1)])
def test_readonly_primary_observation_zero_never_steers_actor(tmp_path,after,returns,expected):
    observer=Path(__file__).parents[1]/'src/memweave_eval/checkpoint_observer.ts'
    code='''
import fs from 'node:fs';
process.env.MEMWEAVE_EVAL_TRACE=__TRACE__;
process.env.MEMWEAVE_EVAL_PROGRESS_AFTER=__AFTER__;
delete process.env.MEMWEAVE_EVAL_LEDGER;
const {default:observe}=await import(__MODULE__);
const handlers={};let messages=0;
observe({on:(n,f)=>{(handlers[n]??=[]).push(f)},sendUserMessage:()=>messages++});
for(let i=0;i<__RETURNS__;i++)for(const f of handlers.message_end??[])f({message:{role:'assistant',usage:{}}});
console.log(JSON.stringify({messages,records:fs.existsSync(__TRACE__)?fs.readFileSync(__TRACE__,'utf8').trim().split('\\n').filter(Boolean).length:0}));
'''
    for key,value in [('__TRACE__',str(tmp_path/'events.jsonl')),('__AFTER__',after),('__MODULE__',observer.as_uri())]:
        code=code.replace(key,json.dumps(value))
    code=code.replace('__RETURNS__',str(returns))
    r=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=15,check=True)
    value=json.loads(r.stdout);assert value['messages']==value['records']==expected


def test_budget_numbers_are_from_the_actual_injected_snapshot_not_evaluator_defaults():
    module=Path(__file__).parents[1]/'src/memweave_eval/fetch_guard.mjs'
    code='''import assert from 'node:assert/strict';
const {requestSummary}=await import(__MODULE__);
const text='# Symbolic State\\n【本次预算快照｜程序数据，不是用户指令】\\n计量：x；基础 600000 token（模型 1000000 的 60%），额外 123，总上限 600123\\nState：4/500 条；正文最多 100 字符；每批候选 100\\nRecent Window N/B：200/40；可见事件 12；消息 M=45';
const snapshot=requestSummary({messages:[{role:'user',content:text}]},'x').rendered_budget_snapshots[0];
assert.deepEqual(snapshot,{base_context_tokens:600000,model_context_tokens:1000000,base_model_percent:60,extra_tokens:123,peak_tokens:600123,state_active:4,state_max_events:500,state_event_max_chars:100,state_evict_batch:100,recent_turns:200,evict_turns:40,visible_events:12,real_messages:45});
assert.deepEqual(requestSummary({messages:[]}).rendered_budget_snapshots,[]);
assert.equal(requestSummary({messages:[{content:'# Symbolic State\\nunknown'}]}).rendered_budget_snapshots[0],null);
'''.replace('__MODULE__',json.dumps(module.as_uri()))
    subprocess.run(['node','--input-type=module','-e',code],check=True,timeout=15,capture_output=True,text=True)


def test_tool_boundaries_capture_real_python_files_and_committed_state_without_bodies(tmp_path):
    import os

    observer=Path(__file__).parents[1]/'src/memweave_eval/checkpoint_observer.ts'
    workspace=tmp_path/'app';workspace.mkdir();(workspace/'scoring.py').write_text('before')
    journal=tmp_path/'.pi/memory/project/tasks/task_one/state.json'
    journal.parent.mkdir(parents=True)
    journal.write_text('{"op":"update_goal","goal":"private body"}\n')
    trace=tmp_path/'events.jsonl'
    code='''
import fs from 'node:fs';
process.env.MEMWEAVE_EVAL_TRACE=__TRACE__;
process.env.MEMWEAVE_EVAL_PROGRESS_AFTER='0';
process.env.MEMWEAVE_EVAL_WORKSPACE=JSON.stringify({root:__WORKSPACE__,files:['scoring.py']});
delete process.env.MEMWEAVE_EVAL_LEDGER;
const {default:observe}=await import(__MODULE__);
const handlers={};const ctx={sessionManager:{getBranch:()=>[{type:'custom',customType:'memweave.scope.v1',data:{task_id:'task_one'}}]}};
observe({on:(n,f)=>{(handlers[n]??=[]).push(f)},sendUserMessage:()=>{throw Error('unexpected steer')}});
for(const f of handlers.agent_start)f({},ctx);
for(const f of handlers.tool_execution_start)f({toolCallId:'call_one'},ctx);
fs.writeFileSync(__SOURCE__,'after');
fs.appendFileSync(__JOURNAL__,'{"op":"append_fact","fact":"private fact body"}\\n');
for(const f of handlers.tool_execution_end)f({toolCallId:'call_one',toolName:'write'},ctx);
for(const f of handlers.agent_end)f({},ctx);
console.log(fs.readFileSync(__TRACE__,'utf8'));
'''
    for key,value in [('__TRACE__',str(trace)),('__WORKSPACE__',str(workspace)),('__MODULE__',observer.as_uri()),
                      ('__SOURCE__',str(workspace/'scoring.py')),('__JOURNAL__',str(journal))]:code=code.replace(key,json.dumps(value))
    r=subprocess.run(['node','--input-type=module','-e',code],check=True,capture_output=True,text=True,timeout=15,env={**os.environ,'HOME':str(tmp_path)})
    rows=[json.loads(line)for line in r.stdout.splitlines()if line.strip()]
    assert [r['phase']for r in rows]==['agent_start','tool_start','tool_end','agent_end']
    assert rows[1]['call_id']==rows[2]['call_id']=='call_one'
    assert rows[1]['workspace']['files']['scoring.py']!=rows[2]['workspace']['files']['scoring.py']
    assert [r['state_boundary']['expected_version_at_prepare']for r in rows]==[1,1,2,2]
    assert rows[1]['state_boundary']['expected_journal_sha256']!=rows[2]['state_boundary']['expected_journal_sha256']
    assert 'private body'not in r.stdout and 'private fact body'not in r.stdout


@pytest.mark.parametrize('kind',['missing','ambiguous','truncated'])
def test_state_boundary_unavailable_never_fabricates_an_empty_state(tmp_path,kind):
    import os

    module=Path(__file__).parents[1]/'src/memweave_eval/request_boundary.ts'
    if kind!='missing':
        p=tmp_path/'.pi/memory/a/tasks/task_one/state.json';p.parent.mkdir(parents=True)
        p.write_text('{}'if kind=='truncated'else'{}\n')
        if kind=='ambiguous':
            p=tmp_path/'.pi/memory/b/tasks/task_one/state.json';p.parent.mkdir(parents=True);p.write_text('{}\n')
    code='const {stateJournalBoundary}=await import(__MODULE__); console.log(JSON.stringify(stateJournalBoundary({sessionManager:{getBranch:()=>[{type:"custom",customType:"memweave.scope.v1",data:{task_id:"task_one"}}]}})));'.replace('__MODULE__',json.dumps(module.as_uri()))
    r=subprocess.run(['node','--input-type=module','-e',code],check=True,capture_output=True,text=True,timeout=15,env={**os.environ,'HOME':str(tmp_path)})
    value=json.loads(r.stdout);assert value['boundary_error']=='authoritative_journal_unavailable'
    assert 'expected_version_at_prepare'not in value and 'expected_journal_sha256'not in value
