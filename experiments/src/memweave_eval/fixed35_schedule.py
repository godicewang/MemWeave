"""Resource/deadline admission for the existing case runner, not an agent workflow."""
from __future__ import annotations

import hashlib
import json
import time
import tomllib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .fixed35_campaign import run_pair, validate_admission
from .fixed35_execution import MODEL_CUTOFF
from .storage import atomic_json

CPU=11
MEMORY_MB=38000
CONTAINER_STOP=1793661732.


def pair_policy(record):
    task=tomllib.loads((Path(record['task_path'])/'task.toml').read_text())
    environment=task['environment'];resources=record['resources']
    if any(environment.get(k)!=resources[k]for k in ('cpus','memory_mb')):
        raise ValueError('advertised actor resources differ from actual task environment')
    verifier=task.get('verifier',{});ve=verifier.get('environment')or environment
    cpus=max(resources['cpus'],ve.get('cpus',resources['cpus']))
    memory=max(resources['memory_mb'],ve.get('memory_mb',resources['memory_mb']))
    if cpus>CPU or memory>MEMORY_MB:raise ValueError('one arm exceeds the safe local resource pool')
    parallel=2*cpus<=CPU and 2*memory<=MEMORY_MB
    stages=task.get('steps')or[{}]
    verify=sum(s.get('verifier',{}).get('timeout_sec',verifier.get('timeout_sec',3600))for s in stages)
    if record.get('family')=='slop':verify=900*len(stages)
    setup=120
    actor_span=(record['seconds']+setup)*(1 if parallel else 2)+(0 if parallel else verify)
    total_span=(record['seconds']+setup+verify)*(1 if parallel else 2)
    latest=min(MODEL_CUTOFF-actor_span,CONTAINER_STOP-total_span)
    first='pi-native'if int(hashlib.sha256(record['case_id'].encode()).hexdigest(),16)%2==0 else'pi-memweave'
    return {'parallel_arms':parallel,'reserved_cpus':cpus*(2 if parallel else 1),
        'reserved_memory_mb':memory*(2 if parallel else 1),'actor_seconds_per_arm':record['seconds'],
        'verifier_upper_bound_seconds_per_arm':verify,'setup_allowance_seconds_per_arm':setup,
        'latest_pair_start_unix':latest,'sequential_order':[first,'pi-native'if first=='pi-memweave'else'pi-memweave'],
        'pool':{'cpus':CPU,'memory_mb':MEMORY_MB},'selection':'frozen order with resource first-fit; no outcome-driven changes'}


def execute_schedule(plan:Path,output:Path,*,dry_run=True):
    frozen=json.loads(plan.read_text());cases=frozen['cases']
    if len(cases)!=35 or len({c['case_id']for c in cases})!=35:raise ValueError('35 unique frozen case entries required')
    output.mkdir(parents=True,exist_ok=False);pending=[];rows=[]
    for case in cases:
        if case['readiness']!='ADMITTED':
            rows.append({'case_id':case['case_id'],'status':'BLOCKED_PREFLIGHT','reason':case.get('reason')});continue
        record=json.loads(Path(case['admission_path']).read_text());validate_admission(record)
        if record['case_id']!=case['case_id']:raise ValueError('case admission identity mismatch')
        pending.append((case,record,pair_policy(record)))
    atomic_json(output/'frozen-plan.json',frozen,immutable=True)
    atomic_json(output/'resource-plan.json',[dict(case_id=c['case_id'],**p)for c,_,p in pending],immutable=True)
    if dry_run:return {'dry_run':True,'paid_requests':0,'admitted_cases':len(pending),'blocked_cases':len(rows)}
    active={};used_cpu=0;used_memory=0;paused=False
    with ThreadPoolExecutor(max_workers=8)as pool:
        while pending or active:
            for entry in list(pending):
                if paused:
                    pending.remove(entry);rows.append({'case_id':entry[0]['case_id'],'status':'NOT_RUN_HARNESS_PAUSED'});continue
                case,record,policy=entry
                if time.time()>policy['latest_pair_start_unix']:
                    pending.remove(entry);rows.append({'case_id':case['case_id'],'status':'NOT_RUN_INSUFFICIENT_EQUAL_TIME'});continue
                if used_cpu+policy['reserved_cpus']>CPU or used_memory+policy['reserved_memory_mb']>MEMORY_MB:continue
                pending.remove(entry);used_cpu+=policy['reserved_cpus'];used_memory+=policy['reserved_memory_mb']
                future=pool.submit(run_pair,Path(case['admission_path']),output/'cases'/case['case_id'])
                active[future]=(case,policy)
            atomic_json(output/'progress.json',{'rows':rows,'active':[c['case_id']for c,_ in active.values()],
                'reserved_cpus':used_cpu,'reserved_memory_mb':used_memory,'timestamp':time.time()})
            if not active:break
            done,_=wait(active,timeout=1,return_when=FIRST_COMPLETED)
            for future in done:
                case,policy=active.pop(future);used_cpu-=policy['reserved_cpus'];used_memory-=policy['reserved_memory_mb']
                try:result=future.result();row={'case_id':case['case_id'],'status':'TERMINAL','result':result}
                except Exception as error:  # noqa: BLE001 -- retain every runner failure and stop launching new cases.
                    paused=True;row={'case_id':case['case_id'],'status':'ERROR_REQUIRES_CLASSIFICATION','error_class':type(error).__name__,'reason':str(error)}
                rows.append(row)
    atomic_json(output/'schedule-result.json',{'rows':rows,'formal_result_rows':sum(r['status']=='TERMINAL'for r in rows)},immutable=True)
    return {'output':str(output),'cases':len(rows),'missing_cases':35-len(rows)}
