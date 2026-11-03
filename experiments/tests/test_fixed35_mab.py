import json
import subprocess
from pathlib import Path

import pytest

from memweave_eval.fixed35_mab import (
    active_text,
    grade_action,
    grade_correction,
    grade_three_evictions,
)


def test_action_multiple_checks_all_required_and_evidence_absence_distinct():
    assert grade_action('B',['B'],{'value':'B'},action_observation_complete=True)['derived_action']['score']==100
    assert grade_action('B',['B'],{'value':'A'},action_observation_complete=True)['derived_action']['score']==0
    assert grade_action('B',['B'],None,action_observation_complete=False)['derived_action']['score'] is None
    assert grade_action('B',['B'],None,action_observation_complete=True)['derived_action']['score']==0


def test_correction_entity_scope_and_old_invalidation_and_order():
    c={'required_relations':[['Microsoft','Steve Jobs']], 'forbidden_relations':[['Microsoft','Satya Nadella']]}
    assert grade_correction(['Microsoft CEO Steve Jobs'],c,correct_action=True,snapshot_before_action=True)['score']==100
    for facts in (['Apple CEO Steve Jobs'],['Microsoft CEO Steve Jobs','Microsoft CEO Satya Nadella']):
        assert grade_correction(facts,c,correct_action=True,snapshot_before_action=True)['score']==0
    assert grade_correction(None,c,correct_action=True,snapshot_before_action=True)['score'] is None
    assert grade_correction(['Microsoft CEO Steve Jobs'],c,correct_action=True,snapshot_before_action=False)['score']==0


def test_three_real_distinct_evictions_middle_loss_cannot_be_repaired_at_end():
    points=[{'boundary_id':str(i),'original_source_absent':True,'current_facts_retained':True,
             'delivered_version_correct':True}for i in range(3)]
    assert grade_three_evictions(points,observation_complete=True)['score']==100
    points[1]['current_facts_retained']=False
    assert grade_three_evictions(points,observation_complete=True)['score']==0
    assert grade_three_evictions(points[:1],observation_complete=True)['score'] is None
    assert grade_three_evictions(None,observation_complete=False)['collection_complete'] is False


def test_archive_or_window_removal_is_not_active_memory():
    rows=[{'op_id':'g','op':'update_goal','goal':'x'},
          {'op_id':'a','op':'append_fact','id':'F1','fact':'old'},
          {'op_id':'b','op':'modify_fact','archive':['F1'],'append_fact':{'content':'new'}}]
    assert active_text(rows)==['new']


def test_known_unbound_state_is_missing_memory_not_missing_observation():
    from memweave_eval.fixed35_mab import delivered_memory
    assert delivered_memory(['当前未绑定 Task。'],{'expected_task_id':None})==([],True)
    assert delivered_memory([],{})==(None,None)
    assert delivered_memory([],{'expected_task_id':'task','expected_version_at_prepare':2})==([],False)
    text='# Symbolic State\ntask_id: other\nstate_version: 2\nF1 wrong\ne: [U1]'
    assert delivered_memory([text],{'expected_task_id':'task','expected_version_at_prepare':2})==([],False)


def test_multihop_current_chain_or_correct_derived_fact_both_accepted():
    from memweave_eval.fixed35_mab import literal_snapshot
    contract={'required_relation_sets':[
        [['Bagratuni','Taipei']],[['Bagratuni','Christianity'],['Christianity','Taipei']]],
        'forbidden_relations':[['Christianity','Jerusalem']]}
    assert all(literal_snapshot(['Bagratuni Dynasty religion Christianity','Christianity origin Taipei'],contract).values())
    assert all(literal_snapshot(['Bagratuni religion originated in Taipei'],contract).values())
    assert not literal_snapshot(['Christianity origin Taipei'],contract)['required_relations']
    assert not literal_snapshot(['Bagratuni religion Christianity','Christianity origin Jerusalem'],contract)['obsolete_relations_absent']
    with pytest.raises(ValueError,match='nonempty'):
        literal_snapshot([],{'required_relation_sets':[[]]})


