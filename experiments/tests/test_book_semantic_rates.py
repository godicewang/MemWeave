import json
from copy import deepcopy

import pytest


@pytest.mark.parametrize('case',['MAB-04','MAB-06','MAB-07','MAB-08'])
@pytest.mark.parametrize('mode',['pass','wrong-write','middle-loss','pollution','late','missing','no-write'])
def test_book_specific_source_predicates_have_pass_fail_missing_and_distinct_denominators(case,mode):
    from memweave_eval.book_semantic_rates import book_semantic_rates
    from memweave_eval.fixed35_mab_cards import BOOKS
    contract=BOOKS[case];card=json.dumps(contract['card'])
    points=[{'original_source_absent':True,'current_facts_retained':True,
        'semantic_unarchived_checks':{'no_incompatible_current_event':True}}for _ in range(3)]
    action={'assertions':{k:{'value':True}for k in ['correct_typed_event_relation',
        'no_incompatible_current_event','before_dependency','business_action_correct']}}
    writes=[card]
    if mode=='wrong-write':
        bad=deepcopy(contract['card']);bad.update(contract['incompatible'][0]);writes.append(json.dumps(bad))
    elif mode=='middle-loss':points[1]['current_facts_retained']=False
    elif mode=='pollution':points[1]['semantic_unarchived_checks']['no_incompatible_current_event']=False
    elif mode=='late':action['assertions']['before_dependency']['value']=False
    elif mode=='missing':points[1].pop('current_facts_retained')
    elif mode=='no-write':writes=[]
    result=book_semantic_rates(contract,points,action,writes,complete=True,source_exposed=True)
    if mode=='wrong-write':assert result['write_precision']['value']==.5
    elif mode=='middle-loss':assert result['retention']['value']==pytest.approx(2/3)
    elif mode=='pollution':assert result['pollution']['value']==pytest.approx(1/3)
    elif mode=='late':assert result['adoption']['value']==0
    elif mode=='missing':assert result['retention']['unknown']==1 and result['retention']['value']is None
    elif mode=='no-write':assert result['write_precision']['status']=='not_applicable'
    else:assert all(result[k]['value']==1 for k in ['timely_write','retention','write_precision','adoption'])


def test_unparsed_or_other_qualified_event_is_not_claimed_correct():
    from memweave_eval.book_semantic_rates import book_semantic_rates
    from memweave_eval.fixed35_mab_cards import BOOKS
    card=deepcopy(BOOKS['MAB-04']['card']);card['q']='a different event condition'
    result=book_semantic_rates(BOOKS['MAB-04'],[],{},['free text',json.dumps(card)],complete=False,source_exposed=None)
    assert result['controlled_coverage']['target_card_changes']==0
    assert result['controlled_coverage']['outside_parser_or_target']==2
    assert result['adoption']['status']=='unknown'


def test_new_mab04_case_mapping_is_opt_in_and_does_not_rewrite_historical_definition():
    from memweave_eval.book_semantic_rates import VERSION
    from memweave_eval.fixed35_mab import normalization_points
    behavior={'typed_book_memory':{'score':100}}
    assert 'S.case_v2.C1-transient-baseline'not in normalization_points(behavior,'MAB-04')
    behavior['semantic_rates']={'version':VERSION}
    assert normalization_points(behavior,'MAB-04')['S.case_v2.C1-transient-baseline']['score']==100
