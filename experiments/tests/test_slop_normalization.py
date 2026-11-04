from copy import deepcopy

import pytest

from memweave_eval.fixed35_slop import normalized_source_metrics
from memweave_eval.normalized_scores import normalize_trial_scores


def outcome():
    return {'problem':'database_migration','checkpoints':{
        'checkpoint_1':{'status':'SCORED','original_reported_passed':1,'original_reported_total':1,'original_all_reported_tests_score':100},
        'checkpoint_2':{'status':'SCORED','original_reported_passed':9,'original_reported_total':10,'original_all_reported_tests_score':0},
        **{f'checkpoint_{i}':{'status':'SCORED','original_reported_passed':1,'original_reported_total':1,'original_all_reported_tests_score':100}for i in range(3,6)}}}


def test_original_stage_macro_is_not_flat_test_weighting_or_derived_rate():
    x=outcome();x['checkpoints']['checkpoint_2'].update(score=100,passed=9,total=9)
    r=normalized_source_metrics(x)
    assert r['partial']['value']==pytest.approx(.98)
    assert r['partial']['denominator']==5 and r['partial']['numerator']==4.9
    assert r['checkpoint_protocol']['value']==.8
    assert r['partial']['stage_evidence']['checkpoint_2']=={'passed':9,'total':10,'kind':'original_reported_tests'}


@pytest.mark.parametrize('change',['missing','empty','negative','overflow','nonfinite','bool'])
def test_damaged_source_never_becomes_a_successful_or_empty_opportunity(change):
    x=outcome()
    if change=='missing':x['checkpoints']['checkpoint_2'].pop('original_reported_passed')
    elif change=='empty':x['checkpoints']={}
    elif change=='negative':x['checkpoints']['checkpoint_2']['original_reported_total']=-1
    elif change=='overflow':x['checkpoints']['checkpoint_2']['original_reported_passed']=11
    elif change=='nonfinite':x['checkpoints']['checkpoint_2']['original_reported_passed']=float('inf')
    else:x['checkpoints']['checkpoint_2']['original_reported_passed']=True
    r=normalized_source_metrics(x)
    assert r['partial']['value']is None and r['partial']['status']=='unknown'


def test_known_submission_gate_is_zero_contribution_but_not_executed_test_counts():
    x=outcome();p=x['checkpoints']['checkpoint_2'];p.clear();p.update(status='SCORED',reason='required submitted file absent',
        missing_required_files=['migration_tool.py'],original_all_reported_tests_score=0,score=0)
    r=normalized_source_metrics(x)
    assert r['partial']['value']==.8 and r['partial']['stage_evidence']['checkpoint_2']['kind']=='known_delivery_gate_failure'
    assert r['partial']['stage_evidence']['checkpoint_2']['executed_tests']==0
    bad=deepcopy(x);bad['checkpoints']['checkpoint_2']['missing_required_files']=['unrelated.txt']
    assert normalized_source_metrics(bad)['partial']['value']is None


def test_explicit_case_partial_evidence_is_not_overridden_by_missing_generic_counts():
    r=normalized_source_metrics(outcome())['partial']
    normalized=normalize_trial_scores({'normalization_evidence':{'S3.partial_pass_rate':r}})
    m=next(m for m in normalized['metrics']if m['id']=='S3.partial_pass_rate')
    assert m['score']==pytest.approx(98)and m['support_n']==5 and m['support_s']==4.9