def test_all_eight_source_components_freeze_action_boundary_without_changing_prompts(tmp_path):
    from memweave_eval.fixed35_mab import prepare_mab_components
    for number in range(1,9):
        identity=f'MAB-{number:02d}';task=tmp_path/'adapter/actor-tasks'/identity
        (task/'steps/ingest-0001').mkdir(parents=True);(task/'steps/query').mkdir()
        (task/'steps/ingest-0001/instruction.md').write_text('public original source')
        (task/'steps/query/instruction.md').write_text('public original query')
        (task/'task.toml').write_text('[[steps]]\nname="ingest-0001"\n[[steps]]\nname="query"\n')
        private=tmp_path/'adapter/evaluator-only'/identity;private.mkdir(parents=True)
        (private/'gold.json').write_text(json.dumps({'answers':['answer'],'selector':{'row':number,'context_sha256':'a'*64,'qa_id':'q'}}))
    result=prepare_mab_components(tmp_path/'adapter',tmp_path/'out')
    assert result['components']==8 and result['correction_components']==4 and result['paid_requests']==0
    c=json.loads((tmp_path/'out/MAB-03.json').read_text())
    assert c['query_stage_id']=='2'and c['action_observation']=='workspace-content-v2'
    assert c['model_visible_changes']==[]and c['task_config']['workspace']['content_files']==['answer.json']
    assert len(c['literal_memory']['required_relation_sets'])==2
    assert json.loads((tmp_path/'out/manifest.json').read_text())['not_formal_admission']
    with pytest.raises(FileExistsError):prepare_mab_components(tmp_path/'adapter',tmp_path/'out')


@pytest.mark.parametrize('state_value,expected',[('Steve Jobs',100),('Satya Nadella',0),(None,None)])
def test_real_content_format_to_action_and_current_memory_grade(tmp_path,state_value,expected):
    from memweave_eval.fixed35_mab import grade_mab_trial
    agent=tmp_path/'steps/query/agent';agent.mkdir(parents=True)
    artifact=agent/'fixed35-artifacts';artifact.mkdir()
    (agent/'pi.txt').write_text(json.dumps({'type':'message_end','message':{'role':'assistant',
        'content':[{'type':'text','text':'Steve Jobs'}]}})+'\n')
    (artifact/'answer-presence.json').write_text('{"exists":true}')
    (artifact/'answer.json').write_text('{"value":"Steve Jobs"}')
    source=tmp_path/'instruction.md';source.write_text('original public source')
    rows=[{'op_id':'g','op':'update_goal','goal':'question'}]
    if state_value:rows.append({'op_id':'a','op':'append_fact','id':'F1','fact':'Microsoft CEO '+state_value})
    module=Path(__file__).parents[1]/'src/memweave_eval/content_evidence.mjs'
    script="""
import {contentEvidence} from MODULE;
const s=contentEvidence(ROOT);const rows=ROWS;
const b={boundary_id:'b',expected_task_id:'task',expected_version_at_prepare:rows.length};
if(HAS_STATE)b.expected_journal_ref=s.put(rows.map(JSON.stringify).join('\\n')+'\\n');
s.event('request_ready',{stage_id:'1',request_id:'r',payload_ref:s.put({messages:[]}),prepared_boundary:b});
s.event('tool_call',{tool:'write',call_id:'w',record_ref:s.put({input:{path:'/app/answer.json',content:'{"value":"Steve Jobs"}'}})});
""".replace('MODULE',json.dumps(module.as_uri())).replace('ROOT',json.dumps(str(agent/'request-content'))).replace('ROWS',json.dumps(rows)).replace('HAS_STATE',json.dumps(state_value is not None))
    subprocess.run(['node','--input-type=module','-e',script],check=True,capture_output=True,text=True)
    contract={'answers':['Steve Jobs'],'source_instruction_path':str(source),'literal_memory':{
        'required_relations':[['Microsoft','Steve Jobs']], 'forbidden_relations':[['Microsoft','Satya Nadella']]}}
    result=grade_mab_trial(tmp_path,contract,arm='pi-memweave')
    assert result['native']['native_outcome']==100
    assert result['derived_action']['score']==100
    assert result['memory']['correction']['score']==expected
