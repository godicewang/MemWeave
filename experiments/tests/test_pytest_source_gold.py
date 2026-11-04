import json

import pytest


@pytest.fixture
def source_bundle(tmp_path):
    from memweave_eval.storage import file_digest
    source=tmp_path/'source';source.write_text('frozen upstream tests')
    ids=['tests.py::test_first[a]','tests.py::test_first[b]','tests.py::test_second']
    contract={'case_id':'TB-03','version':'unit-only','source_hashes':{str(source):file_digest(source)},
        'test_ids':ids,'groups':{'behavior':ids[:2],'provenance':ids[2:]},
        'common_groups':['behavior'],'dependency_group':'provenance','scope':'synthetic unit connection only'}
    trial=tmp_path/'trial';v=trial/'verifier';v.mkdir(parents=True)
    (trial/'result.json').write_text(json.dumps({'config':{'agent':{'name':'oracle'}},'verifier_result':{'rewards':{'reward':1}}}))
    (v/'reward.txt').write_text('1')
    (v/'test-stdout.txt').write_text('=== short test summary info ===\n'+
        '\n'.join('PASSED tests/'+i for i in ids)+'\n=== 3 passed in 1.0s ===\n')
    (v/'ctrf.json').write_text(json.dumps({'results':{'tests':[{'name':i.split('[')[0],'status':'passed'}for i in ids],
        'summary':{'tests':3,'passed':3,'failed':0,'skipped':0,'pending':0,'other':0}}}))
    return trial,contract


def grade(bundle):
    from memweave_eval.pytest_source_gold import grade_trial
    return grade_trial(*bundle,fixture_control=True)


def test_parameter_identity_uses_console_and_ctrf_multiplicity(source_bundle):
    r=grade(source_bundle)
    assert r['collection_complete']and r['fixture_only']
    assert r['source_counts']=={'passed':3,'failed':0,'unknown':0,'total':3}
    assert all(p['score']==100 for p in r['checkpoints'].values())
    from memweave_eval.pytest_source_gold import grade_trial
    with pytest.raises(ValueError,match='fixture-control'):grade_trial(*source_bundle)


def test_failure_is_source_assertion_failure_and_does_not_poison_other_point(source_bundle):
    t,_=source_bundle;p=t/'verifier/test-stdout.txt';p.write_text(p.read_text().replace('PASSED tests/tests.py::test_first[b]','FAILED tests/tests.py::test_first[b] - AssertionError').replace('3 passed','1 failed, 2 passed'))
    p=t/'verifier/ctrf.json';x=json.loads(p.read_text());x['results']['tests'][1]['status']='failed';x['results']['summary'].update(passed=2,failed=1);p.write_text(json.dumps(x))
    (t/'verifier/reward.txt').write_text('0');p=t/'result.json';x=json.loads(p.read_text());x['verifier_result']['rewards']['reward']=0;p.write_text(json.dumps(x))
    r=grade(source_bundle)
    assert r['collection_complete']and r['checkpoints']['behavior']['score']==0
    assert r['checkpoints']['provenance']['score']==100 and r['whole_protocol']['score']==0


@pytest.mark.parametrize('mode',['console_missing','console_duplicate','wrong_parameter','ctrf_missing',
    'ctrf_duplicate','status_conflict','summary_conflict','truncated','skipped'])
def test_collection_damage_is_not_a_valid_zero_or_success(source_bundle,mode):
    t,_=source_bundle;v=t/'verifier';p=v/'test-stdout.txt';text=p.read_text();cp=v/'ctrf.json';c=json.loads(cp.read_text())
    if mode=='console_missing':p.unlink()
    elif mode=='console_duplicate':p.write_text(text.replace('=== 3 passed','PASSED tests/tests.py::test_first[a]\n=== 3 passed'))
    elif mode=='wrong_parameter':p.write_text(text.replace('test_first[b]','test_first[c]'))
    elif mode=='ctrf_missing':c['results']['tests'].pop();cp.write_text(json.dumps(c))
    elif mode=='ctrf_duplicate':c['results']['tests'].append(c['results']['tests'][0]);cp.write_text(json.dumps(c))
    elif mode=='status_conflict':c['results']['tests'][0]['status']='failed';cp.write_text(json.dumps(c))
    elif mode=='summary_conflict':c['results']['summary']['passed']=1;cp.write_text(json.dumps(c))
    elif mode=='truncated':p.write_text(text.removesuffix('=== 3 passed in 1.0s ===\n'))
    else:
        p.write_text(text.replace('PASSED tests/tests.py::test_first[a]','SKIPPED tests/tests.py::test_first[a]'))
        c['results']['tests'][0]['status']='skipped';c['results']['summary'].update(passed=2,skipped=1);cp.write_text(json.dumps(c))
    r=grade(source_bundle)
    assert not r['collection_complete']
    assert r['whole_protocol']['score']is None or r['whole_protocol']['collection_complete']is False


def test_success_reward_cannot_overrule_failed_source_assertion(source_bundle):
    t,_=source_bundle;p=t/'verifier/test-stdout.txt';p.write_text(p.read_text().replace('PASSED tests/tests.py::test_first[b]','FAILED tests/tests.py::test_first[b]').replace('3 passed','1 failed, 2 passed'))
    p=t/'verifier/ctrf.json';c=json.loads(p.read_text());c['results']['tests'][1]['status']='failed';c['results']['summary'].update(passed=2,failed=1);p.write_text(json.dumps(c))
    r=grade(source_bundle)
    assert r['contradictory_reward']and not r['collection_complete']