def test_report_keeps_original_zero_and_conditional_skip_separate_from_stage_scores(tmp_path,monkeypatch):
    import json

    from memweave_eval.fixed35 import checkpoint_verdict
    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import atomic_json, file_digest

    good=checkpoint_verdict({'id':'unit','required_assertions':['unit']},{'unit':True})
    component={'case_id':'SCB-02','fixture_only':True,'collection_complete':True,'scope':'unit source fixture',
        'checkpoints':{k:good for k in ['record-2','record-3','source-business-3','task-continuity']}}
    monkeypatch.setattr('memweave_eval.slop_fk_gold.grade_trial',lambda *args,**kwargs:component)
    selected={'S3.original_reward','S3.partial_pass_rate','S.common.protected_constraints','S.common.process_validation'}
    matrix=[{'metric_id':m['id'],'design_status':'PLANNED'if m['id']in selected else'DESIGN_NA',
        'reason':'unit fixture only','opportunity_ids':[m['id']]if m['id']in selected else[]}for m in catalogue()['metrics']]
    cp=tmp_path/'contract.json';atomic_json(cp,{'version':'unit-fixture','adapter_kind':'slop-fk-source-v1','metric_matrix':matrix})
    atomic_json(tmp_path/'admission.json',{'case_id':'SCB-02','benchmark':'SlopCodeBench','family':'slop',
        'contract_path':str(cp),'contract_sha256':file_digest(cp)})
    trial=tmp_path/'unit-trial/result.json';atomic_json(trial,{'config':{'agent':{'name':'source-program-fixture'}}})
    atomic_json(tmp_path/'pair-result.json',{'arms':[{'arm':a,'result_path':str(trial),'exception':None,'verifier':None,
        'collection':{'fixture_control':True,'state_metrics':{},'cache':{},'tools':{},'estimated_usd':0.,'collection_complete':True}}for a in ['pi-native','pi-memweave']]})
    x=outcome()
    for i,p in enumerate(x['checkpoints'].values(),1):
        p.update(original_reported_passed=1 if i<=2 else 86,original_reported_total=1 if i<=2 else 87,
            original_all_reported_tests_score=100 if i<=2 else 0)
    x.update(original_all_reported_tests_AND=0,score=100,collection_complete=True,
        host_verifier_timing={'status':'CAPTURED','clock':'monotonic','wall_seconds':2.5})
    op=tmp_path/'official.json';atomic_json(op,{'case_id':'SCB-02','fixture_scores_included':True,
        'arms':{a:x for a in ['pi-native','pi-memweave']}})
    single_report(tmp_path,tmp_path/'report',op,fixture_control=True)
    report=json.loads((tmp_path/'report/results.json').read_text())
    for row in report['rows']:
        m={m['id']:m for m in row['normalized_metrics']}
        assert m['S3.original_reward']['score']==0
        assert m['S3.partial_pass_rate']['score']==pytest.approx(100*(2+3*86/87)/5)
        assert m['S.common.process_validation']['score']==40
        assert m['S.common.protected_constraints']['score']==100
        assert row['slop_score_channels']['original_strict']['score']==0
        assert row['slop_score_channels']['derived_applicable']['score']==100
        assert row['phase_seconds']['verifier']==2.5


def test_actual_host_clock_is_recorded_even_when_required_submission_prevents_test_execution(tmp_path,monkeypatch):
    import json
    import time

    from memweave_eval.fixed35_slop import evaluate_trial
    for i in range(1,9):
        p=tmp_path/'trial/steps'/f'checkpoint_{i}'/'artifacts';(p/'submission').mkdir(parents=True)
        (p/'manifest.json').write_text(json.dumps([{'source':'/workspace','destination':'artifacts/submission','status':'empty'}]))
    def no_process(*args,**kwargs):raise AssertionError('No verifier subprocess for proven missing entry')
    monkeypatch.setattr('subprocess.Popen',no_process)
    r=evaluate_trial(tmp_path/'trial',problem='circuit_eval',stages=[f'checkpoint_{i}'for i in range(1,9)],
        runner='unused',environment='unused',sources='unused',output=tmp_path/'output',deadline=time.time()+10,
        env={},expected_image='unused',fixture_only=True)
    assert r['host_verifier_timing']['status']=='CAPTURED'and r['host_verifier_timing']['wall_seconds']>=0
    assert all(p['official_test_execution'].startswith('not started')for p in r['checkpoints'].values())
    assert normalized_source_metrics(r)['partial']['value']==0
