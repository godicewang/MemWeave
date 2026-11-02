from copy import deepcopy

import pytest

from memweave_eval.fixed35 import (
    aggregate_metric,
    checkpoint_verdict,
    paired_effective_rows,
    validate_selection,
)


def test_checkpoint_and_not_whole_case_and_and_missing_is_not_false():
    contract = {'id': 'cp', 'required_assertions': ['action', 'state', 'regression']}
    evidence = {'action': True, 'state': True, 'regression': True}
    assert checkpoint_verdict(contract, evidence)['score'] == 100
    assert checkpoint_verdict(contract, dict(evidence, state=False))['score'] == 0
    missing = checkpoint_verdict(contract, {'action': True, 'regression': True})
    assert missing['score'] is None and missing['status'] == 'MISSING_EVIDENCE'
    assert missing['missing_assertions'] == ['state']
    # A proven failed assertion is a real zero, while the independent collection gap remains.
    mixed = checkpoint_verdict(contract, {'action': False})
    assert mixed['score'] == 0 and mixed['collection_complete'] is False
    assert evidence == {'action': True, 'state': True, 'regression': True}


def test_empty_or_duplicate_required_assertions_cannot_pass_vacuously():
    for ids in ([], ['x', 'x']):
        with pytest.raises(ValueError):
            checkpoint_verdict({'id': 'cp', 'required_assertions': ids}, {})
    assert checkpoint_verdict({'id': 'cp', 'required_assertions': ['x']}, {'x': None})['score'] is None


def test_metric_uses_case_then_benchmark_macro_not_pool_size():
    rows = [{'case_id': str(i), 'benchmark': 'a', 'score': v, 'status': 'SCORED'}
            for i, v in enumerate([100, 100, 0])]
    rows += [{'case_id': 'x', 'benchmark': 'b', 'score': 0, 'status': 'SCORED'}]
    result = aggregate_metric(rows)
    assert result['score'] == pytest.approx((200/3+0)/2)
    assert result['benchmarks']['a']['valid_cases'] == 3
    assert result['valid_cases'] == 4


def test_structural_na_and_unrecoverable_collection_exception_are_distinct():
    rows = [{'case_id': 'a', 'benchmark': 'b', 'score': 100, 'status': 'SCORED'},
            {'case_id': 'n', 'benchmark': 'b', 'score': None, 'status': 'DESIGN_NA', 'reason': 'native no State'},
            {'case_id': 'm', 'benchmark': 'b', 'score': None, 'status': 'MISSING_EVIDENCE'}]
    result = aggregate_metric(rows)
    assert result['score'] == 100 and result['collection_accepted'] is False
    assert result['design_na'] == 1 and result['missing'] == 1
    rows[-1] = dict(rows[-1], status='EXCLUDED_UNCOLLECTABLE', reason='source irrecoverably truncated',
                   repair_attempts=[{'action': 'read-back', 'result': 'failed'}])
    result = aggregate_metric(rows)
    assert result['excluded'] == 1 and result['missing'] == 0
    assert result['collection_accepted'] is False
    with pytest.raises(ValueError):
        aggregate_metric([dict(rows[-1], repair_attempts=[])])


def test_comparison_uses_common_effective_case_metric_mask():
    rows = [{'case_id': c, 'metric_id': 'm', 'arm': a, 'benchmark': 'b', 'score': s, 'status': st}
            for c, a, s, st in [('a','pi-native',100,'SCORED'),('a','pi-memweave',0,'SCORED'),
                                ('b','pi-native',0,'SCORED'),('b','pi-memweave',None,'MISSING_EVIDENCE')]]
    pair = paired_effective_rows(rows)
    assert len(pair['pi-native']) == len(pair['pi-memweave']) == 1
    assert pair['excluded_pairs'] == [('b', 'm')]
    assert pair['pi-native'][0]['case_id'] == pair['pi-memweave'][0]['case_id']


def test_selection_rejects_duplicate_source_case_even_under_different_labels():
    selection = {'cases': [{'pack_case_id': 'a', 'benchmark': 'b', 'upstream_case_id': 'x', 'source_revision': 'a'*40},
                           {'pack_case_id': 'b', 'benchmark': 'b', 'upstream_case_id': 'x', 'source_revision': 'a'*40}]}
    original = deepcopy(selection)
    with pytest.raises(ValueError):
        validate_selection(selection, expected_count=2)
    assert selection == original


def test_collection_acceptance_requires_nonempty_frozen_complete_expected_set():
    assert aggregate_metric([])['collection_accepted'] is False
    expected=[{'benchmark':'b','case_id':'one'},{'benchmark':'b','case_id':'two'}]
    row={'benchmark':'b','case_id':'one','score':100,'status':'SCORED'}
    partial=aggregate_metric([row],expected_cases=expected)
    assert partial['not_run']==1 and partial['omitted_rows']==[('b','two')]
    assert partial['collection_accepted'] is False
    assert aggregate_metric([row],expected_cases=expected[:1])['collection_accepted'] is True
    assert aggregate_metric([row])['collection_accepted'] is False
    with pytest.raises(ValueError):
        aggregate_metric([row],expected_cases=expected[:1]*2)
