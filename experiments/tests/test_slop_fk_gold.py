import json
from copy import deepcopy

import pytest

from memweave_eval.slop_fk_gold import (
    REQUIRED_TESTS,
    dependency_boundary,
    fk_checkpoint,
    journal_entries,
    source_test_checkpoint,
)


def card(value,lo=1,hi=None):
    return json.dumps({'r':'fk','v':value,'lo':lo,'hi':hi},separators=(',',':'))


def journal():
    return [{'op':'update_goal','op_id':'g','goal':'Migration tool'},
        {'op':'append_fact','op_id':'a','id':'F1','fact':card('OFF'),'evidence':{'U1':'Source'}}]


def test_initial_record_has_independent_scope_value_and_timing_assertions():
    point=fk_checkpoint(journal_entries(journal()),2,'OFF',before_dependency=True,boundaries_complete=True)
    assert point['score']==100 and len(point['assertions'])==4
    assert fk_checkpoint([],2,'OFF',before_dependency=True,boundaries_complete=True)['score']==0
    assert fk_checkpoint(None,2,'OFF',before_dependency=True,boundaries_complete=True)['score']is None
    assert fk_checkpoint(journal_entries(journal()),2,'OFF',before_dependency=None,boundaries_complete=True)['score']is None
    late=fk_checkpoint(journal_entries(journal()),2,'OFF',before_dependency=False,boundaries_complete=True)
    assert late['score']==0 and late['collection_complete']


def test_counterevidence_requires_old_effective_card_invalidated_not_just_new_card_added():
    rows=journal()+[{'op':'append_fact','op_id':'b','id':'F2','fact':card('ON',3),'evidence':{'U3':'Source'}}]
    point=fk_checkpoint(journal_entries(rows),3,'ON',before_dependency=True,boundaries_complete=True)
    assert point['assertions']['correct_visible_current_card']['value']is True
    assert point['assertions']['no_unarchived_incompatible_current_card']['value']is False
    assert point['score']==0
    rows=journal()+[{'op':'modify_fact','op_id':'b','archive':['F1'],
        'append_fact':{'content':card('ON',3),'evidence':{'U3':'Source'}}}]
    assert fk_checkpoint(journal_entries(rows),3,'ON',before_dependency=True,boundaries_complete=True)['score']==100


def test_window_eviction_does_not_invalidate_an_outdated_unarchived_rule():
    rows=journal()+[{'op':'slide_window','op_id':'s','batch_id':'b','evicted_range':{'from':2,'to':2},'retained_ids':[]},
        {'op':'append_fact','op_id':'b','id':'F2','fact':card('ON',3),'evidence':{'U3':'Source'}}]
    entries=journal_entries(rows)
    assert entries[0]['visible']is False and entries[0]['archived']is False
    assert fk_checkpoint(entries,3,'ON',before_dependency=True,boundaries_complete=True)['score']==0
    assert fk_checkpoint(entries[:1],2,'OFF',before_dependency=True,boundaries_complete=True)['score']==0


def test_scoped_history_is_legal_and_decision_can_be_archived_with_modify_fact():
    rows=[{'op':'update_goal','op_id':'g','goal':'Migration tool'},
        {'op':'append_decision','op_id':'a','id':'D1','decision':card('OFF'),'evidence':{'U1':'Source'}},
        {'op':'modify_fact','op_id':'b','archive':['D1'],
            'append_fact':{'content':card('OFF',1,2),'evidence':{'U1':'Source'}}},
        {'op':'append_fact','op_id':'c','id':'F2','fact':card('ON',3),'evidence':{'U3':'Source'}}]
    assert fk_checkpoint(journal_entries(rows),3,'ON',before_dependency=True,boundaries_complete=True)['score']==100


@pytest.mark.parametrize('value',[{'r':'fk','v':'ON','lo':True,'hi':None},
    {'r':'fk','v':'ON','lo':3,'hi':2},{'r':'fk','v':'ON','lo':3},
    {'r':'fk','v':'ON','lo':3,'hi':None,'extra':1},
    {'r':'fk','v':[],'lo':3,'hi':None}])
def test_malformed_target_card_is_known_failure_not_free_text_success(value):
    entries=[{'text':json.dumps(value),'visible':True,'archived':False}]
    assert fk_checkpoint(entries,3,'ON',before_dependency=True,boundaries_complete=True)['score']==0


