import copy

import pytest

from memweave_eval.primary_report import ctrf_assertions, score_pair


def contract():
    return {'schema_version':'primary-score-contract.v1','status':'approved','scoring_version':'fixture-v1','case_id':'TB-01',
        'engineering':[{'id':'e.rate','meaning':'common receipt rate','raw_formula':'successes / attempts','unit':'ratio','mapping':'rate_difference','weight':1,'source':'common_tool_rate'}],
        'behavior':[{'id':'h.semantic','meaning':'both necessary tests','raw_formula':'AND then opportunity success rate','unit':'checkpoint','weight':1,
                     'opportunities':[{'id':'end','required_assertions':['test:a','test:b']}]}]}


def arm():
    return {'metrics':{'common_tool_rate':{'status':'observed','raw':1,'support':{'s':2,'f':0,'u':0,'n':2}}},
            'assertions':{'test:a':'pass','test:b':'pass'},'original_business_result':{'reward':1}}


def test_pair_uses_one_kernel_and_keeps_two_independent_totals():
    a,b=arm(),arm();b['metrics']['common_tool_rate']['raw']=.5;b['assertions']['test:b']='fail'
    result=score_pair(contract(),{'pi-native':a,'pi-memweave':b})
    assert result['engineering']['total']['score']==25
    assert result['behavior']['pi-native']['total']['score']==100
    assert result['behavior']['pi-memweave']['total']['score']==0
    assert 'combined_total'not in result
    row=result['engineering']['metrics']['e.rate'];assert row['raw_formula']=='successes / attempts'and row['weight']==1


def test_missing_or_bad_assertion_blocks_total_without_erasing_denominator():
    b=arm();del b['assertions']['test:b']
    result=score_pair(contract(),{'pi-native':arm(),'pi-memweave':b})
    m=result['behavior']['pi-memweave']['metrics']['h.semantic'];assert m['status']=='missing'and m['denominator']==1
    assert result['behavior']['pi-memweave']['total']['score']is None
    assert result['engineering']['total']['score']==50


def test_draft_mismatched_masks_and_duplicate_metric_ids_never_score():
    for change in [{'status':'design_review_pending'},{'engineering':[]},{'behavior':[]}]:
        with pytest.raises(ValueError):score_pair(contract()|change,{'pi-native':arm(),'pi-memweave':arm()})
    c=contract();c['behavior'].append(copy.deepcopy(c['behavior'][0]))
    with pytest.raises(ValueError):score_pair(c,{'pi-native':arm(),'pi-memweave':arm()})


def test_ctrf_success_failure_missing_skipped_and_duplicates_stay_distinct():
    assert ctrf_assertions({'results':{'tests':[{'name':'a','status':'passed'},{'name':'b','status':'failed'},{'name':'c','status':'skipped'}]}},['a','b','c','d'])=={'test:a':'pass','test:b':'fail','test:c':'missing','test:d':'missing'}
    r=ctrf_assertions({'results':{'tests':[{'name':'a','status':'passed'},{'name':'a','status':'passed'}]}},['a'])
    assert r=={'test:a':'invalid'}


