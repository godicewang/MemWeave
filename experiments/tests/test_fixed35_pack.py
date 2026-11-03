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


def test_complete_mathematical_zero_opportunities_never_turn_into_structural_design_na():
    registry,expected,rows=setup_rows()
    rows=[dict(r,status='CONDITIONAL_NO_OPPORTUNITY',score=None,collection_complete=True,
        reason='complete positions prove only one committed batch')for r in rows]
    result=package_metrics(rows,expected,registry)
    assert result['collection_accepted']
    assert all(r['status']=='CONDITIONAL_NO_OPPORTUNITY'and r['score']is None and r['collection_accepted']for r in result['aggregates'])
    assert all(r['mathematical_na']==3 for r in result['aggregates'])
    assert all(r['status']=='CONDITIONAL_NO_OPPORTUNITY'for r in result['matched_common_aggregates'])


@pytest.mark.parametrize('complete',[None,False])
def test_conditional_denominator_needs_explicit_complete_evidence(complete):
    registry,expected,rows=setup_rows()
    rows=[dict(r,status='CONDITIONAL_NO_OPPORTUNITY',score=None,collection_complete=True)for r in rows]
    if complete is None:rows[0].pop('collection_complete')
    else:rows[0]['collection_complete']=complete
    result=package_metrics(rows,expected,registry)
    assert not result['collection_accepted']
    assert result['rows'][0]['status']=='MISSING_EVIDENCE'
    assert result['aggregates'][0]['missing']==1 and result['aggregates'][0]['mathematical_na']==2


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


def test_score_label_without_a_value_is_not_a_matched_common_measurement():
    registry,expected,rows=setup_rows();registry[0]['weights']={'common_product':1,'plugin_memory':1}
    rows[-1]=dict(rows[-1],score=None)
    result=package_metrics(rows,expected,registry)
    pair=next(p for p in result['comparisons']if p['case_id']=='c')
    assert pair['matched_metric_ids']==[]
    assert all(t['score']is None and t['coverage']==0 for t in pair['arms'].values())
    assert all(t['status']=='MISSING_EVIDENCE'for t in result['matched_common_aggregates'])


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


def test_all_common_collection_exceptions_remain_exceptions_with_case_reasons():
    registry,expected,rows=setup_rows();registry[0]['weights']={'common_product':1,'plugin_memory':1}
    rows=[dict(r,status='EXCLUDED_UNCOLLECTABLE',score=None,reason='original and mirror unavailable',
        repair_attempts=['validated both captured sources'])if r['arm']=='pi-memweave'else r for r in rows]
    result=package_metrics(rows,expected,registry)
    assert not result['collection_accepted']
    assert all(r['status']=='EXCLUDED_UNCOLLECTABLE'and len(r['excluded_cases'])==3
        for r in result['matched_common_aggregates'])
    assert all(t['score']is None for t in result['matched_common_totals'].values())


def test_unresolved_design_blocks_acceptance_even_if_a_numeric_result_exists():
    registry,expected,rows=setup_rows()
    expected[0]=dict(expected[0],design_status='DESIGN_UNRESOLVED',reason='opportunity not frozen')
    result=package_metrics(rows,expected,registry)
    assert not result['collection_accepted']
    unresolved=result['rows'][0]
    assert unresolved['status']=='DESIGN_UNRESOLVED' and unresolved['score'] is None
    assert unresolved['observed_unaccepted_score']==0
    assert unresolved['reason']=='opportunity not frozen'


def test_result_cannot_hide_planned_or_unresolved_metric_as_design_na():
    registry,expected,rows=setup_rows()
    rows[0]=dict(rows[0],status='DESIGN_NA',score=None,reason='no record discovered')
    for status in ('PLANNED','DESIGN_UNRESOLVED'):
        expected[0]=dict(expected[0],design_status=status)
        with pytest.raises(ValueError,match='cannot introduce a design NA'):
            package_metrics(rows,expected,registry)


def test_report_contract_and_schema_are_bound_not_just_case_label():
    from copy import deepcopy

    from memweave_eval.fixed35_pack import validate_case_report
    case={'case_id':'a','contract_sha256':'a'*64,'report_schema_version':3,'report_evaluator_version':'frozen-v4'}
    contract={'version':'case-contract-v2'}
    report={'case_id':'a','contract_sha256':'a'*64,'contract_version':'case-contract-v2',
        'schema_version':3,'evaluator_version':'frozen-v4','fixture_scores_included':False,
        'rows':[{'case_id':'a','variant_id':arm,'normalized_metrics':[{'id':'m','mapping_version':'frozen-v4'}]}
            for arm in ('pi-native','pi-memweave')]}
    validate_case_report(case,contract,report,{'m'})
    for key,value in [('case_id','b'),('contract_sha256','b'*64),('contract_version','old'),
        ('schema_version',2),('evaluator_version','old'),('fixture_scores_included',True)]:
        with pytest.raises(ValueError):validate_case_report(case,contract,dict(report,**{key:value}),{'m'})
    bad=deepcopy(report);bad['rows'][1]['normalized_metrics']=[]
    with pytest.raises(ValueError,match='metric schema'):validate_case_report(case,contract,bad,{'m'})
    bad=deepcopy(report);bad['rows'][0]['case_id']='another-case'
    with pytest.raises(ValueError,match='variant row'):validate_case_report(case,contract,bad,{'m'})
    bad=deepcopy(report);bad['rows'][0]['normalized_metrics'][0]['mapping_version']='old'
    with pytest.raises(ValueError,match='mapping versions'):validate_case_report(case,contract,bad,{'m'})
    with pytest.raises(ValueError,match='not frozen'):validate_case_report(
        {k:v for k,v in case.items()if k!='report_evaluator_version'},contract,report,{'m'})
