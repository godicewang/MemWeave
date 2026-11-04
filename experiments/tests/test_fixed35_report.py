from memweave_eval.fixed35_report import weighted_profile


def test_missing_mandatory_capture_cannot_produce_a_complete_weighted_point_score():
    rows=[{'id':i,'weights':{'p':.5},'status':'scored','score':100,'collection_status':status}
        for i,status in [('a',None),('b','REPAIR_REQUIRED')]]
    result=weighted_profile(rows,'p')
    assert result['score']is None and result['coverage']==.5
    assert result['conditional_score']==100 and result['missing_metric_ids']==['b']


def test_fixed_profile_keeps_missing_weight_and_does_not_make_a_point_total():
    rows=[{'id':'a','weights':{'p':.4},'score':100,'status':'scored'},
          {'id':'b','weights':{'p':.4},'score':None,'status':'unknown'},
          {'id':'c','weights':{'p':.2},'score':None,'status':'DESIGN_NA'}]
    profile=weighted_profile(rows,'p')
    assert profile['score'] is None and profile['conditional_score']==100
    assert profile['coverage']==.5 and profile['lower']==50 and profile['upper']==100
    rows[1].update(score=0,status='scored')
    assert weighted_profile(rows,'p')['score']==50


def test_common_comparison_selects_the_same_frozen_metric_ids():
    rows=[{'id':'a','weights':{'p':.4},'score':100,'status':'scored'},
          {'id':'b','weights':{'p':.6},'score':0,'status':'scored'}]
    assert weighted_profile(rows,'p',allowed_ids={'b'})['score']==0


def test_single_report_profile_keeps_audited_exception_separate_from_missing():
    import pytest
    rows=[{'id':'a','weights':{'p':.5},'score':60,'status':'scored'},
        {'id':'b','weights':{'p':.5},'score':None,'status':'EXCLUDED_UNCOLLECTABLE',
         'reason':'Primary and mirror response lost','repair_attempts':[{'action':'recover mirrors','result':'both truncated'}]}]
    profile=weighted_profile(rows,'p')
    assert profile['score']==60 and profile['coverage']==1 and profile['pre_exclusion_coverage']==.5
    assert profile['excluded_weight']==.5 and profile['design_weight']==1
    rows[1]['repair_attempts']=[]
    with pytest.raises(ValueError,match='exception'):weighted_profile(rows,'p')
    rows[1].update(status='unknown')
    assert weighted_profile(rows,'p')['score']is None


def test_known_checkpoint_failure_with_missing_evidence_still_blocks_collection():
    from memweave_eval.fixed35_report import mark_checkpoint_collection
    rows=[{'id':'F35.C4-three-window-checkpoints','status':'scored','score':0},
        {'id':'S.common.protected_constraints','status':'scored','score':100},
        {'id':'unused','status':'DESIGN_NA','score':None}]
    mark_checkpoint_collection(rows,{'F35.C4-three-window-checkpoints':{'score':0,'collection_complete':False},
        'S.common.protected_constraints':{'score':100,'collection_complete':True},
        'unused':{'score':None,'collection_complete':False}})
    assert rows[0]['score']==0 and rows[0]['collection_status']=='REPAIR_REQUIRED'
    assert 'collection_status'not in rows[1]and 'collection_status'not in rows[2]


def test_proved_insufficient_uniformity_sample_is_not_treated_as_missing_or_perfect():
    from memweave_eval.fixed35_report import qualify_state_statistics
    item={'id':'Q7.uniformity_cv','status':'insufficient_sample','score':None,'weights':{'p':1}}
    state={'source_status':'ok','write_model_positions':[14],
        'uniformity':{'status':'insufficient_sample','intervals':[],'mean_interval':None}}
    qualify_state_statistics(item,item['id'],state)
    assert item['score']is None and item['status']=='CONDITIONAL_NO_OPPORTUNITY'
    assert item['statistical_denominator']['committed_batches']==1
    assert weighted_profile([item],'p')['eligible_weight']==0
    missing={'id':'Q7.uniformity_cv','status':'insufficient_sample','score':None}
    state['source_status']='missing_initial_inventory'
    qualify_state_statistics(missing,missing['id'],state)
    assert missing['status']=='insufficient_sample','missing evidence must not acquire a zero-opportunity exemption'


def test_known_zero_model_return_denominator_is_distinct_from_missing_usage():
    from memweave_eval.fixed35_report import qualify_state_statistics
    state={'source_status':'ok','ratio_status':'zero_model_responses','model_responses_with_usage':0,'fd_events_added':0}
    item={'id':'Q7.fd_density','status':'unknown','score':None,'raw':None,'collection_status':'REPAIR_REQUIRED'}
    qualify_state_statistics(item,item['id'],state)
    assert item['status']=='CONDITIONAL_NO_OPPORTUNITY'and item['score']is None and 'collection_status'not in item
    state['model_responses_with_usage']=None
    unknown={'id':'Q7.fd_density','status':'unknown','score':None,'raw':None,'collection_status':'REPAIR_REQUIRED'}
    qualify_state_statistics(unknown,unknown['id'],state)
    assert unknown['status']=='unknown'and unknown['collection_status']=='REPAIR_REQUIRED'


