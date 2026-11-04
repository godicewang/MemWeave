import json
from pathlib import Path

import pytest


@pytest.fixture
def bundle(tmp_path):
    from memweave_eval.storage import file_digest
    groups={name:[name]for name in ['security','orm','content','views','persistence','replay-load']}
    gates={name:{'file':'test_'+name.replace('-','_')+'.py','ids':['test_'+name.replace('-','_')+'.py::test_a[x]','test_'+name.replace('-','_')+'.py::test_a[y]']}
        for name in groups}
    source=tmp_path/'source';source.write_text('frozen source fixture')
    contract={'case_id':'LONG-05','source_hashes':{str(source):file_digest(source)},'gates':gates,
        'groups':groups,'allowed_skip_functions':[],'scope':'unit-only contract'}
    trial=tmp_path/'trial';v=trial/'verifier';v.mkdir(parents=True)
    for name,gate in gates.items():
        (v/(name+'.log')).write_text('\n'.join('../../tests/'+i+' PASSED [100%]'for i in gate['ids'])+
            '\n=== 2 passed in 1.0s ===\n')
        (v/(name+'_ctrf.json')).write_text(json.dumps({'results':{'tests':[
            {'name':gate['ids'][0].split('[')[0],'status':'passed','retries':1}],
            'summary':{'tests':1,'passed':1,'failed':0,'skipped':0,'pending':0,'other':0}}}))
    metrics={'health':True,'anti_cheat':True,'gates_passed':6,'gates_total':6,
        'tests_passed':6,'tests_total':6,'partial_score':1.0,'reward':1}
    (v/'metrics.json').write_text(json.dumps(metrics));(v/'reward.txt').write_text('1')
    (v/'test-stdout.txt').write_text('reward=1 partial_score=1.0000 tests=6/6 gates=6/6\n')
    (trial/'result.json').write_text(json.dumps({'config':{'agent':{'name':'oracle'}},
        'verifier_result':{'rewards':{'reward':1}}}))
    return trial,contract


def grade(bundle):
    from memweave_eval.ruby_source import grade_trial
    return grade_trial(*bundle,fixture_control=True)


@pytest.mark.parametrize('group',['security','orm','content','views','persistence','replay-load'])
@pytest.mark.parametrize('mode',['pass','fail','missing'])
def test_independent_source_groups(bundle,group,mode):
    trial,_contract=bundle;v=trial/'verifier';p=v/(group+'.log')
    if mode=='missing':p.unlink()
    elif mode=='fail':
        p.write_text(p.read_text().replace('PASSED','FAILED',1).replace('2 passed','1 failed, 1 passed'))
        p=v/(group+'_ctrf.json');x=json.loads(p.read_text());x['results']['tests'][0]['status']='failed'
        x['results']['summary'].update(passed=0,failed=1);p.write_text(json.dumps(x))
        p=v/'metrics.json';x=json.loads(p.read_text());x.update(tests_passed=5,gates_passed=5,partial_score=5/6,reward=0);p.write_text(json.dumps(x))
        (v/'reward.txt').write_text('0');p=trial/'result.json';x=json.loads(p.read_text());x['verifier_result']['rewards']['reward']=0;p.write_text(json.dumps(x))
        (v/'test-stdout.txt').write_text('reward=0 partial_score=0.8333 tests=5/6 gates=5/6\n')
    r=grade(bundle)
    if mode=='missing':assert not r['collection_complete']and r['checkpoints'][group]['score']is None
    else:
        assert r['collection_complete']and r['checkpoints'][group]['score']==(0 if mode=='fail'else 100)
        assert all(p['score']==100 for name,p in r['checkpoints'].items()if name!=group)
        assert r['expanded_source_counts']['total']==12
        assert r['original_ctrf_counts']['tests']==6


@pytest.mark.parametrize('mode',['duplicate','truncated','wrong-id','ctrf-retries','metrics','reward','unexpected-skip'])
def test_source_capture_corruption_cannot_pass(bundle,mode):
    t,_c=bundle;v=t/'verifier';p=v/'security.log';text=p.read_text()
    if mode=='duplicate':p.write_text(text.splitlines()[0]+'\n'+text)
    elif mode=='truncated':p.write_text('\n'.join(text.splitlines()[:-1]))
    elif mode=='wrong-id':p.write_text(text.replace('test_a[x]','test_wrong[x]'))
    elif mode=='ctrf-retries':
        p=v/'security_ctrf.json';x=json.loads(p.read_text());x['results']['tests'][0]['retries']=0;p.write_text(json.dumps(x))
    elif mode=='metrics':
        p=v/'metrics.json';x=json.loads(p.read_text());x['tests_total']=100;p.write_text(json.dumps(x))
    elif mode=='reward':(v/'reward.txt').write_text('0')
    else:p.write_text(text.replace('PASSED','SKIPPED',1).replace('2 passed','1 passed, 1 skipped'))
    assert not grade(bundle)['collection_complete']


