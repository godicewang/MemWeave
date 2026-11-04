import json

import pytest


def inputs():
    from memweave_eval.fixed35_fact_cards import FACTS
    facts={'facts':FACTS['MAB-01']};card=json.dumps(facts['facts'][0]['card'])
    points=[{'boundary_id':str(i),'original_source_absent':True,'current_facts_retained':True,
        'semantic_unarchived_checks':{'no_competing_current_relation':True}}for i in range(3)]
    correction={'assertions':{k:{'value':True}for k in ['all_current_relations','no_competing_current_relation',
        'snapshot_precedes_dependency','action_uses_current_value','source_exposed_before_dependency']}}
    return facts,card,points,correction


@pytest.mark.parametrize('mode',['pass','late','middle-loss','pollution','wrong-write','no-write','missing'])
def test_source_target_semantic_rates_have_distinct_denominators_and_missing(mode):
    from memweave_eval.mab_semantic_rates import semantic_rates
    f,card,points,correction=inputs();writes=[card]
    if mode=='late':points[0]['current_facts_retained']=False
    elif mode=='middle-loss':points[1]['current_facts_retained']=False
    elif mode=='pollution':points[1]['semantic_unarchived_checks']['no_competing_current_relation']=False
    elif mode=='wrong-write':writes.append(card.replace('Steve Jobs','Satya Nadella'))
    elif mode=='no-write':writes=[]
    elif mode=='missing':points[1].pop('current_facts_retained')
    result=semantic_rates(f,points,correction,writes,complete=True,prior_active_record=True)
    if mode=='missing':assert result['retention']['unknown']==1 and not result['retention']['collection_complete']
    elif mode=='late':assert result['timely_write']['value']==0
    elif mode=='middle-loss':assert result['retention']['value']==pytest.approx(2/3)
    elif mode=='pollution':assert result['pollution']['value']==pytest.approx(1/3)
    elif mode=='wrong-write':assert result['write_precision']['value']==.5
    elif mode=='no-write':assert result['write_precision']['status']=='not_applicable'and result['write_precision']['value']is None
    else:assert all(result[k]['value']==1 for k in ['timely_write','retention','write_precision'])and result['pollution']['value']==0


def test_unparsed_or_other_subject_text_is_outside_controlled_precision_not_a_free_pass():
    from memweave_eval.mab_semantic_rates import semantic_rates
    f,card,points,correction=inputs();r=semantic_rates(f,points,correction,['not a card',card.replace('Microsoft','Apple')],complete=True)
    assert r['write_precision']['value']is None and r['controlled_coverage']['target_card_changes']==0
    assert r['controlled_coverage']['outside_parser_or_target']==2
    r=semantic_rates(f,points,correction,[card],complete=False)
    assert r['write_precision']['status']=='unknown'and not r['write_precision']['collection_complete']


@pytest.mark.parametrize('observed',[False,None])
def test_correct_guess_without_proven_source_exposure_is_not_correction(observed):
    from memweave_eval.mab_semantic_rates import semantic_rates
    f,card,points,correction=inputs();correction['assertions']['source_exposed_before_dependency']['value']=observed
    result=semantic_rates(f,points,correction,[card],complete=True,prior_active_record=True)
    assert result['correction']['value']==(0 if observed is False else None)
    assert result['adoption']['value']==(0 if observed is False else None)


def test_never_storing_old_card_is_not_a_successful_update_and_missing_history_not_zero_opportunity():
    from memweave_eval.mab_semantic_rates import semantic_rates
    f,card,points,correction=inputs()
    absent=semantic_rates(f,points,correction,[card],complete=True,prior_active_record=False)
    assert absent['correction']['status']=='not_applicable'and absent['correction']['denominator']==0
    missing=semantic_rates(f,points,correction,[card],complete=True,prior_active_record=None)
    assert missing['correction']['value']is None and missing['correction']['unknown']==1


@pytest.mark.parametrize('prior,status',[(False,'CONDITIONAL_NO_OPPORTUNITY'),(None,'MISSING_EVIDENCE')])
def test_c5_case_point_does_not_award_update_success_when_no_prior_record(prior,status):
    from memweave_eval.fixed35_mab import normalization_points
    behavior={'memory':{'correction':{'score':100},'prior_active_record_seen':prior}}
    point=normalization_points(behavior,'MAB-01')['S.case_v2.C5-correct-before-action']
    assert point['score']is None and point['status']==status


def test_counterevidence_boundary_is_its_own_source_not_later_unrelated_hop():
    from memweave_eval.fixed35_mab import counterevidence_visible
    old={'counterevidence_source':{'support':'475. Christianity was founded in the city of Taipei.'}}
    assert counterevidence_visible(['475. Christianity was founded in the city of Taipei.'],old,all_current_exposed=False)
    assert not counterevidence_visible(['Later unrelated bridge fact'],old,all_current_exposed=True)
    assert not counterevidence_visible(['# Symbolic State\n475. Christianity was founded in the city of Taipei.'],old,all_current_exposed=True)
    assert counterevidence_visible([],{},all_current_exposed=True)
