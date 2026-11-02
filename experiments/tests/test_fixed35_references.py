import json
import os
import subprocess
from pathlib import Path

import pytest

from memweave_eval.fixed35_references import known_text_read


def source():
    return {'max_total_chars':1000,'items':[{'requested_ref':'U1','offset':1,'limit':2,
        'status':'CAPTURED_KNOWN_TEXT','source_ref_cas':{'sha256':'a'*64},'total_chars':5,
        'source_task_id':'task_a','source_ref':'U1','source_session_id':'session','entry_id':'entry'}]}


def observed():
    return {'items':[{'ref':'U1','source_task_id':'task_a','source_ref':'U1',
        'source_session_id':'session','entry_id':'entry','offset':1,'content':'😀中',
        'total_chars':5,'source_complete':True,'range_complete':True,'truncated':True,'status':'ok'}]}


def test_immutable_scope_projection_unicode_range_and_truncation_independent_checks():
    read=lambda ref:'a😀中\nb'
    assert known_text_read(source(),observed(),read_source=read)['value']==1
    for field,value in [('source_task_id','wrong'),('entry_id','stale'),('content','xx'),
        ('total_chars',6),('truncated',False),('offset',0)]:
        data=observed();data['items'][0][field]=value
        assert known_text_read(source(),data,read_source=read)['value']==0
    assert known_text_read(source(),None,read_source=read)['unknown']==1
    data=observed();data['items'][0]['range_complete']=False
    assert known_text_read(source(),data,read_source=read)['unknown']==1
    assert known_text_read(dict(source(),max_total_chars=None),observed(),read_source=read)['unknown']==1


def test_actual_source_capture_uses_public_binding_and_raw_original_without_writing_state(tmp_path):
    module=Path(__file__).parents[1]/'src/memweave_eval/reference_source.ts'
    code=r'''
import {captureReferenceSources}from MODULE;
const entries=[{id:'entry',type:'message',message:{role:'user',content:[{type:'text',text:'a😀中\r\nb'}]}},
{type:'custom',customType:'memweave.references.v1',data:{task_id:'task_a',source_session_id:'session',bindings:[{ref:'U1',entry_id:'entry'}]}}];
const ctx={sessionManager:{getBranch:()=>entries,getEntries:()=>entries,getSessionId:()=>'session'}};
console.log(JSON.stringify(captureReferenceSources(ctx,{items:[{ref:'U1'}],max_total_chars:1000},{taskId:'task_a',memoryRoot:ROOT})));
'''.replace('MODULE',json.dumps(module.as_uri())).replace('ROOT',json.dumps(str(tmp_path/'memory')))
    result=json.loads(subprocess.check_output(['node','--input-type=module','-e',code],text=True,
        env=dict(os.environ,MEMWEAVE_EVAL_CONTENT_STORE=str(tmp_path/'cas'))))
    assert result['complete']and result['items'][0]['total_chars']==5
    assert result['items'][0]['source_session_id']=='session'
    assert result['items'][0]['source_ref_cas']['sha256']
    assert not(tmp_path/'memory').exists()


@pytest.mark.parametrize('flat',[True,False])
def test_original_public_tool_result_and_execution_end_shapes_both_replay(tmp_path,flat):
    from memweave_eval.fixed35_references import grade_known_references
    module=Path(__file__).parents[1]/'src/memweave_eval/content_evidence.mjs'
    gold=source();actual=observed()
    payload={'isError':False,**({'content':[{'type':'text','text':json.dumps(actual)}]}if flat else
        {'result':{'content':[{'type':'text','text':json.dumps(actual)}]}})}
    code=r'''
import{contentEvidence}from MODULE;const s=contentEvidence(ROOT);const gold=GOLD;
gold.items[0].source_ref_cas=s.put('a😀中\nb');
s.event('tool_call',{tool:'memory_read',call_id:'call',record_ref:s.put({input:{items:[{ref:'U1'}]}})});
s.event('reference_source',{call_id:'call',source:gold});
s.event(KIND,{call_id:'call',record_ref:s.put(PAYLOAD)});
'''.replace('MODULE',json.dumps(module.as_uri())).replace('ROOT',json.dumps(str(tmp_path/'agent/request-content'))).replace('GOLD',json.dumps(gold)).replace('KIND',json.dumps('tool_result'if flat else'tool_execution_end')).replace('PAYLOAD',json.dumps(payload))
    subprocess.run(['node','--input-type=module','-e',code],check=True,capture_output=True,text=True)
    metric=grade_known_references(tmp_path)
    assert metric['value']==1 and metric['unknown']==0
