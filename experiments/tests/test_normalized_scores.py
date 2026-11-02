import json
from copy import deepcopy

import pytest

from memweave_eval.normalized_scores import (
    attach_normalized_scores,
    catalogue,
    normalize_trial_scores,
    relative_cost_score,
    score_value,
    weighted_score,
)


def test_probability_maps_and_invalid_values():
    assert score_value(.75, 'rate')['score'] == 75
    assert score_value(.25, 'rate_lower')['score'] == 75
    for value in (-.1, 1.1, float('nan'), float('inf'), True):
        assert score_value(value, 'rate')['status'] == 'invalid'
    assert score_value(None, 'rate')['score'] is None
    assert score_value(2, 'rate', support={'numerator': 1, 'denominator': 2, 'unknown': 0})['status'] == 'invalid'
    assert score_value(.8, 'rate', support={'numerator': 1, 'denominator': 2, 'unknown': 0})['status'] == 'invalid'


def test_partial_tool_outcome_retains_denominator_and_bounds():
    metric = score_value(None, 'rate_lower', support={'numerator': 1, 'denominator': 3, 'unknown': 2})
    assert metric['score'] == pytest.approx(100 * 2/3)
    assert metric['coverage'] == .6
    assert metric['lower'] == 40
    assert metric['upper'] == 80
    assert metric['status'] == 'partial'
    assert score_value(None, 'rate', support={'numerator': 0, 'denominator': 0, 'unknown': 0})['score'] is None


@pytest.mark.parametrize(('raw', 'expected'), [(0, 0), (.025, 50), (.05, 100), (.1, 100), (.2, 50)])
def test_density_closed_band(raw, expected):
    assert score_value(raw, 'band')['score'] == pytest.approx(expected)


def test_uniformity_and_insufficient_samples():
    assert score_value(0, 'cv')['score'] == 100
    assert score_value(1, 'cv')['score'] == 50
    row = {'variant_id': 'pi-memweave', 'state_metrics': {'uniformity': {'cv': None, 'status': 'insufficient_sample'}}}
    result = normalize_trial_scores(row)
    metric = next(m for m in result['metrics'] if m['id'] == 'Q7.uniformity_cv')
    assert metric['status'] == 'insufficient_sample'
    assert metric['score'] is None


def test_relative_cost_boundaries_and_zero_baseline():
    assert relative_cost_score(1, 1)['score'] == 50
    assert relative_cost_score(1, .5)['score'] == pytest.approx(100/1.5)
    assert relative_cost_score(1, 2)['score'] == pytest.approx(100/3)
    assert relative_cost_score(0, 2)['score'] == 0
    assert relative_cost_score(2, 0)['score'] == 100
    assert relative_cost_score(0, 0)['status'] == 'not_applicable'
    assert relative_cost_score(None, 2)['status'] == 'unknown'
    assert relative_cost_score(1, 1, compatible=False)['status'] == 'unknown'


def test_fixed_weights_do_not_redistribute_missing_evidence():
    known = dict(score_value(1, 'rate'), id='a')
    missing = dict(score_value(None, 'rate'), id='b')
    result = weighted_score({'a': known, 'b': missing}, {'a': .5, 'b': .5})
    assert result['score'] is None
    assert result['observed_score'] == 100
    assert result['coverage'] == .5
    assert result['lower'] == 50
    assert result['upper'] == 100


def test_profile_weights_aliases_and_structural_native_na():
    c = catalogue()
    assert len({m['id'] for m in c['metrics']}) == len(c['metrics'])
    for name in c['profiles']:
        assert sum(m['weights'][name] for m in c['metrics']) == pytest.approx(1)
    rows = normalize_trial_scores({'variant_id': 'pi-native'})
    assert rows['profiles']['plugin_memory']['status'] == 'not_applicable'
    assert rows['profiles']['common_product']['score'] is None
    density = next(m for m in c['metrics'] if m['id'] == 'Q7.fd_density')
    assert density['weights']['plugin_memory'] == .015


def test_per_metric_explanation_and_diagnostic_qualification():
    scored = normalize_trial_scores({'variant_id': 'pi-native', 'engineering_metrics': {'http_attempts': 3}})
    for m in scored['metrics']:
        assert all(k in m for k in ('meaning', 'raw_formula', 'score_formula', 'unit', 'status', 'weight_basis', 'threshold_basis', 'reason', 'raw', 'score', 'weights', 'mapping_version'))
    count = next(m for m in scored['metrics'] if m['id'] == 'Q8.http_attempts')
    assert count['raw'] == 3 and count['score'] is None and count['status'] == 'diagnostic'


