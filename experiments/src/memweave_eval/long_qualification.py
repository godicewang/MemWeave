"""Five fixed long-case qualifications, separate from task capability scores."""
from __future__ import annotations

import json
from pathlib import Path

from .fixed35_sources import read_design
from .storage import atomic_json, file_digest

VERSION='fixed35-long-reference-qualification-20261104-v2'
CASES=('TB-07','LONG-02','LONG-03','LONG-04','LONG-05')
THRESHOLD=1000


def qualify_attempt(row):
    """Never combine attempts or count tools/auxiliaries to meet the threshold."""
    keys=('formal','fixture','collection_complete','original_verifier_passed',
        'completed_actor_request_ids','actor_http_attempts')
    ids=row.get('completed_actor_request_ids')
    valid_ids=isinstance(ids,list)and all(isinstance(i,str)and i for i in ids)
    count=len(set(ids))if valid_ids else None
    result={'qualified':False,'task_success':row.get('original_verifier_passed'),
        'completed_unique_actor_calls':count,'threshold':THRESHOLD,
        'actor_http_attempts':row.get('actor_http_attempts'),
        'tool_attempts_excluded':row.get('tool_attempts'),
        'auxiliary_http_attempts_excluded':row.get('auxiliary_http_attempts')}
    if any(k not in row or row[k]is None for k in keys):
        return dict(result,status='MISSING_EVIDENCE')
    if any(type(row[k])is not bool for k in keys[:4])or not valid_ids \
            or len(ids)!=count or type(row['actor_http_attempts'])is not int \
            or row['actor_http_attempts']<count:
        return dict(result,status='INVALID_COUNT_EVIDENCE')
    if row['formal']is not True or row['fixture']is not False:
        return dict(result,status='NOT_FORMAL_ACTOR_EVIDENCE')
    if not row['collection_complete']:return dict(result,status='MISSING_EVIDENCE')
    if not row['original_verifier_passed']:return dict(result,status='TASK_FAILED')
    return dict(result,status='QUALIFIED'if count>=THRESHOLD else'SUCCESS_BELOW_THRESHOLD',
        qualified=count>=THRESHOLD)


def _formal_attempt(root,case_id,arm,model,model_version):
    admission=json.loads((root/'admission.json').read_text())
    lock=json.loads((root/'experiment.lock.json').read_text())
    if admission['case_id']!=case_id or admission.get('admission_status')!='ADMITTED' \
            or lock.get('admission_sha256')!=file_digest(root/'admission.json'):
        raise ValueError('long reference attempt is not this frozen formal case')
    report_path=root/'reports/results.json';report=json.loads(report_path.read_text())
    if report.get('fixture_scores_included')is not False or report.get('case_id')!=case_id \
            or report.get('contract_sha256')!=admission['contract_sha256']:
        raise ValueError('long qualification report provenance differs')
    rows=[r for r in report['rows']if r['variant_id']==arm]
    pair=json.loads((root/'pair-result.json').read_text())
    sources=[r for r in pair['arms']if r['arm']==arm]
    if len(rows)!=1 or len(sources)!=1:raise ValueError('exactly one reference arm required')
    source=sources[0];collection=source['collection'];rp=Path(source['result_path'])
    if file_digest(rp)!=source['result_sha256']:raise ValueError('original trial changed')
    raw=json.loads(rp.read_text());reward=(raw.get('verifier_result')or{}).get('rewards',{}).get('reward')
    reported=rows[0].get('native_reward')
    success=reward==1 if type(reward)in (int,float)and reported==reward else None
    campaign_proof=admission['campaign'];cp=Path(campaign_proof['path'])
    if file_digest(cp)!=campaign_proof['sha256']:raise ValueError('frozen model campaign changed')
    campaign=json.loads(cp.read_text())
    if campaign['model']!=model or campaign['model_version']!=model_version:
        raise ValueError('reference model differs from fixed qualification configuration')
    ids=collection.get('completed_unique_actor_agent_call_ids')
    if isinstance(ids,list):
        requests=json.loads(Path(campaign['ledger']).read_text())['requests']
        episode='fixed35-formal:'+root.name+':'+case_id
        if any(requests.get(i,{}).get('status')!='settled'or requests[i].get('arm')!=arm
                or requests[i].get('episode')!=episode for i in ids):
            raise ValueError('qualification call does not have this settled actor identity')
        if not set(ids)<=set(collection['request_ids']):raise ValueError('counted ID not in transport evidence')
    observed={'formal':True,'fixture':collection.get('fixture_control'),
        'collection_complete':collection.get('collection_complete'),
        'original_verifier_passed':success,'completed_actor_request_ids':ids,
        'actor_http_attempts':collection.get('actor_http_attempts'),
        'auxiliary_http_attempts':collection.get('auxiliary_http_attempts'),
        'tool_attempts':sum(t['attempts']for t in collection['tools'].values())}
    return dict(qualify_attempt(observed),run_root=str(root),arm=arm,
        original_reward=reward,original_result_sha256=file_digest(rp),
        report_sha256=file_digest(report_path),completed_actor_request_ids=ids,
        evaluator_commit=admission['evaluator_commit'])


def qualification_table(design_path,manifest_path,output):
    design=read_design(design_path);manifest=json.loads(manifest_path.read_text())
    if manifest.get('version')!=VERSION or manifest.get('reference_variant')not in {'pi-native','pi-memweave'}:
        raise ValueError('fixed qualification profile required')
    declared=manifest.get('cases')
    if not isinstance(declared,list)or len(declared)!=5 or {c.get('case_id')for c in declared}!=set(CASES):
        raise ValueError('all five distinct long candidates must remain visible')
    selected={c['pack_case_id']:c for c in design['selection']['cases']};rows=[]
    for entry in declared:
        case=selected[entry['case_id']];roots=entry.get('formal_runs')
        if not isinstance(roots,list)or any(not isinstance(r,str)or not r for r in roots)or len(roots)!=len(set(roots)):
            raise ValueError('explicit unique formal attempt roots required')
        attempts=[_formal_attempt(Path(r),entry['case_id'],manifest['reference_variant'],
            manifest['model'],manifest['model_version'])for r in roots]
        rows.append({'case_id':entry['case_id'],'upstream_case_id':case['upstream_case_id'],
            'source_revision':case['source_revision'],'formal_attempts':attempts,
            'qualified':any(a['qualified']for a in attempts),
            'status':'NOT_RUN'if not attempts else'QUALIFIED'if any(a['qualified']for a in attempts)else'NOT_YET_QUALIFIED',
            'historical_external_proofs':[p for p in design['selection']['historical_call_proofs']
                if p['task']==case['upstream_case_id'].rsplit('/',1)[-1]]})
    result={'version':VERSION,'reference_variant':manifest['reference_variant'],'model':manifest['model'],
        'model_version':manifest['model_version'],'required_distinct_cases':5,
        'qualified_distinct_cases':sum(r['qualified']for r in rows),'cases':rows,
        'counting_rule':'One successful original-verifier formal reference episode with >=1000 deduplicated completed real actor request IDs; never add stages, tools, auxiliary calls, mocks or separate attempts.',
        'below_threshold_policy':'A faster successful task remains successful; only the separate long-call qualification is unmet. No padding.',
        'manifest_sha256':file_digest(manifest_path),'approved_design_sha256':file_digest(design_path)}
    atomic_json(output,result,immutable=True)
    return {'output':str(output),'qualified_distinct_cases':result['qualified_distinct_cases'],'required':5,'paid_requests':0}