def test_real_report_adapter_checks_frozen_contract_and_raw_hashes(tmp_path):
    import json

    from memweave_eval.primary_report import score_run, write_primary_artifacts
    from memweave_eval.storage import atomic_json, file_digest

    c=contract()|{'task_name':'batched-eval-parity','verifier_test_names':['a','b']}
    atomic_json(tmp_path/'primary-case.json',c);indexed=[];rows=[]
    for variant in ('pi-native','pi-memweave'):
        trial=tmp_path/variant;(trial/'verifier').mkdir(parents=True)
        atomic_json(trial/'result.json',{'verifier_result':{'rewards':{'reward':1}}})
        atomic_json(trial/'verifier/ctrf.json',{'results':{'tests':[{'name':'a','status':'passed'},{'name':'b','status':'passed'}]}})
        for p in trial.rglob('*.json'):indexed.append({'path':str(p.relative_to(tmp_path)),'sha256':file_digest(p)})
        rows.append({'variant_id':variant,'task_id':'batched-eval-parity','score_source':variant+'/result.json'})
    atomic_json(tmp_path/'evidence-index.json',{'files':indexed})
    lock={'run_id':'fixture','primary_case_sha256':file_digest(tmp_path/'primary-case.json')}
    result=score_run(tmp_path,lock,rows);assert result['engineering']['total']['score']is None
    assert result['behavior']['pi-memweave']['total']['score']==100
    out=tmp_path/'supplement';out.mkdir();write_primary_artifacts(out,result)
    assert 'raw_formula'in(out/'primary-scores.csv').read_text()and '含义'in(out/'primary-report.md').read_text()
    assert 'normalized_scores'not in json.loads((out/'primary-scores.json').read_text())
    (tmp_path/'pi-native/verifier/ctrf.json').write_text('{}')
    with pytest.raises(ValueError,match='changed'):score_run(tmp_path,lock,rows)


def test_existing_automatic_report_uses_primary_totals_and_never_old_combined_profiles(tmp_path):
    import json

    from memweave_eval.report import generate_report
    from memweave_eval.storage import atomic_json, evidence_index, file_digest

    c=contract()|{'task_name':'batched-eval-parity','verifier_test_names':['a','b']}
    atomic_json(tmp_path/'primary-case.json',c);plans=[];jobs={}
    for variant in ('pi-native','pi-memweave'):
        name=variant+'-r1';trial=tmp_path/'harbor'/name/'trial';(trial/'verifier').mkdir(parents=True)
        atomic_json(trial/'result.json',{'task_name':'batched-eval-parity','verifier_result':{'rewards':{'reward':1}}})
        atomic_json(trial/'verifier/ctrf.json',{'results':{'tests':[{'name':'a','status':'passed'},{'name':'b','status':'passed'}]}})
        plans.append({'task_id':'batched-eval-parity','variant_id':variant,'repetition':1});jobs[name]={'path':'harbor/'+name}
    lock={'schema_version':1,'run_id':'fixture','suite':{'id':'terminal-bench-4','protocol':'tb4'},'plan':plans,
          'config':{'evaluation':{'primary_default':True}},'primary_case_sha256':file_digest(tmp_path/'primary-case.json')}
    atomic_json(tmp_path/'experiment.lock.json',lock);atomic_json(tmp_path/'run.json',{'jobs':jobs})
    atomic_json(tmp_path/'evidence-index.json',{'files':evidence_index(tmp_path)})
    summary=generate_report(tmp_path)
    assert 'primary_scores'in summary and 'normalized_scores'not in summary
    assert summary['complete']is False and summary['primary_collection_accepted']is False
    assert summary['primary_scores']['behavior']['pi-native']['total']['score']==100
    result=json.loads((tmp_path/'reports/results.json').read_text());assert 'primary_scores'in result['summary']
    assert (tmp_path/'reports/primary-scores.csv').exists()and '独立工程相对分'in(tmp_path/'reports/report.md').read_text()
    assert not (tmp_path/'reports/normalized-scores.json').exists()


