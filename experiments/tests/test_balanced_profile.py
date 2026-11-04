import pytest

from memweave_eval.balanced_profile import balanced_profile


def definition():return {'class_weights':{'engineering':.5,'behavior':.5},'engineering':{'tools':{'weight':1,'leaves':{'Q.a':.5,'Q.b':.5}}},'behavior':{'outcome':{'weight':.8,'leaves':{'S.a':1}},'memory':{'weight':.2,'leaves':{'S.b':1}}}}
def row(i,score=100,status='scored'):return {'id':i,'score':score,'status':status}


def test_na_leaf_and_na_family_cannot_shift_the_two_categories():
    rows=[row('Q.a'),row('Q.b',None,'DESIGN_NA'),row('S.a',0),row('S.b',None,'DESIGN_NA')]
    r=balanced_profile(rows,definition());assert r['score']==50
    assert r['effective_leaf_weights']=={'Q.a':.5,'S.a':.5}
    assert r['classes']['engineering']['eligible_weight']==r['classes']['behavior']['eligible_weight']==.5


def test_unknown_is_not_na_and_missing_category_does_not_become_a_perfect_full_score():
    r=balanced_profile([row('Q.a'),row('Q.b',None,'unknown'),row('S.a',0),row('S.b',0)],definition())
    assert r['score']is None and r['coverage']==.75 and r['lower']==25 and r['upper']==50
    r=balanced_profile([row('Q.a'),row('Q.b'),row('S.a',None,'DESIGN_NA'),row('S.b',None,'DESIGN_NA')],definition())
    assert r['score']is None and r['conditional_score']==100 and r['full_profile_design_coverage']==.5
    assert (r['full_profile_lower'],r['full_profile_upper'])==(50,100)


def test_common_intersection_and_alias_do_not_choose_different_denominators():
    rows=[row('Q.a',0),row('Q.b'),row('S.a',20),row('S.b')]
    r=balanced_profile(rows,definition(),allowed_ids={'Q.b','S.a'});assert r['score']==60
    assert sum(r['effective_leaf_weights'].values())==pytest.approx(1)
    rows[0].update(score=100,collection_status='REPAIR_REQUIRED')
    assert balanced_profile(rows,definition())['score']is None
