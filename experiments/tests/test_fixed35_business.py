import pytest

from memweave_eval.fixed35_business import readonly_checkpoint

PATHS=['/app/app/types.py','/app/app/DESIGN.md','/app/app/__init__.py']


def test_readonly_checkpoint_has_seven_independent_required_assertions():
    facts=['READ_ONLY '+p for p in PATHS];initial={p:'a'*64 for p in PATHS}
    point=readonly_checkpoint(PATHS,facts,initial,[initial,initial],changed_boundary_known=True,boundaries_complete=True)
    assert point['score']==100 and len(point['assertions'])==7
    for missing in range(3):
        assert readonly_checkpoint(PATHS,facts[:missing]+facts[missing+1:],initial,[initial,initial],changed_boundary_known=True,boundaries_complete=True)['score']==0
        changed=dict(initial);changed[PATHS[missing]]='b'*64
        assert readonly_checkpoint(PATHS,facts,initial,[initial,changed],changed_boundary_known=True,boundaries_complete=True)['score']==0
    assert readonly_checkpoint(PATHS,facts,initial,[initial],changed_boundary_known=False,boundaries_complete=True)['score']==0


@pytest.mark.parametrize('part',['memory','file','boundary'])
def test_each_missing_evidence_class_remains_missing(part):
    facts=['READ_ONLY '+p for p in PATHS];initial={p:'a'*64 for p in PATHS};observations=[initial,initial]
    if part=='memory':facts=None
    if part=='file':observations=[{p:None for p in PATHS}]
    boundary=None if part=='boundary'else True
    point=readonly_checkpoint(PATHS,facts,initial,observations,changed_boundary_known=boundary,boundaries_complete=True)
    assert point['score'] is None and not point['collection_complete']


def test_wrong_scope_or_positive_instruction_cannot_match_read_only_marker():
    initial={p:'a'*64 for p in PATHS}
    assert readonly_checkpoint(PATHS,['READ_ONLY /other/types.py'],initial,[initial,initial],changed_boundary_known=True,boundaries_complete=True)['score']==0
    assert readonly_checkpoint(PATHS,['CAN_MODIFY '+p for p in PATHS],initial,[initial,initial],changed_boundary_known=True,boundaries_complete=True)['score']==0
    assert readonly_checkpoint(PATHS,['NOT READ_ONLY '+p for p in PATHS],initial,[initial,initial],changed_boundary_known=True,boundaries_complete=True)['score']==0
    assert readonly_checkpoint(PATHS,['READ_ONLY '+p+'.other'for p in PATHS],initial,[initial,initial],changed_boundary_known=True,boundaries_complete=True)['score']==0


@pytest.mark.parametrize('state_kind,expected',[('complete',100),('wrong',0),('missing',None)])
def test_readonly_actual_cas_before_change_and_common_preservation(tmp_path,state_kind,expected):
    import json
    import subprocess
    from pathlib import Path

    from memweave_eval.fixed35_business import grade_readonly
    module=Path(__file__).parents[1]/'src/memweave_eval/content_evidence.mjs'
    rows=[{'op_id':'g','op':'update_goal','goal':'repair'}]
    for i,p in enumerate(PATHS):
        rows.append({'op_id':str(i),'op':'append_fact','id':'F'+str(i+1),
                     'fact':('READ_ONLY 'if state_kind=='complete'else'ALLOW_MODIFY ')+p})
    source="""import {contentEvidence} from MODULE;
const s=contentEvidence(ROOT), initial={'app/types.py':'a'.repeat(64),'app/DESIGN.md':'a'.repeat(64),
'app/__init__.py':'a'.repeat(64),'app/events.py':'b'.repeat(64)};
s.event('workspace_checkpoint',{phase:'agent_start',workspace:{files:initial}});
const b={expected_task_id:'task'};
if(KIND!=='missing')b.expected_journal_ref=s.put(ROWS.map(JSON.stringify).join('\\n')+'\\n');
s.event('request_ready',{request_id:'r',payload_ref:s.put({messages:[]}),prepared_boundary:b,workspace:{files:initial}});
s.event('tool_call',{call_id:'w',tool:'write'});
s.event('workspace_checkpoint',{phase:'tool_end',call_id:'w',workspace:{files:{...initial,'app/events.py':'c'.repeat(64)}}});
s.event('workspace_checkpoint',{phase:'agent_end',workspace:{files:{...initial,'app/events.py':'c'.repeat(64)}}});
"""
    for key,value in {'MODULE':module.as_uri(),'ROOT':str(tmp_path/'agent/request-content'),
                      'KIND':state_kind,'ROWS':rows}.items():source=source.replace(key,json.dumps(value))
    subprocess.run(['node','--input-type=module','-e',source],check=True,capture_output=True,text=True)
    (tmp_path/'agent/pi.txt').write_text('\n'.join(json.dumps(v)for v in [{'type':'agent_start'},{'type':'tool_execution_start','toolCallId':'w'},{'type':'tool_execution_end','toolCallId':'w'},{'type':'agent_end'}])+'\n')
    result=grade_readonly(tmp_path,{'workspace_root':'/app','readonly_paths':PATHS,
        'mutable_files':['/app/app/events.py']},arm='pi-memweave')
    assert result['plugin_memory']['score']==expected
    assert result['common_constraint']['score']==100


