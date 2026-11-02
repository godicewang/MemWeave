import pytest

from memweave_eval.fixed35_pack import package_metrics


def setup_rows():
    registry=[{'id':'m','mapping':'rate_higher','meaning':'success rate','raw_formula':'s/n',
        'score_formula':'100*s/n','weights':{'p':1}}]
    expected=[{'case_id':c,'benchmark':b,'arm':a,'metric_id':'m','design_status':'PLANNED'}
        for c,b in [('a','A'),('b','A'),('c','B')]for a in ('pi-native','pi-memweave')]
    rows=[dict(e,status='SCORED',score=s)for e,s in zip(expected,[0,0,100,100,100,100],strict=True)]
    return registry,expected,rows


def test_full_matrix_macro_and_missing_entire_case_cannot_pass():
    registry,expected,rows=setup_rows();result=package_metrics(rows,expected,registry)
    assert result['collection_accepted']
    assert result['aggregates'][0]['score']==75
    result=package_metrics(rows[:-2],expected,registry)
    assert not result['collection_accepted']and result['expected_cells']==6
    assert result['aggregates'][0]['not_run']==1
    assert result['rows'][-1]['status']=='NOT_RUN'
    assert not package_metrics([],expected,registry)['collection_accepted']


def test_na_requires_design_and_duplicate_or_unexpected_cells_rejected():
    registry,expected,rows=setup_rows()
    with pytest.raises(ValueError):package_metrics(rows+rows[:1],expected,registry)
    expected[0]=dict(expected[0],design_status='DESIGN_NA',reason='frozen scope')
    with pytest.raises(ValueError):package_metrics(rows,expected,registry)
    rows[0]=dict(expected[0],status='DESIGN_NA',score=None)
    assert package_metrics(rows,expected,registry)['rows'][0]['score']is None


def test_common_pair_uses_same_scored_intersection_and_keeps_missing_coverage():
    registry,expected,rows=setup_rows()
    registry[0]['weights']={'common_product':1,'plugin_memory':1}
    result=package_metrics(rows[:-1],expected,registry)
    pair=next(x for x in result['comparisons']if x['case_id']=='c')
    assert pair['matched_metric_ids']==[]
    for arm in pair['arms'].values():
        assert arm['score'] is None and arm['coverage']==0
    assert result['totals']['pi-memweave']['plugin_memory']['score'] is None
    assert result['totals']['pi-native']['common_product']['score']==75


def test_existing_cli_writes_all_35_rows_even_with_no_run_reports(tmp_path):
    import csv
    import json
    from types import SimpleNamespace

    from memweave_eval.fixed35_cli import execute
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    cases=[]
    for index in range(35):
        contract=tmp_path/f'contract-{index}.json'
        contract.write_text(json.dumps({'metric_matrix':[{'metric_id':m['id'],
            'design_status':'PLANNED','reason':'synthetic integration contract'}for m in catalogue()['metrics']]}))
        cases.append({'case_id':f'case-{index}','benchmark':'synthetic-fixture',
            'contract_path':str(contract),'contract_sha256':file_digest(contract)})
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'cases':cases}))
    result=execute(SimpleNamespace(fixed35_command='pack-report',manifest=manifest,output=tmp_path/'report'))
    assert result['expected_cells']==35*2*len(catalogue()['metrics'])
    assert result['observed_cells']==0 and not result['collection_accepted']
    table=list(csv.DictReader((tmp_path/'report/pi-memweave-wide.csv').open()))
    assert len(table)==35 and all(r['S3.original_reward']=='NOT_RUN'for r in table)


def test_two_classes_keep_fixed_half_weights_and_comparison_denominators():
    registry=[{'id':identity,'mapping':'rate','meaning':identity,'raw_formula':'s/n','score_formula':'100*s/n',
        'category':category,'applicability':'all','weights':{'common_product':.5,'plugin_memory':.5}}
        for identity,category in [('e','engineering'),('b','behavior')]]
    expected=[{'case_id':'c','benchmark':'B','arm':a,'metric_id':m['id'],'design_status':'PLANNED'}
        for a in ('pi-native','pi-memweave')for m in registry]
    rows=[dict(e,status='SCORED',score=100 if e['metric_id']=='e'else 0)for e in expected]
    result=package_metrics(rows,expected,registry)
    for total in result['matched_common_totals'].values():
        assert total['score']==50
        assert total['classes']['engineering']['score']==100
        assert total['classes']['behavior']['score']==0
    result=package_metrics(rows[:-1],expected,registry)
    for total in result['matched_common_totals'].values():
        assert total['score']is None and total['coverage']==.5


def test_irreparable_exception_is_shared_and_never_design_na():
    registry,expected,rows=setup_rows();registry[0]['weights']={'common_product':1,'plugin_memory':1}
    rows[-1]=dict(rows[-1],status='EXCLUDED_UNCOLLECTABLE',score=None,
        reason='raw response lost beyond both mirrors',repair_attempts=['primary parse','mirror recovery rejected'])
    result=package_metrics(rows,expected,registry)
    pair=next(p for p in result['comparisons']if p['case_id']=='c')
    assert pair['excluded_metrics']['m']['status']=='EXCLUDED_UNCOLLECTABLE'
    assert pair['eligible_metric_ids']==[]
    assert all(t['score']==50 for t in result['matched_common_totals'].values())
    assert not result['collection_accepted']
    rows[-1].pop('repair_attempts')
    with pytest.raises(ValueError,match='requires reason and attempted repairs'):
        package_metrics(rows,expected,registry)