def test_known_health_delivery_failure_is_not_fabricated_test_failures(bundle):
    t,_c=bundle;v=t/'verifier'
    for p in list(v.glob('*.log'))+list(v.glob('*_ctrf.json')):p.unlink()
    (v/'metrics.json').write_text(json.dumps({'tests_passed':0,'tests_total':0,'gates_passed':0,
        'gates_total':0,'partial_score':0,'reward':0}))
    (v/'reward.txt').write_text('0');p=t/'result.json';x=json.loads(p.read_text());x['verifier_result']['rewards']['reward']=0;p.write_text(json.dumps(x))
    (v/'test-stdout.txt').write_text('FAIL: rj-rust :8000 did not come up\n')
    r=grade(bundle)
    assert r['collection_complete']and all(p['score']==0 for p in r['checkpoints'].values())
    assert r['expanded_source_counts']['failed']==0 and r['unexecuted_source_cases']==12
    (v/'test-stdout.txt').unlink()
    assert not grade(bundle)['collection_complete']


def test_source_mutation_and_control_without_opt_in_are_rejected(bundle):
    from memweave_eval.ruby_source import grade_trial
    with pytest.raises(ValueError,match='fixture-control'):grade_trial(*bundle)
    Path(next(iter(bundle[1]['source_hashes']))).write_text('changed')
    with pytest.raises(ValueError,match='source changed'):grade(bundle)


def test_custom_resource_control_is_always_fixture_and_needs_opt_in(bundle):
    from memweave_eval.ruby_source import grade_trial
    p=bundle[0]/'result.json';x=json.loads(p.read_text());x['config']['agent']={'name':None,
        'import_path':'memweave_eval.resource_control:ResourceOracle'};p.write_text(json.dumps(x))
    with pytest.raises(ValueError,match='fixture-control'):grade_trial(*bundle)
    assert grade(bundle)['fixture_only']


def test_documented_markdown_skip_is_not_a_passed_expanded_assertion(bundle):
    t,c=bundle;v=t/'verifier';ids=['test_markdown.py::test_a[x]','test_markdown.py::test_a[y]']
    c['gates']['markdown']={'file':'test_markdown.py','ids':ids};c['allowed_skip_functions']=['test_markdown.py::test_a']
    (v/'markdown.log').write_text('../../tests/'+ids[0]+' PASSED [50%]\n../../tests/'+ids[1]+' SKIPPED [100%]\n=== 1 passed, 1 skipped in 1.0s ===\n')
    (v/'markdown_ctrf.json').write_text(json.dumps({'results':{'tests':[{'name':'test_markdown.py::test_a','status':'skipped','retries':1}],
        'summary':{'tests':1,'passed':0,'failed':0,'skipped':1,'pending':0,'other':0}}}))
    p=v/'metrics.json';x=json.loads(p.read_text());x.update(tests_total=7,partial_score=6/7,gates_total=7,gates_passed=7);p.write_text(json.dumps(x))
    (v/'test-stdout.txt').write_text('reward=1 partial_score=0.8571 tests=6/7 gates=7/7\n')
    r=grade(bundle)
    assert r['collection_complete']and r['expanded_source_counts']['skipped']==1
    assert r['expanded_source_counts']['passed']==13 and r['original_ctrf_counts']['passed']==6
    assert all(p['score']==100 for p in r['checkpoints'].values())


@pytest.mark.parametrize('bad',[{},[],{'results':{'tests':None,'summary':{}}},
    {'results':{'tests':[{}],'summary':{'tests':None}}}])
def test_malformed_or_missing_ctrf_fields_require_repair(bundle,bad):
    p=bundle[0]/'verifier/security_ctrf.json';p.write_text(json.dumps(bad))
    assert not grade(bundle)['collection_complete']


def test_existing_report_keeps_original_partial_and_expanded_source_counts(bundle,tmp_path):
    import csv

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    trial,c=bundle;c.update(version='unit-ruby-v1',adapter_kind='ruby-source-v1',metric_matrix=[
        {'metric_id':m['id'],'design_status':'PLANNED'if m['id']in {'S3.original_reward','S3.partial_pass_rate',
            'S.common.protected_constraints','S.common.process_validation'}else'DESIGN_NA',
         'opportunity_ids':['unit-only'],'reason':'Unit report test only'}for m in catalogue()['metrics']])
    root=tmp_path/'report-input';root.mkdir();cp=root/'contract.json';cp.write_text(json.dumps(c))
    (root/'admission.json').write_text(json.dumps({'case_id':'LONG-05','family':'marathon','benchmark':'SWE-Marathon',
        'contract_path':str(cp),'contract_sha256':file_digest(cp)}))
    (root/'pair-result.json').write_text(json.dumps({'arms':[{'arm':a,'result_path':str(trial/'result.json'),
        'collection':{'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True},
        'exception':None,'verifier':{'rewards':{'reward':1}}}for a in ['pi-native','pi-memweave']]}))
    single_report(root,tmp_path/'report',fixture_control=True)
    r=json.loads((tmp_path/'report/results.json').read_text())
    assert r['fixture_scores_included']and r['collection_accepted']
    counter_rows=list(csv.DictReader((tmp_path/'report/ruby-source-counts.csv').open()))
    assert len(counter_rows)==2 and all(row['observed_expanded_total']=='12'and row['original_ctrf_total']=='6'for row in counter_rows)
    assert '原始折叠计数与展开参数样本'in(tmp_path/'report/report.md').read_text()
    for row in r['rows']:
        assert row['ruby_component']['expanded_source_counts']['total']==12
        assert row['behavior_metrics']['native_metrics']['total']==6
        assert all(m['score']==100 for m in row['normalized_metrics']if m['status']=='scored')
    (trial/'verifier/security.log').unlink()
    single_report(root,tmp_path/'missing-report',fixture_control=True)
    assert not json.loads((tmp_path/'missing-report/results.json').read_text())['collection_accepted']
