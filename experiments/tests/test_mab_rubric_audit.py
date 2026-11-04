from memweave_eval.mab_rubric_audit import measured_components, reject_mismatched_slot


def test_components_have_accurate_new_ids_and_never_inherit_old_weights():
    p={'score':100,'status':'SCORED','collection_complete':True,'assertions':{'file':{'value':True}}}
    rows=measured_components({'derived_action':p,'typed_book_memory':p},arm='pi-memweave')
    assert {r['id']for r in rows}=={'F35.MAB.answer_schema_artifact','F35.MAB.source_retention_action_consistency'}
    assert all(r['score']==100 and not any(r['weights'].values())for r in rows)
    bad=measured_components({'derived_action':dict(p,score=0)},arm='pi-memweave')
    assert bad[0]['score']==0 and bad[1]['score']is None and not bad[1]['collection_complete']
    assert measured_components({},arm='pi-native')[1]['status']=='DESIGN_NA'


def test_a_different_predicate_is_not_a_success_of_the_original_metric():
    for identity in ['S.common.protected_constraints','S.case_v2.C1-transient-baseline']:
        metric={'score':100,'status':'scored'};reject_mismatched_slot(metric,identity)
        assert metric['score']is None and metric['observed_unaccepted_score']==100
        assert metric['repair_kind']=='evaluator_design'and metric['collection_status']=='REPAIR_REQUIRED'
        na={'score':None,'status':'DESIGN_NA'};reject_mismatched_slot(na,identity);assert na=={'score':None,'status':'DESIGN_NA'}
    valid={'score':0,'status':'scored'};reject_mismatched_slot(valid,'S.case_v2.C5-correct-before-action');assert valid['score']==0
