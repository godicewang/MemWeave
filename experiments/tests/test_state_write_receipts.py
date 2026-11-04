from copy import deepcopy

import pytest

TOOLS=['state_append','modify_fact','update_goal','state_remain','task_create']


def sample(tool,a=3,s=2,f=1,u=0):
    return {'state_metrics':{'session_counts_status':'complete','episode_return_scope_consistent':True,
        'writes':{tool:{'attempts':a,'successes':s,'failures':f,'unknown':u,'success_rate':s/a if a and not u else None}}},
        'execution_boundary_collection':{'complete':True},'stage_execution':{'evidence_complete':True},
        'tools':{tool:{'attempts':a,'successes':s,'errors':f,'unknown_results':u}}}


@pytest.mark.parametrize('tool',TOOLS)
@pytest.mark.parametrize('mode',['mixed','failed','partial','zero'])
def test_receipt_opportunities_keep_counts_coverage_and_zero_distinct(tool,mode):
    from memweave_eval.normalized_scores import normalize_trial_scores
    from memweave_eval.state_write_receipts import receipt_evidence
    values={'mixed':(3,2,1,0),'failed':(2,0,2,0),'partial':(5,2,1,2),'zero':(0,0,0,0)}
    c=sample(tool,*values[mode]);p=receipt_evidence(c)[tool]
    row={'variant_id':'pi-memweave','state_metrics':c['state_metrics'],
        'normalization_evidence':{'Q2.write.'+tool+'.success':p}}
    m=next(m for m in normalize_trial_scores(row)['metrics']if m['id']=='Q2.write.'+tool+'.success')
    if mode=='zero':assert m['score']is None and m['status']=='not_applicable'and p['complete']
    else:
        a,s,f,u=values[mode];assert m['score']==pytest.approx(100*s/(s+f))
        assert m['support_s']==s and m['support_f']==f and m['support_u']==u and m['support_n']==a
        assert m['coverage']==(a-u)/a and p['complete']==(u==0)
        assert m['lower']==100*s/a and m['upper']==100*(s+u)/a


@pytest.mark.parametrize('mode',['no-session','scope','no-boundary','no-stages','no-tools','no-field','mismatch','negative','boolean','bad-sum'])
def test_missing_or_conflicting_sources_never_default_to_zero_or_success(mode):
    from memweave_eval.state_write_receipts import receipt_evidence
    c=sample('state_append');before=deepcopy(c)
    if mode=='no-session':c['state_metrics']['session_counts_status']='missing'
    elif mode=='scope':c['state_metrics']['episode_return_scope_consistent']=False
    elif mode=='no-boundary':c['execution_boundary_collection']={}
    elif mode=='no-stages':c['stage_execution']={}
    elif mode=='no-tools':c.pop('tools')
    elif mode=='no-field':c['state_metrics']['writes']['state_append'].pop('attempts')
    elif mode=='mismatch':c['tools']['state_append'].update(successes=1,errors=2)
    elif mode=='negative':c['tools']['state_append']['attempts']=-1
    elif mode=='boolean':c['tools']['state_append']['attempts']=True
    else:c['state_metrics']['writes']['state_append']['successes']=3
    expected=deepcopy(c);p=receipt_evidence(c)['state_append']
    assert p['status']in {'unknown','invalid'}and not p['complete']and p['value']is None
    assert p['numerator']is None and p['denominator']is None
    assert c==expected
    assert before['tools']['state_append']['attempts']==3


def test_absent_independent_tool_row_is_zero_only_with_complete_dual_source_proof():
    from memweave_eval.state_write_receipts import receipt_evidence
    c=sample('state_append',0,0,0,0);c['tools']={}
    assert receipt_evidence(c)['state_append']['status']=='not_applicable'
    c['execution_boundary_collection']['complete']=False
    assert receipt_evidence(c)['state_append']['status']=='unknown'


def test_multiple_execution_starts_cannot_hide_failure_behind_one_final_receipt():
    from memweave_eval.state_write_receipts import receipt_evidence
    c=sample('state_append',1,1,0,0);c['tools']['state_append']['executions']=2
    p=receipt_evidence(c)['state_append']
    assert p['status']=='unknown'and not p['complete']and p['value']is None
    assert 'individual_attempt_receipts'in p['reason']


def test_authored_opportunities_do_not_mutate_old_matrix_or_overwrite_explicit_na():
    from memweave_eval.fixed35_sources import author_write_receipt_opportunities
    from memweave_eval.state_write_receipts import METRICS, VERSION
    rows=[{'case_id':'a','metric_id':i,'design_status':'DESIGN_UNRESOLVED','opportunity_ids':[]}for i in METRICS]
    before=deepcopy(rows);first=author_write_receipt_opportunities(rows)
    assert rows==before and all(r['design_status']=='PLANNED'and r['opportunity_version']==VERSION for r in first)
    assert author_write_receipt_opportunities(first)==first
    rows[0].update(design_status='DESIGN_NA',reason='Explicit frozen scope')
    assert author_write_receipt_opportunities(rows)[0]==rows[0]
    rows[0]['design_status']='INVALID_DESIGN_STATUS'
    assert author_write_receipt_opportunities(rows)[0]==rows[0]


