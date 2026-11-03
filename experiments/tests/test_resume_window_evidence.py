import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from memweave_eval.fixed35_identity_window import identity_selection, identity_window_checkpoint


def resumed_fixture():
    source=[{'role':'user','content':'source A'},
        {'role':'assistant','content':[{'type':'text','text':'A acknowledged'}]},
        {'role':'user','content':'unrelated B'},
        {'role':'assistant','content':[{'type':'text','text':'B acknowledged'}]},
        {'role':'user','content':'return to A'},
        {'role':'assistant','content':[{'type':'toolCall','id':'resume-call','name':'task_resume','arguments':{'task_id':'A'}}]},
        {'role':'toolResult','toolCallId':'resume-call','content':[{'type':'text','text':'restored'}]}]
    ids=['uA','aA','uB','aB','trigger','resume','result'];messages=[]
    for identity,message in zip(ids,source,strict=True):
        messages.append({'id':identity,'role':message['role'],'sha256':identity,'stop_reason':None,
            'calls':['resume-call']if identity=='resume'else[],
            'result_id':'resume-call'if identity=='result'else None})
    ledger=[]
    def add(identity,kind='message',custom=None,data=None):
        row={'id':identity,'parent_id':ledger[-1]['id']if ledger else None,'type':kind}
        if custom:row.update(custom_type=custom,data=data)
        ledger.append(row)
    add('scope-A','custom','memweave.scope.v1',{'task_id':'A'})
    add('uA');add('aA');add('scope-B','custom','memweave.scope.v1',{'task_id':'B'})
    add('uB');add('aB');add('trigger');add('resume')
    receipt={'task_id':'A','source_session_id':'s','source_anchor_entry_id':'aB',
        'target_anchor_entry_id':'aB','recent_turns':20,'evict_turns':4,'seed_event_ids':['uA','aA']}
    add('receipt','custom','memweave.resume.v1',receipt)
    add('scope-A2','custom','memweave.scope.v1',{'task_id':'A'});add('result')
    shape={'version':'native-window-shape-v2','session_id':'s','previous_window':None,
        'unsupported_lifecycle':True,'messages':messages,'branch_ledger':ledger}
    descriptors=[{'entry_id':identity,'sha256':identity}for identity in ids]
    payload={'messages':[{'role':'user','content':'source A'},{'role':'assistant','content':'A acknowledged'},
        {'role':'user','content':'return to A'},{'role':'assistant','content':'','tool_calls':[{
            'id':'resume-call','type':'function','function':{'name':'task_resume','arguments':'{"task_id":"A"}'}}]},
        {'role':'tool','tool_call_id':'resume-call','content':'restored'}]}
    return shape,descriptors,source,payload


def test_same_session_frozen_seed_excludes_other_goal_and_preserves_complete_resume_tool_event():
    shape,descriptors,source,payload=resumed_fixture()
    ids,window=identity_selection(shape,recent_turns=20,evict_turns=4)
    assert ids==['uA','aA','trigger','resume','result']
    assert identity_window_checkpoint(shape,descriptors,source,payload,window,recent_turns=20,evict_turns=4)[0]is True
    payload['messages'].insert(2,{'role':'user','content':'unrelated B'})
    assert identity_window_checkpoint(shape,descriptors,source,payload,window,recent_turns=20,evict_turns=4)[0]is False


@pytest.mark.parametrize('part',['seed','task','source_anchor','tool_pair','empty_owner'])
def test_known_wrong_resume_metadata_or_pair_is_not_accepted(part):
    shape,descriptors,source,payload=resumed_fixture();_,window=identity_selection(shape,recent_turns=20,evict_turns=4)
    receipt=shape['branch_ledger'][8]['data']
    if part=='seed':receipt['seed_event_ids']=['uB','aB']
    if part=='task':receipt['task_id']='B'
    if part=='source_anchor':receipt['source_anchor_entry_id']='receipt'
    if part=='tool_pair':shape['messages'][-1]['result_id']='another-call'
    if part=='empty_owner':receipt.update(task_id='missing-task',seed_event_ids=[])
    assert identity_window_checkpoint(shape,descriptors,source,payload,window,recent_turns=20,evict_turns=4)[0]is False


@pytest.mark.parametrize('part',['ledger','foreign','restart','ancestry','owner_record','prior'])
def test_missing_or_out_of_scope_resume_evidence_remains_unknown(part):
    shape,descriptors,source,payload=resumed_fixture();_,window=identity_selection(shape,recent_turns=20,evict_turns=4)
    if part=='ledger':shape.pop('branch_ledger')
    if part=='foreign':shape['branch_ledger'][8]['data']['source_session_id']='foreign'
    if part=='restart':shape['branch_ledger'].append({'id':'restart','type':'custom','parent_id':'result','custom_type':'memweave.restart.v1','data':{}})
    if part=='ancestry':shape['branch_ledger'][1]['parent_id']='missing'
    if part=='owner_record':shape['branch_ledger'][0]['data']={}
    if part=='prior':shape['previous_window']={'old':'before latest resume'}
    assert identity_window_checkpoint(shape,descriptors,source,payload,window,recent_turns=20,evict_turns=4)[0]is None


def test_source_bootstrap_reference_ownership_and_current_n_expansion_are_independent():
    shape,*_=resumed_fixture();shape=deepcopy(shape)
    shape['branch_ledger'][0].update(custom_type='memweave.references.v1',data={'task_id':'A','bindings':[
        {'entry_id':'uA','ref':'U1'},{'entry_id':'aA','ref':'A1'}]})
    # No source scope points to A; raw recorded reference ownership restores it.
    shape['branch_ledger'][8]['data'].update(recent_turns=1,evict_turns=1,seed_event_ids=['aA'])
    ids,_=identity_selection(shape,recent_turns=2,evict_turns=1)
    assert ids[:2]==['uA','aA']


def test_read_only_emitter_scopes_prior_and_freezes_raw_metadata_without_copying_chat():
    module=Path(__file__).parents[1]/'src/memweave_eval/request_boundary.ts'
    script='''import {nativeShape}from MODULE;
const branch=[{id:'u',parentId:null,type:'message',message:{role:'user',content:'private chat source'}},
 {id:'old',parentId:'u',type:'custom',customType:'memweave.window.v1',data:{old:true}},
 {id:'resume',parentId:'old',type:'custom',customType:'memweave.resume.v1',data:{task_id:'A'}}];
const first=nativeShape(branch,'s');
if(first.previous_window!==null||first.version!=='native-window-shape-v2'||first.branch_ledger.length!==3)throw Error('missing reset');
branch.push({id:'new',parentId:'resume',type:'custom',customType:'memweave.window.v1',data:{pending:['frozen']}});
const second=nativeShape(branch,'s');branch[3].data.pending.push('late');
if(second.previous_window.pending.length!==1||second.branch_ledger[3].data.pending.length!==1)throw Error('snapshot mutated');
if(JSON.stringify(second).includes('private chat source'))throw Error('ledger copied chat');
console.log('ok');
'''.replace('MODULE',json.dumps(str(module)))
    out=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],
        text=True,capture_output=True,check=True,timeout=10)
    assert out.stdout.strip()=='ok'