def test_report_rejects_whole_tail_deletion_even_after_reindexing(tmp_path):
    import hashlib
    import json

    from memweave_eval.report import generate_report
    from memweave_eval.storage import atomic_json, evidence_index, file_digest

    c=contract()|{'task_name':'batched-eval-parity','verifier_test_names':['a','b']}
    c['engineering'][0]['weight']=.5
    c['engineering'].append({'id':'e.service','meaning':'complete service responses','raw_formula':'complete / HTTP attempts',
        'unit':'ratio','mapping':'rate_difference','weight':.5,'source':'service_complete_rate'})
    atomic_json(tmp_path/'primary-case.json',c);plans=[];jobs={};audit=[];entries=[];requests={};traces={}
    for variant in ('pi-native','pi-memweave'):
        name=variant+'-r1';trial=tmp_path/'harbor'/name/'trial';(trial/'verifier').mkdir(parents=True);(trial/'agent').mkdir()
        atomic_json(trial/'result.json',{'task_name':'batched-eval-parity','agent_execution':{'started_at':'2026-11-04T00:00:00+00:00','finished_at':'2026-11-04T00:00:01+00:00'},'verifier_result':{'rewards':{'reward':1}}})
        atomic_json(trial/'verifier/ctrf.json',{'results':{'tests':[{'name':'a','status':'passed'},{'name':'b','status':'passed'}]}})
        (trial/'agent/pi.txt').write_text('\n'.join(json.dumps({'type':kind,'toolName':'read','toolCallId':'call','isError':False})for kind in ('tool_execution_start','tool_execution_end'))+'\n')
        events=[];ids=[]
        for n in range(2):
            identity=f'{variant}-{n}';ids.append(identity);requests[identity]={'arm':variant,'episode':'fixture','status':'settled'}
            events.extend([{'event':kind,'request_id':identity,**detail}for kind,detail in [
                ('budget_reserved',{}),('request_ready',{}),('http_attempt',{}),('http_response',{'status':200}),
                ('budget_settled',{'charge_usd':.01}),('request_end',{'settled':True,'stream_done':True,'usage':{'input':100,'output':2,'cache_hit':0}})]])
        trace=trial/'agent/request-trace.jsonl';trace.write_text(''.join(json.dumps(e)+'\n'for e in events));traces[variant]=trace
        audit.extend(events);entries.append({'arm':variant,'episode':'fixture','admitted_request_ids':ids,'http_request_ids':ids,'terminal_request_ids':ids})
        plans.append({'task_id':'batched-eval-parity','variant_id':variant,'repetition':1});jobs[name]={'path':'harbor/'+name}
    trusted=tmp_path/'trusted';trusted.mkdir();previous='0'*64;chain=[]
    for index,event in enumerate(audit,1):
        item={'sequence':index,'previous_hash':previous,**event};previous=hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();chain.append(item|{'event_hash':previous})
    (trusted/'transport-audit.jsonl').write_text(''.join(json.dumps(e)+'\n'for e in chain))
    atomic_json(trusted/'quota.final.json',{'requests':requests})
    atomic_json(trusted/'transport-terminal.json',{'schema_version':'trusted-transport-terminal.v1','finalized':True,'entries':entries,'audit_events':len(chain),'audit_head':previous})
    lock={'schema_version':1,'run_id':'fixture','experiment_kind':'free_transport_fixture','suite':{'id':'terminal-bench-4','protocol':'tb4'},'plan':plans,
          'config':{'evaluation':{'primary_default':True}},'primary_case_sha256':file_digest(tmp_path/'primary-case.json')}
    atomic_json(tmp_path/'experiment.lock.json',lock);atomic_json(tmp_path/'run.json',{'jobs':jobs})
    atomic_json(tmp_path/'evidence-index.json',{'files':evidence_index(tmp_path)})
    complete=generate_report(tmp_path);assert complete['primary_collection_accepted']and complete['complete']
    assert complete['is_model_performance_result']is False
    trace=traces['pi-native'];lines=[json.loads(x)for x in trace.read_text().splitlines()]
    trace.write_text(''.join(json.dumps(e)+'\n'for e in lines if e['request_id']!='pi-native-1'))
    atomic_json(tmp_path/'evidence-index.json',{'files':evidence_index(tmp_path)})
    broken=generate_report(tmp_path)
    assert broken['complete']is False and broken['primary_collection_accepted']is False
    assert broken['primary_scores']['engineering']['total']['score']is None
    integrity=broken['primary_scores']['raw_arms']['pi-native']['transport_integrity']
    assert integrity['status']=='invalid_missing'and integrity['missing_admitted_ids']==['pi-native-1']
