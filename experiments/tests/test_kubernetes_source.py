import copy

from memweave_eval.kubernetes_source import grade_evidence


def evidence():
    return {'expected_manifest':['tests/a.rs 2','tests/b.rs 1'],
        'manifest':['tests/a.rs 2','tests/b.rs 1'],
        'metrics':{'phase':'complete','build_status':'passed','counted_suite':'protected_integration_tests',
            'scoring_mode':'binary','passed':3,'passed_raw_uncapped':9,'failed':0,'ignored':0,
            'agent_unit_passed_uncounted':20,'min_passed_for_reward':3,'partial_score':1.,'reward':1},
        'parsed':{'integration_passed':3,'integration_passed_raw':9,'integration_failed':0,
            'integration_ignored':0,'unit_passed_uncounted':20,'structure_ok':True},
        'reward':1.,'reported_reward':1.,'raw_log_present':True,'terminal_summary':True,
        'build_log_present':True}


def test_original_protected_counts_exclude_unit_and_uncapped_passes():
    result=grade_evidence(evidence())
    assert result['collection_complete']and result['whole_protocol']['score']==100
    assert result['native_metrics']=={'passed':3,'total':3}
    assert result['source_counts']['uncounted_agent_unit_passed']==20


def test_partial_and_original_binary_stay_distinct():
    data=evidence();data['metrics'].update(passed=2,failed=1,partial_score=2/3,reward=0)
    data['parsed'].update(integration_passed=2,integration_failed=1)
    data.update(reward=0.,reported_reward=0.)
    result=grade_evidence(data)
    assert result['collection_complete']and result['whole_protocol']['score']==0
    assert result['native_metrics']=={'passed':2,'total':3}
    data=evidence();data['parsed']['structure_ok']=False
    data['metrics']['reward']=0;data.update(reward=0.,reported_reward=0.)
    result=grade_evidence(data)
    assert result['collection_complete']and result['whole_protocol']['score']==0
    assert result['native_metrics']['passed']==result['native_metrics']['total']


def test_missing_raw_or_terminal_evidence_is_not_a_known_zero():
    for key in ['raw_log_present','terminal_summary']:
        data=evidence();data[key]=False
        result=grade_evidence(data)
        assert not result['collection_complete']and result['native_metrics']is None
    data=evidence();data['metrics']['phase']='initialized'
    assert not grade_evidence(data)['collection_complete']


def test_manifest_multiplicity_and_metric_contradictions_require_repair():
    for mutate in [lambda d:d['manifest'].append('tests/a.rs 2'),
                   lambda d:d['metrics'].update(passed=2),
                   lambda d:d.update(reward=0),
                   lambda d:d['metrics'].update(passed=-1),
                   lambda d:d['metrics'].pop('passed')]:
        data=evidence();mutate(data);result=grade_evidence(data)
        assert not result['collection_complete']and result['native_metrics']is None


def test_completed_build_failure_has_unexecuted_tests_not_fabricated_assertions():
    data=evidence();data['metrics'].update(phase='build_failed',build_status='failed',
        passed=0,passed_raw_uncapped=0,failed=0,ignored=0,agent_unit_passed_uncounted=0,
        partial_score=0.,reward=0)
    data.update(parsed=None,reward=0.,reported_reward=0.,raw_log_present=False,terminal_summary=False)
    result=grade_evidence(data)
    assert result['collection_complete']and result['whole_protocol']['score']==0
    assert result['unexecuted_protected_tests']==3
    assert result['native_metrics']=={'passed':0,'total':3}
    missing=copy.deepcopy(data);missing['build_log_present']=False
    assert not grade_evidence(missing)['collection_complete']


def test_attached_original_outcome_runs_through_existing_report_and_normalization(tmp_path,monkeypatch):
    import json

    from memweave_eval import kubernetes_source
    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    gold=tmp_path/'original-gold.json';gold.write_text(json.dumps(
        {'case_id':'LONG-04','adapter_kind':'kubernetes-source-v1'}))
    called=[]
    def original_trial(trial,contract,*,fixture_control):
        called.append(trial);assert fixture_control
        return grade_evidence(evidence())
    monkeypatch.setattr(kubernetes_source,'grade_trial',original_trial)
    wanted={'S3.original_reward','S3.partial_pass_rate','S.common.process_validation'}
    contract=tmp_path/'contract.json';contract.write_text(json.dumps({'case_id':'LONG-04','version':'unit',
        'original_source_tests':{'path':str(gold),'sha256':file_digest(gold)},
        'metric_matrix':[{'metric_id':m['id'],'design_status':'PLANNED'if m['id']in wanted else'DESIGN_NA',
            'reason':'Unit integration scope','opportunity_ids':['unit']}for m in catalogue()['metrics']]}))
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'LONG-04','benchmark':'unit','family':'unit',
        'contract_path':str(contract),'contract_sha256':file_digest(contract)}))
    arms=[]
    for arm in ['pi-native','pi-memweave']:
        folder=tmp_path/arm;folder.mkdir();rp=folder/'result.json';rp.write_text('{}')
        arms.append({'arm':arm,'result_path':str(rp),'exception':None,'verifier':{'rewards':{'reward':1}},
            'collection':{'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,
                'transport_collection_complete':True,'collection_complete':True,'fixture_control':True}})
    (tmp_path/'pair-result.json').write_text(json.dumps({'arms':arms}))
    single_report(tmp_path,tmp_path/'report',fixture_control=True)
    result=json.loads((tmp_path/'report/results.json').read_text())
    assert len(called)==2 and result['collection_accepted']
    for row in result['rows']:
        metrics={m['id']:m for m in row['normalized_metrics']}
        assert metrics['S3.partial_pass_rate']['raw']==1
        assert metrics['S.common.process_validation']['score']==100
        assert 'cargo integration'in metrics['S.common.process_validation']['meaning']
        assert 'cargo integration'in metrics['S.common.process_validation']['raw_formula']
        assert '原题公开测试'in metrics['S.common.process_validation']['legacy_registry_meaning']
        assert row['attached_original_source_outcome']['source_counts']['raw_uncapped_passed']==9
