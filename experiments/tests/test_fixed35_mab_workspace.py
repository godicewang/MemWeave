import json
import subprocess
from pathlib import Path

import pytest

from memweave_eval.fixed35_mab import grade_mab_trial


@pytest.mark.parametrize('first_value,content_present,expected',[
    ('Steve Jobs',True,100),('Satya Nadella',True,0),('Steve Jobs',False,None)])
def test_first_actual_file_change_via_bash_uses_pre_action_state_and_actual_bytes(tmp_path,first_value,content_present,expected):
    agent=tmp_path/'steps/query/agent';agent.mkdir(parents=True)
    artifacts=agent/'fixed35-artifacts';artifacts.mkdir()
    (agent/'pi.txt').write_text(json.dumps({'type':'message_end','message':{'role':'assistant',
        'content':[{'type':'text','text':'Steve Jobs'}]}})+'\n')
    (artifacts/'answer-presence.json').write_text('{"exists":true}')
    (artifacts/'answer.json').write_text('{"value":"Steve Jobs"}')
    source=tmp_path/'source.md';source.write_text('early source')
    module=Path(__file__).parents[1]/'src/memweave_eval/content_evidence.mjs'
    code=r'''
import {contentEvidence} from MODULE;
const s=contentEvidence(ROOT);
const rows=[{op_id:'g',op:'update_goal',goal:'answer'},
 {op_id:'f',op:'append_fact',id:'F1',fact:'Microsoft CEO Steve Jobs'}];
const state=s.put(rows.map(JSON.stringify).join('\n')+'\n');
s.event('request_ready',{stage_id:'1',request_id:'r',prepared_boundary:{boundary_id:'b',
 expected_task_id:'task',expected_version_at_prepare:2,expected_journal_ref:state},payload_ref:s.put({messages:[]})});
s.event('workspace_checkpoint',{stage_id:'1',phase:'agent_start',workspace:{
 files:{'answer.json':null},file_status:{'answer.json':{status:'absent'}}}});
s.event('task_registry_checkpoint',{stage_id:'1',phase:'before_tool',call_id:'bash',
 binding:{status:'CAPTURED',journal_ref:state}});
s.event('tool_call',{stage_id:'1',tool:'bash',call_id:'bash',record_ref:s.put({input:{command:'opaque shell script writes the answer'}})});
const ref=s.put(JSON.stringify({value:FIRST}));
s.event('workspace_checkpoint',{stage_id:'1',phase:'tool_end',call_id:'bash',workspace:{
 files:{'answer.json':ref.sha256},file_status:{'answer.json':{status:'present'}},
 file_refs:CONTENT?{'answer.json':ref}:{}}});
// A later final correction must not erase the first dependent action.
s.event('workspace_checkpoint',{stage_id:'1',phase:'tool_end',call_id:'later',workspace:{
 files:{'answer.json':s.put('correct final').sha256}}});
'''.replace('MODULE',json.dumps(module.as_uri())).replace('ROOT',json.dumps(str(agent/'request-content'))).replace('FIRST',json.dumps(first_value)).replace('CONTENT',json.dumps(content_present))
    subprocess.run(['node','--input-type=module','-e',code],check=True,capture_output=True,text=True)
    contract={'answers':['Steve Jobs'],'source_instruction_path':str(source),
        'action_observation':'workspace-content-v2','query_stage_id':'1','literal_memory':{
            'required_relations':[['Microsoft','Steve Jobs']],'forbidden_relations':[['Microsoft','Satya Nadella']]}}
    result=grade_mab_trial(tmp_path,contract,arm='pi-memweave')
    assert result['derived_action']['score']==100
    assert result['memory']['correction']['score']==expected
