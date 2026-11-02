"""Harbor job construction for the fixed campaign; no alternate agent loop."""
from __future__ import annotations

import json
from pathlib import Path

from .storage import file_digest

SUBJECT_COMMIT='207d746babd80b2381f04688d8d576c73429af30'
PACKAGE_SHA256='5ed61de2eb9d8096cf063fb519c4b54c8f63b09cd518c00e4d228d1bed92f022'
BASE=Path('/Users/godice/.local/share/memweave-experiments')
PACKAGE=BASE/'artifacts/marathon-20261101/godice-memweave-0.1.0.tgz'
MODEL_CUTOFF=1793650812.0  # 2026-11-02T20:20:12Z; validated below by campaign config.


def can_pair(resources,available_cpu,available_memory_mb,reserve_memory_mb=2048):
    return (2*resources['cpus']<=available_cpu and
            2*resources['memory_mb']<=available_memory_mb-reserve_memory_mb)


def job_config(*,root:Path,task:Path,case_id,arm,run_id,plan:Path,deadline,
               seconds=1800,resources,prepare_only=False,canary=False,control=None,
               host_scored=False,episode_budget=.6,output_tokens=8192,concurrency=1,
               task_config=None):
    if arm not in {'pi-native','pi-memweave'}:
        raise ValueError('unknown paired arm')
    resources={k:resources[k]for k in ('cpus','memory_mb','storage_mb')if k in resources}
    if not all(type(v)is int and v>0 for v in resources.values())or not {'cpus','memory_mb'}<=set(resources):
        raise ValueError('positive integer CPU/memory resource limits required')
    name=case_id.lower()+'-'+arm+('-software' if prepare_only else '-canary' if canary else '')
    options={'version':'1.4.0','node_version':'24.22.0','variant':arm,
             'package_path':str(PACKAGE),'package_sha256':PACKAGE_SHA256,
             'auth_path':'' if prepare_only else str(Path.home()/'.local/share/memweave-dev/pi-agent/auth.json'),
             'protocol':'fixed35','thinking':'off','runtime_plan':str(plan),
             'runtime_plan_sha256':file_digest(plan),'prepare_only':prepare_only,
             'evaluation_deadline':deadline,'evaluation_output_tokens':128 if canary else output_tokens,
             'evaluation_quota_backend':'python','evaluation_content_evidence':True,
             'evaluation_case_id':case_id,'evaluation_task_ids':[task.name],
             'evaluation_task_configs':{task.name:task_config or {}},
             'evaluation_run_id':run_id+':'+case_id+(':canary' if canary else ''),
             'evaluation_progress_after_returns':0,'evaluation_canary':canary,
             'evaluation_request_limit':1 if canary else None,
             'evaluation_episode_budget':episode_budget,'evaluation_resources':resources,
             'evaluation_task_timeouts':{task.name:seconds}}
    if canary:
        options.update(evaluation_budget_arm='preflight',evaluation_role='preflight',
                       evaluation_run_id=run_id+':'+case_id+':'+arm+':canary')
    if not prepare_only:
        options['runtime_objects']=json.loads(plan.with_name('runtime-assets.lock.json').read_text())['objects']
    agent={'import_path':'memweave_eval.pi_agent:ExperimentPi','model_name':'deepseek/deepseek-flash',
           'resume_trajectory':True,'extra_allowed_hosts':['api.deepseek.com'],'kwargs':options,
           'override_setup_timeout_sec':1800,'override_timeout_sec':120 if canary else seconds}
    if control:agent={'name':control,'resume_trajectory':True}
    cfg={'job_name':name,'jobs_dir':str(root/'harbor'),'n_attempts':1,
         'n_concurrent_trials':concurrency,'quiet':True,'retry':{'max_retries':0},
         'environment':{'type':'docker','delete':True},'agents':[agent],
         'tasks':[{'path':str(task)}]}
    if prepare_only or canary or host_scored:
        cfg['verifier']={'disable':True}
    return cfg
