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
    result=semantic_rates(f,points,correction,writes,complete=True)
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
    result=semantic_rates(f,points,correction,[card],complete=True)
    assert result['correction']['value']==(0 if observed is False else None)
    assert result['adoption']['value']==(0 if observed is False else None)