def test_task_macro_and_pair_common_coverage_do_not_pool_tests():
    rows = []
    for task, reward in [('a', 1), ('b', 0), ('c', 0)]:
        for variant in ('pi-native', 'pi-memweave'):
            rows.append({'task_id': task, 'variant_id': variant, 'native_reward': {'reward': reward}})
    before = deepcopy(rows)
    result = attach_normalized_scores(rows)
    assert result['by_variant']['pi-native']['common_product']['task_count'] == 3
    assert len(result['pairs']) == 3
    assert rows[0]['normalized_scores']['profiles']['common_product']['lower'] == pytest.approx(20)
    # Original reward/usage/behavior stay intact; only normalization fields are added.
    for old, new in zip(before, rows):
        assert all(new[k] == v for k, v in old.items())
    json.dumps(result, allow_nan=False)


def test_logical_missing_null_counts_remain_unknown_not_invalid():
    row = {'variant_id': 'pi-memweave', 'contract_metrics': {'logical_operations': {
        'recovery': {'value': None, 'numerator': None, 'denominator': None,
                     'unknown': 0, 'status': 'unknown', 'reason': 'explicit_operation_identity_missing'}}}}
    m = next(m for m in normalize_trial_scores(row)['metrics'] if m['id'] == 'Q1.logical.recovery')
    assert m['status'] == 'unknown' and m['score'] is None


def test_one_gap_cannot_become_perfect_uniformity_from_forged_cv_zero():
    row = {'variant_id': 'pi-memweave', 'state_metrics': {'uniformity': {'cv': 0, 'intervals': [10]}}}
    m = next(m for m in normalize_trial_scores(row)['metrics'] if m['id'] == 'Q7.uniformity_cv')
    assert m['status'] == 'insufficient_sample' and m['score'] is None
    row['state_metrics']['uniformity']['intervals'] = [0, 0]
    m = next(m for m in normalize_trial_scores(row)['metrics'] if m['id'] == 'Q7.uniformity_cv')
    assert m['status'] == 'insufficient_sample' and m['score'] is None
    row['state_metrics']['uniformity']['intervals'] = [1, 2]
    m = next(m for m in normalize_trial_scores(row)['metrics'] if m['id'] == 'Q7.uniformity_cv')
    assert m['status'] == 'invalid' and m['score'] is None


def test_cost_mapping_aggregates_costs_not_task_indices_and_requires_charge_coverage():
    rows = []
    for task, native, plugin in [('a', 1, 2), ('b', 9, 9)]:
        for variant, cost in [('pi-native', native), ('pi-memweave', plugin)]:
            rows.append({'task_id': task, 'variant_id': variant, 'finance_estimated_usd': cost,
                         'finance_context': {'model': 'm', 'price': 'p', 'currency': 'USD'},
                         'finance': {'unknown_charge_attempts': 0}})
    result = attach_normalized_scores(rows)
    assert result['auxiliary_finance']['relative_cost_overall']['score'] == pytest.approx(100*10/21)
    rows[0]['finance'] = {}
    result = attach_normalized_scores(rows)
    assert result['auxiliary_finance']['relative_cost_overall']['score'] is None


def test_nonfinite_raw_is_invalid_and_exportable_without_nan_json():
    row = {'variant_id': 'pi-native', 'native_reward': {'reward': float('nan')}}
    output = normalize_trial_scores(row)
    m = next(m for m in output['metrics'] if m['id'] == 'S3.original_reward')
    assert m['status'] == 'invalid' and m['score'] is None
    assert m['raw'] == {'invalid_number': 'nan'}
    json.dumps(output, allow_nan=False)


def test_partial_quality_uses_original_counts_not_rounded_fraction():
    row = {'variant_id': 'pi-memweave', 'behavior_metrics': {'native_metrics': {
        'passed': 31759, 'total': 31767, 'partial_score': .999748}}}
    m = next(m for m in normalize_trial_scores(row)['metrics'] if m['id'] == 'S3.partial_pass_rate')
    assert m['raw'] == 31759/31767
    assert m['score'] == pytest.approx(100*31759/31767)