def test_duplicate_keys_are_not_silently_accepted_and_unrelated_text_is_not_a_target_card():
    entries=[{'text':'{"r":"fk","v":"OFF","v":"ON","lo":3,"hi":null}','visible':True,'archived':False}]
    assert fk_checkpoint(entries,3,'ON',before_dependency=True,boundaries_complete=True)['score']==0
    entries.append({'text':card('ON',3),'visible':True,'archived':False})
    assert fk_checkpoint(entries,3,'ON',before_dependency=True,boundaries_complete=True)['score']==0
    entries=[{'text':card('ON',3),'visible':True,'archived':False},
        {'text':'Unrelated project uses foreign keys OFF','visible':True,'archived':False}]
    assert fk_checkpoint(entries,3,'ON',before_dependency=True,boundaries_complete=True)['score']==100


@pytest.mark.parametrize('change',['duplicate','bad_id','unknown_archive','no_goal'])
def test_corrupt_journal_is_rejected_not_converted_to_empty_memory(change):
    rows=journal()
    if change=='duplicate':rows.append(rows[-1])
    if change=='bad_id':rows[-1]['id']='F2'
    if change=='unknown_archive':rows.append({'op':'modify_fact','op_id':'b','archive':['F9'],'append_fact':{'content':card('ON',3)}})
    if change=='no_goal':rows.pop(0)
    with pytest.raises(ValueError):journal_entries(rows)


def test_source_test_checkpoint_requires_every_specific_independent_test_and_infrastructure():
    tests={}
    for group,name in REQUIRED_TESTS:
        tests.setdefault(group,{'passed':[],'failed':[],'skipped':[]})['passed'].append(name)
    report={'problem_name':'database_migration','checkpoint_name':'checkpoint_3',
        'infrastructure_failure':False,'pytest_exit_code':0,'pytest_collected':87,'tests':tests}
    assert source_test_checkpoint(report)['score']==100
    for group,name in REQUIRED_TESTS:
        bad=deepcopy(report);bad['tests'][group]['passed'].remove(name);bad['tests'][group]['failed'].append(name)
        assert source_test_checkpoint(bad)['score']==0
        missing=deepcopy(report);missing['tests'][group]['passed'].remove(name)
        point=source_test_checkpoint(missing)
        assert point['score']is None and not point['collection_complete']
    bad=deepcopy(report);bad['infrastructure_failure']=True
    assert source_test_checkpoint(bad)['score']is None
    for data in [None,[],{},'unknown']:
        bad=deepcopy(report);bad['tests']=data
        assert source_test_checkpoint(bad)['score']is None
    duplicate=deepcopy(report);group,name=REQUIRED_TESTS[0];duplicate['tests'][group]['passed'].append(name)
    assert source_test_checkpoint(duplicate)['score']is None


def frame(phase,digest,call=None):
    return {'event':'workspace_checkpoint','stage_id':'3','phase':phase,'producer_id':'p','call_id':call,
        'workspace':{'tree_projections':{'mutable':{'status':'complete','projection_sha256':digest}}}}


def test_mutation_deadline_is_first_observed_change_not_final_repaired_files():
    events=[frame('agent_start','a'*64),{'event':'tool_call','stage_id':'3','producer_id':'p','call_id':'edit'},
        frame('tool_end','b'*64,'edit'),{'event':'tool_call','stage_id':'3','producer_id':'p','call_id':'undo'},
        frame('tool_end','a'*64,'undo'),frame('agent_end','a'*64)]
    cutoff,status=dependency_boundary(events,'3')
    assert cutoff==1 and status=='FIRST_OBSERVED_PERSISTENT_SOURCE_CHANGE'
    missing=deepcopy(events);missing.pop(1)
    assert dependency_boundary(missing,'3')[0]is None
    assert dependency_boundary(events[:1],'3')[0]is None
    assert dependency_boundary([events[0],events[-1]],'3')==(1,'COMPLETE_STAGE_END_WITHOUT_OBSERVED_SOURCE_CHANGE')
    overlap=deepcopy(events);overlap.insert(1,{'event':'tool_call','stage_id':'3','producer_id':'p','call_id':'overlap'})
    assert dependency_boundary(overlap,'3')==(None,'AMBIGUOUS_OVERLAPPING_TOOL_BOUNDARY')


