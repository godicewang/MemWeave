import json
from pathlib import Path

import pytest

from memweave_eval.wal_gold import checkpoint_rows, grade_trial, source_tests


@pytest.fixture
def bundle(tmp_path):
    source=tmp_path/'source.txt';source.write_text('fixed source')
    from memweave_eval.storage import file_digest
    ids=['source.py::Suite::'+name for name in ['prefix','concurrent','detached']]
    contract={'source_hashes':{str(source):file_digest(source)},'test_ids':ids,'required_runs':10,
        'performance_runs':5,'structural_gates':['imports','symbols'],
        'groups':dict(zip(['durable-prefix','concurrent-prefix','deep-detachment'],[[x]for x in ids],strict=True)),
        'scope':'Synthetic oracle unit-test only; not an upstream task'}
    trial=tmp_path/'trial';v=trial/'verifier';v.mkdir(parents=True)
    text='\n'.join(['  [structural] imports: OK','  [structural] symbols: OK','structural gate: all gates passed',
        *[f'  [perf] run {i}/5: elapsed=0.1000s peak_mem=123.4 KiB'for i in range(1,6)],
        'performance gate: passed','CTRF verification: 97/97 passed -- OK','all gates passed'])
    (v/'test-stdout.txt').write_text(text)
    (v/'reward.txt').write_text('1')
    (trial/'result.json').write_text(json.dumps({'config':{'agent':{'name':'oracle'}},
        'verifier_result':{'rewards':{'reward':1}}}))
    for number in range(1,11):
        (v/f'ctrf_{number}.json').write_text(json.dumps({'results':{'tests':[{'name':x,'status':'passed'}for x in ids]}}))
    return trial,contract


def grade(bundle):
    return grade_trial(*bundle,fixture_control=True)


def test_all_source_points_and_supplement_rows_are_independently_and_scored(bundle):
    result=grade(bundle)
    assert result['collection_complete']and result['fixture_only']
    assert len(result['checkpoints'])==6 and all(p['score']==100 for p in result['checkpoints'].values())
    assert result['common_checkpoint']['score']==100
    assert result['first_run_native_metrics']['passed']==3
    assert all(r['score']==100 and r['weights']['plugin_memory']==0 for r in checkpoint_rows(result))
    with pytest.raises(ValueError,match='fixture-control'):grade_trial(*bundle)


@pytest.mark.parametrize('point,index',[('durable-prefix',0),('concurrent-prefix',1),('deep-detachment',2)])
def test_each_business_point_has_its_own_failure_and_missing_case(bundle,point,index):
    trial,contract=bundle;path=trial/'verifier/ctrf_1.json';value=json.loads(path.read_text())
    value['results']['tests'][index]['status']='failed';path.write_text(json.dumps(value))
    result=grade(bundle)
    assert result['checkpoints'][point]['score']==0
    assert all(result['checkpoints'][n]['score']==100 for n in contract['groups']if n!=point)
    value['results']['tests'][index]['status']='skipped';path.write_text(json.dumps(value))
    result=grade(bundle)
    assert result['checkpoints'][point]['score']is None and not result['collection_complete']


@pytest.mark.parametrize('point,old,new',[
    ('structural','imports: OK','imports: FAIL: forbidden import'),
    ('performance','performance gate: passed','perf gate failures:')])
def test_gate_failure_does_not_invent_missing_business_results(bundle,point,old,new):
    trial,_=bundle;path=trial/'verifier/test-stdout.txt';text=path.read_text();path.write_text(text.replace(old,new))
    assert grade(bundle)['checkpoints'][point]['score']==0
    assert grade(bundle)['contradictory_source_protocol']and not grade(bundle)['collection_complete']
    path.write_text(text.replace(old,''))
    assert grade(bundle)['checkpoints'][point]['score']is None
    assert not grade(bundle)['collection_complete']


def test_missing_a_performance_observation_is_capture_missing_not_known_slow(bundle):
    trial,_=bundle;p=trial/'verifier/test-stdout.txt'
    p.write_text('\n'.join(line for line in p.read_text().splitlines()if'run 3/5'not in line))
    r=grade(bundle)
    assert r['checkpoints']['performance']['score']is None and not r['collection_complete']


@pytest.mark.parametrize('mode',['missing','duplicate','wrong_id','skipped','invalid_json'])
def test_exact_run_identity_and_observation_cannot_be_faked(bundle,mode):
    trial,_=bundle;path=trial/'verifier/ctrf_5.json';x=json.loads(path.read_text())
    if mode=='missing':path.unlink()
    elif mode=='invalid_json':path.write_text('{')
    else:
        if mode=='duplicate':x['results']['tests'].append(x['results']['tests'][0])
        elif mode=='wrong_id':x['results']['tests'][0]['name']='different.py::unrelated'
        else:x['results']['tests'][0]['status']='skipped'
        path.write_text(json.dumps(x))
    r=grade(bundle)
    assert r['checkpoints']['ten-run-validation']['score']is None and not r['collection_complete']


def test_intermediate_failure_is_not_erased_by_final_success(bundle):
    trial,_=bundle;p=trial/'verifier/ctrf_5.json';x=json.loads(p.read_text());x['results']['tests'][0]['status']='failed';p.write_text(json.dumps(x))
    assert grade(bundle)['checkpoints']['ten-run-validation']['score']==0