def test_static_source_parametrization_never_executes_test_code(tmp_path):
    from memweave_eval.pytest_source_gold import test_identities
    p=tmp_path/'test_outputs.py';p.write_text('raise RuntimeError("never import")\n@pytest.mark.parametrize("case", VECTORS["encode"], ids=case_id)\ndef test_encode(case): pass\ndef test_plain():pass\n')
    assert test_identities(p,{'encode':[{'profile':'standard'},{'profile':'durable'}]})==[
        'test_outputs.py::test_encode[standard]','test_outputs.py::test_encode[durable]','test_outputs.py::test_plain']


def test_source_class_methods_keep_their_identity_without_importing(tmp_path):
    from memweave_eval.pytest_source_gold import test_identities
    p=tmp_path/'test_state.py';p.write_text('raise RuntimeError("must not import")\nclass TestCheckpointConsolidation:\n def test_exists(self):pass\n def test_shapes(self):pass\n')
    assert test_identities(p,{})==['test_state.py::TestCheckpointConsolidation::test_exists',
        'test_state.py::TestCheckpointConsolidation::test_shapes']


def test_error_is_only_controlled_when_an_explicit_output_absence_was_observed(source_bundle):
    t,c=source_bundle;c['setup_error_prerequisite']='tests.py::test_second'
    c['controlled_setup_error_ids']=['tests.py::test_first[a]','tests.py::test_first[b]']
    v=t/'verifier';p=v/'test-stdout.txt';p.write_text('=== short test summary info ===\n'+
        'ERROR tests/tests.py::test_first[a] - missing output\nERROR tests/tests.py::test_first[b] - missing output\n'+
        'FAILED tests/tests.py::test_second - output missing\n=== 1 failed, 2 errors in 1.0s ===\n')
    p=v/'ctrf.json';x=json.loads(p.read_text())
    for row in x['results']['tests']:row['status']='failed'
    x['results']['summary'].update(passed=0,failed=3);p.write_text(json.dumps(x))
    (v/'reward.txt').write_text('0');p=t/'result.json';x=json.loads(p.read_text());x['verifier_result']['rewards']['reward']=0;p.write_text(json.dumps(x))
    r=grade(source_bundle)
    assert r['collection_complete']and r['checkpoints']['behavior']['score']==0
    assert len(r['controlled_setup_errors'])==2 and r['source_counts']['failed']==1
    assert r['native_metrics']['passed']==0 and r['native_metrics']['total']==3
    assert all(r['observations'][i]is None for i in c['controlled_setup_error_ids'])
    p=v/'test-stdout.txt';p.write_text(p.read_text().replace('FAILED tests/tests.py::test_second','PASSED tests/tests.py::test_second'))
    p=v/'ctrf.json';x=json.loads(p.read_text());x['results']['tests'][2]['status']='passed';x['results']['summary'].update(passed=1,failed=2);p.write_text(json.dumps(x))
    r=grade(source_bundle)
    assert not r['collection_complete']and not r['controlled_setup_errors']


def test_existing_report_scores_selected_source_and_keeps_capture_failure(source_bundle,tmp_path):
    import csv

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    trial,contract=source_bundle;root=tmp_path/'report-input';root.mkdir()
    contract.update(adapter_kind='pytest-selected-source-v1',metric_matrix=[{'metric_id':m['id'],
        'design_status':'PLANNED'if m['id']in {'S3.original_reward','S3.partial_pass_rate','S.common.protected_constraints',
            'S.common.process_validation','S.common.dependency_constraints'}else'DESIGN_NA',
        'opportunity_ids':['synthetic-report-test'],'reason':'Unit fixture only, not actual source applicability'}for m in catalogue()['metrics']])
    cp=root/'contract.json';cp.write_text(json.dumps(contract))
    (root/'admission.json').write_text(json.dumps({'case_id':'TB-03','family':'tb4','benchmark':'Terminal-Bench 4.0',
        'contract_path':str(cp),'contract_sha256':file_digest(cp)}))
    collection={'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True}
    (root/'pair-result.json').write_text(json.dumps({'arms':[{'arm':a,'result_path':str(trial/'result.json'),
        'collection':collection,'exception':None,'verifier':{'rewards':{'reward':1}}}for a in ['pi-native','pi-memweave']]}))
    single_report(root,tmp_path/'report',fixture_control=True)
    r=json.loads((tmp_path/'report/results.json').read_text())
    assert r['fixture_scores_included']and r['collection_accepted']
    assert all(m['score']==100 for row in r['rows']for m in row['normalized_metrics']if m['status']=='scored')
    assert len(list(csv.DictReader((tmp_path/'report/derived-behavior.csv').open())))==6
    (trial/'verifier/test-stdout.txt').unlink()
    single_report(root,tmp_path/'missing-report',fixture_control=True)
    r=json.loads((tmp_path/'missing-report/results.json').read_text())
    assert not r['collection_accepted']
    assert all(m['collection_status']=='REPAIR_REQUIRED'for row in r['rows']for m in row['normalized_metrics']if m['status']!='DESIGN_NA')
    with pytest.raises(ValueError,match='fixture-control'):single_report(root,tmp_path/'not-a-model-score')