def test_no_state_writes_proves_undefined_interval_diagnostics_without_faking_zero():
    from memweave_eval.fixed35_report import qualify_state_statistics
    state={'source_status':'ok','write_model_positions':[], 'model_responses_with_usage':2,
        'uniformity':{'status':'insufficient_sample','intervals':[],
            'mean_interval':None,'max_interval':None,'head_calls':None,'tail_calls':None}}
    for identity in ['Q7.mean_interval','Q7.max_interval','Q7.head_calls','Q7.tail_calls']:
        item={'status':'unknown','raw':None,'score':None,'collection_status':'REPAIR_REQUIRED'}
        qualify_state_statistics(item,identity,state)
        assert item['status']=='CONDITIONAL_NO_OPPORTUNITY'and item['raw']is None
        assert 'collection_status'not in item
        assert item['statistical_denominator']['whole_no_write_span']==2


def test_one_write_has_head_and_tail_but_no_internal_gap():
    from memweave_eval.fixed35_report import qualify_state_statistics
    state={'source_status':'ok','write_model_positions':[3], 'model_responses_with_usage':5,
        'uniformity':{'status':'insufficient_sample','intervals':[],
            'mean_interval':None,'max_interval':None,'head_calls':3,'tail_calls':2}}
    for identity in ['Q7.mean_interval','Q7.max_interval']:
        item={'status':'unknown','raw':None,'score':None,'collection_status':'REPAIR_REQUIRED'}
        qualify_state_statistics(item,identity,state)
        assert item['status']=='CONDITIONAL_NO_OPPORTUNITY'
    for identity,value in [('Q7.head_calls',3),('Q7.tail_calls',2)]:
        item={'status':'diagnostic','raw':value,'score':None}
        qualify_state_statistics(item,identity,state)
        assert item['status']=='diagnostic'and item['raw']==value


def test_missing_or_incoherent_state_positions_never_waive_missing_diagnostics():
    from copy import deepcopy

    from memweave_eval.fixed35_report import qualify_state_statistics
    base={'source_status':'ok','write_model_positions':[], 'model_responses_with_usage':2,
        'uniformity':{'status':'insufficient_sample','intervals':[]}}
    for patch in [{'source_status':'missing_initial_inventory'}, {'write_model_positions':None},
                  {'model_responses_with_usage':None}, {'write_model_positions':[True]},
                  {'write_model_positions':[3]}, {'uniformity':{'status':'unknown','intervals':[]}}]:
        state=deepcopy(base);state.update(patch)
        item={'status':'unknown','raw':None,'score':None,'collection_status':'REPAIR_REQUIRED'}
        qualify_state_statistics(item,'Q7.mean_interval',state)
        assert item['status']=='unknown'and item['collection_status']=='REPAIR_REQUIRED'


def test_existing_report_keeps_slop_original_and_derived_channels_separate(tmp_path):
    import csv
    import json

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest

    contract=tmp_path/'contract.json';contract.write_text(json.dumps({'version':'synthetic-slop-provenance-only',
        'metric_matrix':[{'metric_id':m['id'],'design_status':'PLANNED'if m['id']=='S3.original_reward'else'DESIGN_NA',
            'opportunity_ids':['synthetic-source-verdict'],
            'reason':'Synthetic unit-test scope; not a case applicability decision'}for m in catalogue()['metrics']]}))
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'SCB-02','family':'slop','benchmark':'SlopCodeBench',
        'contract_path':str(contract),'contract_sha256':file_digest(contract)}))
    collection={'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True}
    (tmp_path/'pair-result.json').write_text(json.dumps({'arms':[{'arm':arm,
        'result_path':str(tmp_path/arm/'result.json'),'collection':collection,'exception':None,'verifier':None}
        for arm in ['pi-native','pi-memweave']]}))
    official=tmp_path/'outcomes.json';official.write_text(json.dumps({'case_id':'SCB-02','fixture_scores_included':False,
        'arms':{arm:{'score':100,'original_all_reported_tests_AND':0,'collection_complete':True}
            for arm in ['pi-native','pi-memweave']}}))
    single_report(tmp_path,tmp_path/'reports',official,fixture_control=True)
    report=json.loads((tmp_path/'reports/results.json').read_text())
    assert report['fixture_scores_included']is True
    for row in report['rows']:
        assert row['native_reward']==0
        original=next(m for m in row['normalized_metrics']if m['id']=='S3.original_reward')
        assert original['raw']==original['score']==0
        assert row['slop_score_channels']['derived_applicable']['score']==100
    csv_rows=list(csv.DictReader((tmp_path/'reports/slop-score-channels.csv').open()))
    assert len(csv_rows)==4 and {r['score']for r in csv_rows}=={'0','100'}
    main_csv=[r for r in csv.DictReader((tmp_path/'reports/metrics.csv').open())if r['metric_id']=='S3.original_reward']
    assert len(main_csv)==2 and all(float(r['score'])==0 and json.loads(r['raw'])==0 for r in main_csv)
    assert 'Slop原始严格与派生适用测试口径'in(tmp_path/'reports/report.md').read_text()
    missing=json.loads(official.read_text());missing['arms']['pi-memweave'].pop('original_all_reported_tests_AND')
    official.write_text(json.dumps(missing));single_report(tmp_path,tmp_path/'missing-report',official,fixture_control=True)
    row=json.loads((tmp_path/'missing-report/results.json').read_text())['rows'][1]
    metric=next(m for m in row['normalized_metrics']if m['id']=='S3.original_reward')
    assert row['native_reward']is None and metric['score']is None and metric['status']=='unknown'
