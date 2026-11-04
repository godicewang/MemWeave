import json

import pytest


@pytest.fixture
def bundle():
    reports={};expected={}
    for n in range(1,4):
        stage='checkpoint_'+str(n)
        tests={stage+'-Core':{'passed':['test_source_a','test_source_b'],'failed':[],'skipped':[]}}
        if n>1:tests['checkpoint_1-Regression']={'passed':['test_old_a','test_old_b'],'failed':[],'skipped':[]}
        raw={'problem_name':'circuit_eval','checkpoint_name':stage,'test_collection_hash':'a'*64,'schema_version':1,
            'infrastructure_failure':False,'pytest_exit_code':0,'pytest_collected':2,
            'tests':tests,'pass_counts':{'Core':2,'Regression':2 if n>1 else 0},
            'total_counts':{'Core':2,'Regression':2 if n>1 else 0}}
        reports[stage]=raw
        expected[stage]={'groups':{g:sorted(v['passed'])for g,v in tests.items()},
            'test_collection_hash':'a'*64,'pytest_collected':2,'schema_version':1}
    return {'case_id':'SCB-01','problem':'circuit_eval','stages':expected,'source_hashes':{},
        'scope':'unit fixture only'},reports


@pytest.mark.parametrize('kind',['current','regression'])
@pytest.mark.parametrize('mode',['pass','fail','skip','missing'])
def test_source_stage_points_are_independent_and_use_all_parameters(bundle,kind,mode):
    from memweave_eval.slop_source_business import grade_reports
    c,reports=bundle;raw=reports['checkpoint_2'];key='checkpoint_2-Core'if kind=='current'else'checkpoint_1-Regression'
    if mode=='missing':raw['tests'][key]['passed'].pop()
    elif mode in {'fail','skip'}:
        identity=raw['tests'][key]['passed'].pop();raw['tests'][key]['failed'if mode=='fail'else'skipped'].append(identity)
        category=key.rsplit('-',1)[-1];raw['pass_counts'][category]-=1;raw['pytest_exit_code']=1 if mode=='fail'else 0
    r=grade_reports(reports,c,fixture_control=True);p=r['checkpoints']['checkpoint_2:'+kind]
    if mode=='missing':assert not r['collection_complete']and p['score']is None
    else:
        assert r['collection_complete']and p['score']==(0 if mode in {'fail','skip'}else 100)
        other='regression'if kind=='current'else'current'
        assert r['checkpoints']['checkpoint_2:'+other]['score']==100
        assert r['common_checkpoint']['score']==(50 if kind=='regression'and mode in {'fail','skip'}else 100)
        assert r['process_checkpoint']['score']==pytest.approx(200/3 if kind=='current'and mode in {'fail','skip'}else 100)


def test_known_failed_and_damaged_point_remains_zero_but_does_not_pass_collection(bundle):
    from memweave_eval.slop_source_business import grade_reports
    c,r=bundle;p=r['checkpoint_2'];p['tests']['checkpoint_1-Regression']={'passed':[],
        'failed':['test_old_a'],'skipped':[]};p['pass_counts']['Regression']=0;p['total_counts']['Regression']=1;p['pytest_exit_code']=1
    result=grade_reports(r,c,fixture_control=True)
    assert result['checkpoints']['checkpoint_2:regression']['score']==0
    assert result['common_checkpoint']['score']==50
    assert not result['common_checkpoint']['collection_complete']and not result['collection_complete']


@pytest.mark.parametrize('mode',['duplicate','wrong-id','count','hash','missing-stage','extra-stage','bad-json','nested-null','bad-status-list'])
def test_source_inventory_and_protocol_damage_require_repair(bundle,mode):
    from memweave_eval.slop_source_business import grade_reports
    c,r=bundle;p=r['checkpoint_2']
    if mode=='duplicate':p['tests']['checkpoint_2-Core']['passed'].append('test_source_a')
    elif mode=='wrong-id':p['tests']['checkpoint_2-Core']['passed'][0]='wrong'
    elif mode=='count':p['pass_counts']['Core']=1
    elif mode=='hash':p['test_collection_hash']='b'*64
    elif mode=='missing-stage':r.pop('checkpoint_2')
    elif mode=='extra-stage':r['checkpoint_4']=p
    elif mode=='nested-null':p['tests']['checkpoint_2-Core']=None
    elif mode=='bad-status-list':p['tests']['checkpoint_2-Core']['skipped']='wrong type'
    else:p['tests']=[]
    assert not grade_reports(r,c,fixture_control=True)['collection_complete']


def test_report_counts_are_not_silently_replaced_by_initial_collection_count(bundle):
    from memweave_eval.slop_source_business import grade_reports
    c,r=bundle;g=grade_reports(r,c,fixture_control=True)
    assert g['collection_complete']and g['fixture_only']
    assert g['stage_inventory']['checkpoint_2']['reported_occurrences']==4
    assert g['stage_inventory']['checkpoint_2']['initial_collected']==2
    assert g['untriggered_points']==['checkpoint_1:regression']


