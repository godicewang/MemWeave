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