@pytest.mark.parametrize('scenario,memory,common,complete,opportunity',[
    ('initial_only',None,None,False,'UNKNOWN_INCOMPLETE_EXECUTION'),
    ('no_change_complete',None,100,True,'NO_OBSERVED_SOURCE_CHANGE_COMPLETE_EPISODE'),
    ('missing_change_call',None,None,False,'OBSERVED_CHANGE_ACTION_BOUNDARY_MISSING'),
    ('changed_then_restored',0,0,True,'OBSERVED_SOURCE_CHANGE'),
    ('missing_end',None,None,False,'OBSERVED_SOURCE_CHANGE'),
    ('missing_post',None,None,False,'OBSERVED_CHANGE_ACTION_BOUNDARY_MISSING'),
])
def test_observation_boundaries_and_opportunity_are_independent(tmp_path,scenario,memory,common,complete,opportunity):
    import json
    import subprocess
    from pathlib import Path

    from memweave_eval.fixed35_business import grade_readonly
    root=tmp_path/'agent';root.mkdir()
    rows=[{'op_id':'g','op':'update_goal','goal':'repair'}]+[
        {'op_id':str(i),'op':'append_fact','id':f'F{i+1}','fact':'READ_ONLY '+p}for i,p in enumerate(PATHS)]
    module=Path(__file__).parents[1]/'src/memweave_eval/content_evidence.mjs'
    script="""import {contentEvidence}from MODULE;
const s=contentEvidence(ROOT), scenario=SCENARIO;
const initial={'app/types.py':'a'.repeat(64),'app/DESIGN.md':'a'.repeat(64),
'app/__init__.py':'a'.repeat(64),'app/events.py':'b'.repeat(64)};
const changed={...initial,'app/events.py':'c'.repeat(64)};
s.event('workspace_checkpoint',{phase:'agent_start',workspace:{files:initial}});
s.event('request_ready',{request_id:'r',payload_ref:s.put({messages:[]}),workspace:{files:initial},
prepared_boundary:{expected_task_id:'task',expected_journal_ref:s.put(ROWS.map(JSON.stringify).join('\\n')+'\\n')}});
if(!['initial_only','no_change_complete'].includes(scenario)){
 if(scenario!=='missing_change_call')s.event('tool_call',{call_id:'w',tool:'write'});
 if(scenario!=='missing_post')s.event('workspace_checkpoint',{phase:'tool_end',call_id:'w',workspace:{files:
 scenario==='changed_then_restored'?{...changed,'app/types.py':'d'.repeat(64)}:changed}});
 if(scenario==='changed_then_restored'){
  s.event('tool_call',{call_id:'restore',tool:'write'});
  s.event('workspace_checkpoint',{phase:'tool_end',call_id:'restore',workspace:{files:initial}});
 }
}
if(!['initial_only','missing_end'].includes(scenario))s.event('workspace_checkpoint',{phase:'agent_end',workspace:{files:
 ['no_change_complete','changed_then_restored'].includes(scenario)?initial:changed}});
"""
    for key,value in {'MODULE':module.as_uri(),'ROOT':str(root/'request-content'),'SCENARIO':scenario,'ROWS':rows}.items():script=script.replace(key,json.dumps(value))
    subprocess.run(['node','--input-type=module','-e',script],check=True,capture_output=True,text=True)
    raw=[{'type':'agent_start'}]
    if scenario not in {'initial_only','no_change_complete'}:
        for identity in ['w',*(['restore']if scenario=='changed_then_restored'else[])]:
            raw.extend([{'type':'tool_execution_start','toolCallId':identity},{'type':'tool_execution_end','toolCallId':identity}])
    if scenario not in {'initial_only','missing_end'}:raw.append({'type':'agent_end'})
    (root/'pi.txt').write_text('\n'.join(json.dumps(v)for v in raw)+'\n')
    result=grade_readonly(tmp_path,{'workspace_root':'/app','readonly_paths':PATHS,
        'mutable_files':['/app/app/events.py']},arm='pi-memweave')
    assert result['plugin_memory']['score']==memory
    assert result['common_constraint']['score']==common
    assert result['boundary_coverage']['complete']==complete
    assert result['opportunity_status']==opportunity