def test_unknown_dual_source_result_still_blocks_collection_without_losing_partial_interval():
    from memweave_eval.normalized_scores import normalize_trial_scores
    from memweave_eval.state_write_receipts import qualify_receipt, receipt_evidence
    c=sample('state_append',5,2,1,2);proof=receipt_evidence(c)['state_append']
    m=next(m for m in normalize_trial_scores({'variant_id':'pi-memweave','state_metrics':c['state_metrics'],
        'normalization_evidence':{'Q2.write.state_append.success':proof}})['metrics']if m['id']=='Q2.write.state_append.success')
    qualify_receipt(m,proof)
    assert m['score']==pytest.approx(200/3)and m['collection_status']=='REPAIR_REQUIRED'
    assert m['support_u']==2 and m['lower']==40 and m['upper']==80


def test_invalid_receipt_proof_cannot_become_zero_opportunity_exemption():
    from memweave_eval.normalized_scores import normalize_trial_scores
    from memweave_eval.state_write_receipts import qualify_receipt, receipt_evidence
    c=sample('state_append');c['tools']['state_append']['attempts']=True
    p=receipt_evidence(c)['state_append'];m={'status':'unknown','score':None}
    qualify_receipt(m,p)
    assert m['status']=='invalid'and m['collection_status']=='REPAIR_REQUIRED'
    metric=next(m for m in normalize_trial_scores({'variant_id':'pi-memweave','state_metrics':c['state_metrics'],
        'normalization_evidence':{'Q2.write.state_append.success':p}})['metrics']if m['id']=='Q2.write.state_append.success')
    assert metric['status']=='invalid'and metric['score']is None


@pytest.mark.parametrize('change',[{'state_metrics':[]},{'execution_boundary_collection':None},{'stage_execution':None}])
def test_malformed_collection_shapes_are_unknown_not_zero(change):
    from memweave_eval.state_write_receipts import receipt_evidence
    c=sample('state_append');c.update(change)
    p=receipt_evidence(c)['state_append']
    assert p['status']=='unknown'and p['value']is None and not p['complete']


def test_existing_report_scores_only_reconciled_receipts_and_repairs_a_damaged_source(tmp_path):
    import csv
    import json

    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    c=sample('state_append');cp=tmp_path/'contract.json'
    cp.write_text(json.dumps({'version':'unit-write-receipts','metric_matrix':[{'metric_id':m['id'],
        'design_status':'PLANNED'if m['id']=='Q2.write.state_append.success'else'DESIGN_NA',
        'opportunity_ids':['unit-only'],'reason':'Unit fixture, not real applicability'}for m in catalogue()['metrics']]}))
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'unit','family':'unit','benchmark':'unit',
        'contract_path':str(cp),'contract_sha256':file_digest(cp)}))
    collection=dict(c,cache={},estimated_usd=0,collection_complete=True,fixture_control=True)
    pair={'arms':[{'arm':a,'result_path':str(tmp_path/a/'result.json'),'collection':collection,
        'exception':None,'verifier':None}for a in ['pi-native','pi-memweave']]}
    pp=tmp_path/'pair-result.json';pp.write_text(json.dumps(pair))
    single_report(tmp_path,tmp_path/'report',fixture_control=True)
    report=json.loads((tmp_path/'report/results.json').read_text());assert report['collection_accepted']
    m=next(m for m in report['rows'][1]['normalized_metrics']if m['id']=='Q2.write.state_append.success')
    assert m['score']==pytest.approx(200/3)and m['support_s']==2 and m['support_n']==3
    assert 'Session/execution'in m['raw_formula']
    exported=next(r for r in csv.DictReader((tmp_path/'report/metrics.csv').open())if
        r['arm']=='pi-memweave'and r['metric_id']=='Q2.write.state_append.success')
    assert json.loads(exported['session_receipt_counts'])==json.loads(exported['execution_receipt_counts'])==[3,2,1,0]
    assert next(m for m in report['rows'][0]['normalized_metrics']if m['id']=='Q2.write.state_append.success')['status']=='DESIGN_NA'
    pair['arms'][1]['collection']['tools']['state_append'].update(successes=1,errors=2);pp.write_text(json.dumps(pair))
    single_report(tmp_path,tmp_path/'damaged-report',fixture_control=True)
    bad=json.loads((tmp_path/'damaged-report/results.json').read_text());assert not bad['collection_accepted']
    m=next(m for m in bad['rows'][1]['normalized_metrics']if m['id']=='Q2.write.state_append.success')
    assert m['score']is None and m['status']=='unknown'and m['collection_status']=='REPAIR_REQUIRED'