def test_state_evidence_after_dependency_does_not_retroactively_fix_timing(monkeypatch):
    from memweave_eval.slop_fk_gold import _state_at
    old=journal();new=old+[{'op':'modify_fact','op_id':'b','archive':['F1'],
        'append_fact':{'content':card('ON',3),'evidence':{'U3':'Source'}}}]
    monkeypatch.setattr('memweave_eval.slop_fk_gold.read_object',lambda store,ref:'\n'.join(json.dumps(r)for r in (old if ref=='old'else new)).encode())
    events=[{'event':'state_after_tool','producer_id':'p','sequence':0,'state':{'task_id':'t','journal_ref':'old'}},
        {'event':'tool_call','producer_id':'p','sequence':1},
        {'event':'state_after_tool','producer_id':'p','sequence':2,'state':{'task_id':'t','journal_ref':'new'}}]
    locations={('p',0):'unused',('p',2):'unused'}
    earlier=_state_at(events,locations,1)
    assert fk_checkpoint(earlier,3,'ON',before_dependency=True,boundaries_complete=True)['score']==0
    final=_state_at(events,locations,3)
    assert fk_checkpoint(final,3,'ON',before_dependency=True,boundaries_complete=True)['score']==100
    assert _state_at(events[1:2],{},1)is None


def test_report_registry_keeps_source_components_separate_from_original_strict_reward(tmp_path,monkeypatch):
    import csv

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    contract={'version':'fixed35-slop-fk-20261103-v1','adapter_kind':'slop-fk-source-v1',
        'metric_matrix':[{'metric_id':m['id'],'design_status':'PLANNED'if m['id']in {'S3.original_reward','S.common.protected_constraints'}else'DESIGN_NA',
            'opportunity_ids':['unit-only-source-component'],'reason':'Unit scope, not actual applicability'}for m in catalogue()['metrics']]}
    path=tmp_path/'contract.json';path.write_text(json.dumps(contract))
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'SCB-02','family':'slop','benchmark':'SlopCodeBench',
        'contract_path':str(path),'contract_sha256':file_digest(path)}))
    collection={'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True}
    (tmp_path/'pair-result.json').write_text(json.dumps({'arms':[{'arm':arm,'result_path':str(tmp_path/arm/'result.json'),
        'collection':collection,'exception':None,'verifier':None}for arm in ['pi-native','pi-memweave']]}))
    official=tmp_path/'official.json';official.write_text(json.dumps({'case_id':'SCB-02','fixture_scores_included':True,
        'arms':{arm:{'score':100,'original_all_reported_tests_AND':0,'collection_complete':True}for arm in ['pi-native','pi-memweave']}}))
    missing=fk_checkpoint(None,3,'ON',before_dependency=None,boundaries_complete=False)
    business=source_test_checkpoint({'problem_name':'database_migration','checkpoint_name':'checkpoint_3',
        'infrastructure_failure':False,'pytest_exit_code':0,'pytest_collected':5,
        'tests':{group:{'passed':[n for g,n in REQUIRED_TESTS if g==group],'failed':[],'skipped':[]}for group,_ in REQUIRED_TESTS}})
    component={'fixture_only':True,'scope':'unit-only','checkpoints':{'source-business-3':business,'record-3':missing},'collection_complete':False}
    monkeypatch.setattr('memweave_eval.slop_fk_gold.grade_trial',lambda *args,**kw:component)
    output=tmp_path/'reports';single_report(tmp_path,output,official,fixture_control=True)
    record=json.loads((output/'results.json').read_text())
    assert record['collection_accepted']is False and record['fixture_scores_included']is True
    assert all(r['native_reward']==0 for r in record['rows'])
    derived=list(csv.DictReader((output/'derived-behavior.csv').open()))
    assert len(derived)==4 and all(json.loads(r['weights'])=={'common_product':0,'plugin_memory':0}for r in derived)
    with pytest.raises(ValueError,match='actual Slop'):single_report(tmp_path,tmp_path/'rejected',official)


def test_native_design_na_row_does_not_require_nonexistent_assertions():
    from memweave_eval.slop_fk_gold import checkpoint_rows
    rows=checkpoint_rows({'scope':'unit','checkpoints':{'record-2':{
        'score':None,'status':'DESIGN_NA','collection_complete':True}}})
    assert rows[0]['score']is None and rows[0]['support_n']==rows[0]['support_u']==0
    assert rows[0]['raw_formula'].startswith('Design NA')
