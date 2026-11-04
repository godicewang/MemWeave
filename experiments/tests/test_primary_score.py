import pytest

from memweave_eval.primary_score import behavior_score, relative_score, weighted_total


def test_relative_rates_use_the_pair_not_plugin_absolute_success():
    r=relative_score(15/16,14/16,mapping='rate_difference')
    assert r['score']==46.875 and r['difference']==-.0625
    assert relative_score(.5,.5,mapping='rate_difference')['score']==50
    assert relative_score(.4,.8,mapping='rate_difference')['score']==70


def test_lower_cost_and_time_mapping_has_explicit_zero_boundaries():
    assert relative_score(2,1,mapping='lower_share')['score']==pytest.approx(100*2/3)
    assert relative_score(1,2,mapping='lower_share')['score']==pytest.approx(100/3)
    r=relative_score(0,1,mapping='lower_share');assert r['score']==0 and r['plugin_native_ratio']['kind']=='positive_infinity'
    assert relative_score(0,0,mapping='lower_share')['status']=='not_comparable'
    assert relative_score(None,2,mapping='lower_share')['status']=='missing'


@pytest.mark.parametrize('native,plugin',[(True,0),(-1,0),(0,float('nan')),(float('inf'),0)])
def test_invalid_values_are_not_clipped(native,plugin):
    assert relative_score(native,plugin,mapping='lower_share')['status']=='invalid'
    assert relative_score(0,1.01,mapping='rate_difference')['status']=='invalid'


def fixture():
    o=[{'id':str(i),'required_assertions':['a','b','c','d']}for i in range(3)]
    e={x['id']:{k:'pass'for k in x['required_assertions']}for x in o};return o,e


def test_binary_and_then_opportunity_rate_never_subassertion_partial_credit():
    o,e=fixture();e['1']['c']='fail';r=behavior_score(o,e)
    assert r['score']==pytest.approx(200/3)and r['numerator']==2 and r['denominator']==3
    e['1']['c']='missing';r=behavior_score(o,e);assert r['score']is None and r['denominator']==3 and r['status']=='missing'
    e['1']['a']='fail';assert behavior_score(o,e)['score']is None


def test_prerequisite_absence_does_not_remove_a_planned_opportunity():
    o=[{'id':'update','required_assertions':['capture_old','apply_update','use_latest']}]
    e={'update':{'capture_old':'fail','apply_update':'pass','use_latest':'pass'}}
    r=behavior_score(o,e);assert r['score']==0 and r['denominator']==1
    del e['update']['capture_old'];r=behavior_score(o,e);assert r['score']is None and r['denominator']==1


def test_empty_duplicate_or_invalid_contracts_are_rejected():
    for o in [[],[{'id':'x','required_assertions':[]}],[{'id':'x','required_assertions':['a','a']}]]:
        with pytest.raises(ValueError):behavior_score(o,{})
    o,e=fixture();e['0']['a']='not_applicable'
    assert behavior_score(o,e)['status']=='invalid'


def test_two_totals_stay_independent_and_missing_never_becomes_zero_or_other_class_credit():
    engineering=weighted_total({'a':relative_score(1,1,mapping='lower_share')},{'a':1})
    o,e=fixture();e['0']['a']='missing';behavior=weighted_total({'b':behavior_score(o,e)},{'b':1})
    assert engineering['score']==50 and behavior['score']is None
    assert behavior['evidence_coverage']==0 and behavior['conditional_score']is None
    assert 'combined_score'not in engineering
    with pytest.raises(ValueError):weighted_total({'a':{'score':100,'status':'observed'}},{'a':0})


def test_malformed_external_assertion_values_and_large_finite_numbers_are_safe():
    o=[{'id':'x','required_assertions':['a']}]
    assert behavior_score(o,{'x':{'a':[]}})['status']=='invalid'
    assert behavior_score(o,{'x':{'a':{}}})['status']=='invalid'
    assert relative_score(1e308,1e308,mapping='lower_share')['score']==50
    assert relative_score(1e-308,1e308,mapping='lower_share')['plugin_native_ratio']=={'kind':'overflow','value':None}
    with pytest.raises(TypeError):behavior_score([None],{})
    with pytest.raises(TypeError):weighted_total({'x':None},{'x':1})
    with pytest.raises(ValueError):weighted_total({'x':{},'y':{}},{'x':1e308,'y':1e308})
    assert relative_score(10**1000,1,mapping='lower_share')['status']=='invalid'
    result=weighted_total({'a':{'status':'observed','score':70},'b':{'status':'missing','score':None}},{'a':1e-308,'b':1e308})
    assert result['conditional_score']==70 and result['score']is None
    assert weighted_total({'a':{'status':'invalid','score':None}},{'a':1})['status']=='invalid'
