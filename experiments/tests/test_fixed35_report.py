from memweave_eval.fixed35_report import weighted_profile


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