def test_existing_slop_report_does_not_overwrite_source_business_with_official_summary(bundle,tmp_path):
    import csv

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.fixed35_slop import sequential_outcome
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    c,reports=bundle;c.update(version='unit-source-v1',adapter_kind='slop-source-business-v1',
        metric_matrix=[{'metric_id':m['id'],'design_status':'PLANNED'if m['id']in {
            'S3.original_reward','S.common.protected_constraints','S.common.process_validation'}else'DESIGN_NA',
            'opportunity_ids':['unit-only'],'reason':'Unit fixture report only'}for m in catalogue()['metrics']])
    root=tmp_path/'input';root.mkdir();cp=root/'contract.json';cp.write_text(json.dumps(c));evidence={}
    for stage,raw in reports.items():
        p=root/(stage+'.json');p.write_text(json.dumps(raw));evidence[stage]={'report':str(p),'sha256':file_digest(p)}
    official=dict(sequential_outcome(reports,list(reports)),source_evidence=evidence,fixture_scores_included=True)
    op=root/'official.json';op.write_text(json.dumps({'case_id':'SCB-01','fixture_scores_included':True,
        'arms':{a:official for a in ['pi-native','pi-memweave']}}))
    (root/'admission.json').write_text(json.dumps({'case_id':'SCB-01','family':'slop','benchmark':'SlopCodeBench',
        'contract_path':str(cp),'contract_sha256':file_digest(cp)}))
    trial=root/'trial';trial.mkdir();(trial/'result.json').write_text('{}')
    (root/'pair-result.json').write_text(json.dumps({'arms':[{'arm':a,'result_path':str(trial/'result.json'),
        'collection':{'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True},
        'exception':None,'verifier':None}for a in ['pi-native','pi-memweave']]}))
    single_report(root,tmp_path/'report',op,fixture_control=True)
    r=json.loads((tmp_path/'report/results.json').read_text());assert r['collection_accepted']and r['fixture_scores_included']
    assert all(row['slop_business_component']['common_checkpoint']['score']==100 for row in r['rows'])
    for row in r['rows']:
        metric=next(m for m in row['normalized_metrics']if m['id']=='S.common.protected_constraints')
        assert metric['support_s']==metric['support_n']==2
    assert len(list(csv.DictReader((tmp_path/'report/derived-behavior.csv').open())))==10
    p=root/'checkpoint_2.json';p.write_text('{}')
    single_report(root,tmp_path/'missing-report',op,fixture_control=True)
    assert not json.loads((tmp_path/'missing-report/results.json').read_text())['collection_accepted']


@pytest.mark.parametrize('mode',['valid','manifest-changed','not-reference-fixture','dirty-source'])
def test_source_freeze_requires_pinned_source_and_both_control_manifest_hashes(bundle,tmp_path,monkeypatch,mode):
    from copy import deepcopy

    from memweave_eval.slop_source_business import freeze_contract
    from memweave_eval.storage import file_digest
    pin='a'*40;source=tmp_path/'source';task=source/'trajectory_api';tests=task/'tests';tests.mkdir(parents=True)
    (task/'config.yaml').write_text('name: trajectory_api')
    (tests/'test_source.py').write_text('raise RuntimeError("must never be imported")')
    records=[]
    for n in range(1,6):
        stage='checkpoint_'+str(n);raw=deepcopy(bundle[1]['checkpoint_1'if n==1 else'checkpoint_2'])
        raw.update(problem_name='trajectory_api',checkpoint_name=stage)
        raw['tests']={k.replace('checkpoint_2-',stage+'-')if k.startswith('checkpoint_2-')else k:v for k,v in raw['tests'].items()}
        p=tmp_path/(stage+'.json');p.write_text(json.dumps(raw));(task/(stage+'.md')).write_text(stage)
        records.append({'problem':'trajectory_api','stage':stage,'control':'reference','source':str(p),
            'source_sha256':file_digest(p),'fixture_only':mode!='not-reference-fixture','formal_score':None})
    upstream=tmp_path/'controls-source.json';upstream.write_text('[]')
    controls=tmp_path/'controls.json';controls.write_text(json.dumps({'records':records,
        'source_manifest':str(upstream),'source_manifest_sha256':file_digest(upstream)}))
    if mode=='manifest-changed':upstream.write_text('[1]')
    monkeypatch.setattr('memweave_eval.slop_source_business.subprocess.check_output',lambda args,**kwargs:
        pin+'\n'if'rev-parse'in args else' M tests.py'if mode=='dirty-source'else'')
    case={'pack_case_id':'SCB-03','upstream_case_id':'trajectory_api','source_revision':pin};out=tmp_path/'contract.json'
    if mode!='valid':
        with pytest.raises(ValueError):freeze_contract(case,source,controls,out)
        assert not out.exists()
    else:
        r=freeze_contract(case,source,controls,out)
        assert len(r['stages'])==5 and r['not_formal_admission']
        assert r['control_manifest_proof']['sha256']==file_digest(controls)
        assert r['source_hashes'][str(tests/'test_source.py')]==file_digest(tests/'test_source.py')