def test_observed_source_early_exit_keeps_unexecuted_tests_separate(bundle):
    trial,_=bundle;v=trial/'verifier';x=json.loads((v/'ctrf_1.json').read_text());x['results']['tests'][1]['status']='failed'
    (v/'ctrf_1.json').write_text(json.dumps(x))
    for i in range(2,11):(v/f'ctrf_{i}.json').unlink()
    p=v/'test-stdout.txt';p.write_text(p.read_text().removesuffix('all gates passed')+'\ndeterminism run 1 failed (rc=1)\nverifier failed (rc=1)\n')
    (v/'reward.txt').write_text('0');r=json.loads((trial/'result.json').read_text());r['verifier_result']['rewards']['reward']=0;(trial/'result.json').write_text(json.dumps(r))
    result=grade(bundle)
    assert result['source_early_exit']and result['collection_complete']
    assert result['checkpoints']['ten-run-validation']['score']==0
    assert all(r['collection_status']=='SOURCE_EARLY_EXIT'and r['values']is None for r in result['runs'][1:])
    (v/'ctrf_10.json').write_text('{')
    result=grade(bundle)
    assert result['contradictory_suffix']and result['checkpoints']['ten-run-validation']['score']==0
    assert not result['collection_complete'],'contradictory post-abort artifacts must block acceptance'


def test_log_tail_and_reward_cross_check_are_independent(bundle):
    trial,_=bundle;v=trial/'verifier';p=v/'test-stdout.txt';p.write_text(p.read_text().removesuffix('all gates passed'))
    assert not grade(bundle)['collection_complete']
    assert grade(bundle)['checkpoints']['ten-run-validation']['score']is None
    (v/'reward.txt').write_text('0')
    assert grade(bundle)['original_reward']is None


def test_source_tests_ast_includes_state_machine_alias_without_importing(tmp_path):
    (tmp_path/'test_outputs.py').write_text('raise RuntimeError("must never execute")\nclass TestSuite01:\n def test_a(self): pass\n')
    (tmp_path/'_hidden_outputs.py').write_text('TestSuite08 = Machine.TestCase\n')
    assert source_tests(tmp_path)==['_hidden_outputs.py::TestSuite08::runTest','test_outputs.py::TestSuite01::test_a']


def test_frozen_source_content_change_rejected(bundle):
    _,contract=bundle;Path(next(iter(contract['source_hashes']))).write_text('changed')
    with pytest.raises(ValueError,match='source changed'):grade(bundle)


def test_existing_report_registers_common_gold_and_keeps_missing_collection(bundle,tmp_path):
    import csv

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    trial,contract=bundle;root=tmp_path/'report-input';root.mkdir()
    contract.update(adapter_kind='wal-source-v1',version='synthetic-wal-report-test',
        metric_matrix=[{'metric_id':m['id'],'design_status':'PLANNED'if m['id']in {
            'S3.original_reward','S3.partial_pass_rate','S.common.protected_constraints',
            'S.common.process_validation','S.common.dependency_constraints'}else'DESIGN_NA',
            'opportunity_ids':['synthetic-unit-connection'],
            'reason':'Unit-test-only scope, not a real case applicability decision'}for m in catalogue()['metrics']])
    cp=root/'contract.json';cp.write_text(json.dumps(contract))
    (root/'admission.json').write_text(json.dumps({'case_id':'TB-05','family':'tb4','benchmark':'Terminal-Bench 4.0',
        'contract_path':str(cp),'contract_sha256':file_digest(cp)}))
    collection={'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True}
    (root/'pair-result.json').write_text(json.dumps({'arms':[{'arm':arm,'result_path':str(trial/'result.json'),
        'collection':collection,'exception':None,'verifier':{'rewards':{'reward':1}}}for arm in ['pi-native','pi-memweave']]}))
    single_report(root,tmp_path/'report',fixture_control=True)
    report=json.loads((tmp_path/'report/results.json').read_text())
    assert report['fixture_scores_included']and report['collection_accepted']
    for row in report['rows']:
        assert row['wal_component']['fixture_only']and len(row['derived_behavior_checkpoints'])==6
        assert all(m['score']==100 for m in row['normalized_metrics']if m['status']=='scored')
    assert len(list(csv.DictReader((tmp_path/'report/derived-behavior.csv').open())))==12
    original_fifth=(trial/'verifier/ctrf_5.json').read_text()
    (trial/'verifier/ctrf_5.json').unlink()
    single_report(root,tmp_path/'missing',fixture_control=True)
    report=json.loads((tmp_path/'missing/results.json').read_text())
    assert not report['collection_accepted']
    assert all(next(m for m in row['normalized_metrics']if m['id']=='S.common.process_validation')['collection_status']=='REPAIR_REQUIRED'
        for row in report['rows'])
    (trial/'verifier/ctrf_5.json').write_text(original_fifth)
    log=trial/'verifier/test-stdout.txt';log.write_text(log.read_text().replace('imports: OK','imports: FAIL: forbidden import'))
    single_report(root,tmp_path/'contradiction',fixture_control=True)
    report=json.loads((tmp_path/'contradiction/results.json').read_text())
    assert not report['collection_accepted']
    assert all(m['collection_status']=='REPAIR_REQUIRED'for row in report['rows']for m in row['normalized_metrics']if m['status']=='scored')
    with pytest.raises(ValueError,match='fixture-control'):single_report(root,tmp_path/'no-fixture')
