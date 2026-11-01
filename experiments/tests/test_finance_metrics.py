import pytest

from memweave_eval.finance_metrics import aggregate_cache, cache_metrics, finance_summary


def row(task, variant, cost, usage=None, **context):
    return {'task_id':task,'repetition':1,'variant_id':variant,'usage':usage or {},
            'finance_estimated_usd':cost,'finance_context':{'model':'flash','price':'peak-v1','currency':'USD',**context}}


def test_cache_includes_hit_already_and_aggregate_is_token_weighted():
    a={'input_tokens':100,'cache_tokens':80,'output_tokens':100}
    b={'input_tokens':900,'cache_tokens':90,'output_tokens':0}
    assert cache_metrics(a)['input_cache_utilization']['value']==.8
    assert cache_metrics(a)['all_tokens_cache_share']['value']==.4
    assert aggregate_cache([a,b])['input_cache_utilization']['value']==.17
    assert aggregate_cache([a,b])['all_tokens_cache_share']['value']==pytest.approx(170/1100)


@pytest.mark.parametrize('usage,status',[
    ({'input_tokens':10,'cache_tokens':None,'output_tokens':2},'unknown'),
    ({'input_tokens':10,'cache_tokens':0,'output_tokens':2},'scored'),
    ({'input_tokens':0,'cache_tokens':0,'output_tokens':0},'not_applicable'),
    ({'input_tokens':10,'cache_tokens':11,'output_tokens':2},'invalid'),
    ({'input_tokens':-1,'cache_tokens':0,'output_tokens':2},'invalid'),
])
def test_cache_missing_zero_and_invalid_are_distinct(usage,status):
    assert cache_metrics(usage)['input_cache_utilization']['status']==status


def test_cost_ratio_uses_matched_sums_not_average_ratios():
    rows=[row('a','pi-native',1),row('a','pi-memweave',2),
          row('b','pi-native',9),row('b','pi-memweave',9)]
    result=finance_summary(rows)
    assert result['overall_cost_ratio']['value']==1.1
    assert result['overall_cost_ratio']['percent_of_native']==pytest.approx(110)
    assert result['overall_cost_ratio']['relative_change']==pytest.approx(.1)
    assert finance_summary([row('a','pi-native',0),row('a','pi-memweave',2)])['pairs'][0]['cost_ratio']['status']=='not_applicable'
    assert finance_summary([row('a','pi-native',None),row('a','pi-memweave',2)])['overall_cost_ratio']['status']=='unknown'
    mismatched=[row('a','pi-native',1),row('a','pi-memweave',2,price='different')]
    assert finance_summary(mismatched)['pairs'][0]['cost_ratio']['reason']=='incompatible_pair_context'
