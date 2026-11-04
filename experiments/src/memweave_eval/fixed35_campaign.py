"""Fixed-case admissions use the existing Harbor/Pi runner and its quota guard."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .fixed35_campaign_config import campaign_config, verify_account
from .fixed35_collection import collect_episode
from .fixed35_execution import BASE, job_config
from .runner import execute_harbor, trial_results, verify_package
from .storage import atomic_json, file_digest
from .suites import task_digest


def trusted_environment(code: Path):
    env={k:v for k,v in os.environ.items()if k in {'PATH','HOME','LANG','LC_ALL','TERM','TMPDIR'}}
    env.update(DOCKER_HOST='unix:///Users/godice/.colima/memweave-eval/docker.sock',
        DOCKER_CONFIG=str(BASE/'tools/docker-config'),PYTHONPATH=str(code/'experiments/src')+
        ':/tmp/memweave-35-20261102/deps',HARBOR_TELEMETRY='0',DO_NOT_TRACK='1')
    env['PATH']=str(BASE/'tools/native/bin')+':'+str(BASE/'tools/bin')+':'+env['PATH']
    return env


def validate_paid_canary(record,ledger=None):
    if record.get('admission_status')!='ADMITTED':raise ValueError('case is not admitted for real execution')
    proof=record.get('paid_canary')
    if not isinstance(proof,dict)or not {'path','sha256'}<=set(proof):raise ValueError('real canary evidence is required')
    path=Path(proof['path'])
    if file_digest(path)!=proof['sha256']:raise ValueError('real canary evidence changed')
    canary=json.loads(path.read_text())
    if canary.get('passed')is not True or canary.get('runtime_plan_sha256')!=record['runtime_plan_sha256']or canary.get('evaluator_commit')!=record.get('evaluator_commit'):
        raise ValueError('canary did not verify this frozen evaluator and runtime plan')
    if set(canary.get('per_arm',{}))!={'pi-native','pi-memweave'}:raise ValueError('both canary variants required')
    account=json.loads((ledger or BASE/'budgets/fixed35-20261102/quota.json').read_text())['requests']
    identities=[]
    for arm,evidence in canary['per_arm'].items():
        rule=evidence.get('rule_integrity')or{}
        if arm=='pi-memweave'and(rule.get('value')!=1 or rule.get('coverage')!=1):
            raise ValueError('real plugin canary must prove complete frozen Rule delivery')
        ids=evidence.get('actor_request_ids')
        if not isinstance(ids,list)or len(ids)!=1 or type(evidence.get('guard_negative_upstream_requests'))is not int or evidence['guard_negative_upstream_requests']!=0:
            raise ValueError('canary must prove one actual actor request and zero negative-test upstream dispatch')
        ids=ids+evidence.get('auxiliary_request_ids',[])
        if record.get('family')=='state'and len(ids)<2:raise ValueError('STATE host auxiliary canary missing')
        for identity in ids:
            entry=account.get(identity,{})
            if entry.get('status')!='settled'or entry.get('arm')!='preflight':raise ValueError('canary request is not settled in this campaign preflight ledger')
        identities.extend(ids)
    if len(identities)!=len(set(identities)):raise ValueError('canary variants reused request identities')


def validate_case_design(contract):
    if not isinstance(contract,dict):raise TypeError('case contract must be an object')
    matrix=contract.get('metric_matrix')
    if 'fixture_only'in contract and(type(contract['fixture_only'])is not bool or contract['fixture_only']):
        raise ValueError('fixture scoring contracts cannot enter a real admission')
    if 'not_formal_admission'in contract and type(contract['not_formal_admission'])is not bool:
        raise ValueError('component admission marker must be boolean')
    if contract.get('not_formal_admission')is True or contract.get('contract_status')in {'DRAFT_NOT_ADMITTED','SOURCE_COMPONENT_NOT_ADMITTED'}or not isinstance(matrix,list)or not matrix:
        raise ValueError('source draft or empty case opportunities cannot be admitted')
    if any(not isinstance(m,dict)or not isinstance(m.get('metric_id'),str)or not m['metric_id']for m in matrix):
        raise ValueError('case metric identities must be explicit strings')
    if len({m.get('metric_id')for m in matrix})!=len(matrix):
        raise ValueError('case design repeats a metric')
    from .normalized_scores import catalogue
    if {m.get('metric_id')for m in matrix}!={m['id']for m in catalogue()['metrics']}:
        raise ValueError('case design must cover the complete current metric registry')
    for metric in matrix:
        if metric.get('applicability_version')!='fixed35-research-assignments-20261102-v2':
            raise ValueError('legacy research-as-NA matrix must be migrated before admission')
        if metric.get('design_status')not in {'PLANNED','DESIGN_NA'}:
            raise ValueError('unresolved case opportunities cannot be admitted')
        if metric['design_status']=='DESIGN_NA'and(not isinstance(metric.get('reason'),str)or not metric['reason'].strip()):
            raise ValueError('structural design NA requires an explicit frozen reason')
        if metric['design_status']=='PLANNED':
            opportunities=metric.get('opportunity_ids')
            if not isinstance(opportunities,list)or not opportunities or any(
                    not isinstance(i,str)or not i.strip()for i in opportunities)or len(opportunities)!=len(set(opportunities)):
                raise ValueError('planned metric requires explicit unique frozen opportunities')


def verify_evaluator_checkout(record):
    """Read-only provenance gate before any authority or actor can be started."""
    identity=record.get('evaluator_commit')
    if not isinstance(identity,str)or not re.fullmatch(r'[a-f0-9]{40}',identity):
        raise ValueError('full frozen evaluator commit required')
    root=Path(record['code_path']).resolve()
    if Path(__file__).resolve()!=(root/'experiments/src/memweave_eval/fixed35_campaign.py').resolve():
        raise ValueError('loaded evaluator does not belong to the frozen code path')
    try:
        actual_root=subprocess.check_output(['git','-C',str(root),'rev-parse','--show-toplevel'],text=True,stderr=subprocess.PIPE).strip()
        head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,stderr=subprocess.PIPE).strip()
        dirty=subprocess.check_output(['git','--no-optional-locks','-C',str(root),'status','--porcelain','--untracked-files=all'],text=True,stderr=subprocess.PIPE)
    except (OSError,subprocess.SubprocessError):
        raise ValueError('evaluator checkout could not be verified')from None
    if Path(actual_root).resolve()!=root or head!=identity or dirty.strip():
        raise ValueError('evaluator checkout differs from the clean frozen canary revision')


def validate_adapter_observers(record,contract):
    if contract.get('adapter_kind')=='warranty-source-v1'and record.get('agent_import')!='memweave_eval.warranty_pi:WarrantyPi':
        raise ValueError('warranty admission requires its read-only sidecar evidence wrapper; final files alone do not prove empty history')


def validate_episode_policy(record):
    declared=tomllib.loads((Path(record['task_path'])/'task.toml').read_text()).get('agent',{}).get('timeout_sec')
    seconds=record['seconds'];budget=record['episode_budget']
    policy=record.get('time_policy','case-cap')
    if policy=='source-per-stage':
        from .fixed35_execution import source_stage_budgets
        declared=sum(source_stage_budgets(Path(record['task_path'])))
    if policy not in {'case-cap','source-per-stage'}or any(type(value)not in (int,float)or not math.isfinite(value)for value in (declared,seconds,budget)) \
            or not 0<seconds<=declared or policy=='source-per-stage'and seconds!=declared or budget<.31:
        raise ValueError('episode must fit its frozen task agent timeout and bounded budget')


def validate_admission(record):
    for key in ('case_id','benchmark','task_path','task_sha256','runtime_plan','runtime_plan_sha256',
                'code_path','contract_path','contract_sha256','resources','seconds','episode_budget',
                'preflight_evidence'):
        if key not in record:
            raise ValueError('missing admission field '+key)
    verify_evaluator_checkout(record)
    campaign=campaign_config(record)
    validate_paid_canary(record,Path(campaign['ledger']))
    if not record['preflight_evidence']:
        raise ValueError('no preflight evidence')
    for source in record['preflight_evidence']:
        if not Path(source).is_file():
            raise ValueError('preflight evidence absent')
    if task_digest(Path(record['task_path']))!=record['task_sha256']:
        raise ValueError('admitted task changed')
    for key in ('runtime_plan','contract_path'):
        expected=record['runtime_plan_sha256' if key=='runtime_plan' else 'contract_sha256']
        if file_digest(Path(record[key]))!=expected:
            raise ValueError('admitted evaluator input changed')
    contract=json.loads(Path(record['contract_path']).read_text())
    validate_adapter_observers(record,contract);validate_case_design(contract)
    validate_episode_policy(record)
    allowed={'state_source_path','state_selector','evaluation_host_ledger','state_evaluator_output',
        'evaluation_judge_deadline','evaluation_state_overlay'}
    if set(record.get('agent_options',{}))-allowed:
        raise ValueError('case options may not replace frozen model, guard, output, time, or variant policy')


def run_pair(admission: Path, root: Path):
    from .fixed35_report import VERSION
    record=json.loads(admission.read_text());validate_admission(record)
    from .fixed35_schedule import pair_policy
    policy=pair_policy(record)
    if time.time()>=policy['latest_pair_start_unix']:
        raise TimeoutError('insufficient time for both complete arm budgets and verifier reserve')
    root.mkdir(parents=True,exist_ok=False)
    atomic_json(root/'admission.json',record,immutable=True)
    atomic_json(root/'experiment.lock.json',{'schema_version':3,'protocol':'fixed35',
        'admission_sha256':file_digest(root/'admission.json'),'evaluator_version':VERSION},immutable=True)
    run_id=root.name
    campaign=campaign_config(record);verify_account(campaign)
    ledger=Path(campaign['ledger']);model_cutoff=campaign['model_cutoff']
    container_cutoff=campaign['container_cutoff']
    from .fixed35_execution import PACKAGE, PACKAGE_SHA256, SUBJECT_COMMIT
    verify_package(PACKAGE,PACKAGE_SHA256,SUBJECT_COMMIT)
    env=trusted_environment(Path(record['code_path']))
    from .quota_authority import add_channel, start_authority
    authority=start_authority(Path(campaign['authority_root']),ledger,env)
    atomic_json(root/'quota-authority.json',authority,immutable=True)
    parallel=policy['parallel_arms']
    atomic_json(root/'resource-policy.json',policy,immutable=True)
    atomic_json(root/'run.json',{'run_id':run_id,'case_id':record['case_id'],'started_at':datetime.now(UTC).isoformat(),
        'status':'RUNNING','parallel_arms':parallel,'ledger':str(ledger),'arms':{}},immutable=True)
    watch=subprocess.Popen([sys.executable,'-m','memweave_eval.deadline_watchdog',str(root),run_id,
        str(model_cutoff),str(container_cutoff)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    sleep_guard=subprocess.Popen(['caffeinate','-i','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def arm_run(arm):
        cfg=job_config(root=root,task=Path(record['task_path']),case_id=record['case_id'],arm=arm,
            run_id=run_id,plan=Path(record['runtime_plan']),deadline=model_cutoff,resources=record['resources'],
            seconds=record['seconds'],host_scored=record.get('host_scored',False),
            episode_budget=record['episode_budget'],task_config=record.get('task_config'),
            time_policy=record.get('time_policy','case-cap'))
        cfg['agents'][0]['kwargs']['evaluation_run_id']='fixed35-formal:'+cfg['agents'][0]['kwargs']['evaluation_run_id']
        episode=cfg['agents'][0]['kwargs']['evaluation_run_id']
        channel=add_channel(authority,arm=arm,episode=episode,max_output=8192,deadline=model_cutoff,
            episode_budget=record['episode_budget'])
        overlay=root/(arm+'-platform.yaml')
        overlay.write_text('services:\n  main:\n    platform: '+record.get('platform','linux/amd64')+
            '\n    labels:\n      org.memweave.eval.run: '+run_id+
            '\n    volumes:\n      - '+channel['host_path']+':/opt/memweave-eval-control:rw\n')
        cfg['environment']['extra_docker_compose']=[str(overlay)]
        cfg['agents'][0]['kwargs'].update(record.get('agent_options',{}))
        cfg['agents'][0]['kwargs'].update(evaluation_quota_backend='ipc',
            evaluation_quota_channel='/opt/memweave-eval-control')
        if record.get('family')=='state':
            aux={}
            for role in ('user_simulator','official_judge'):
                scope=add_channel(authority,arm=arm,episode=episode+(':judge'if role=='official_judge'else''),max_output=8192,
                    deadline=campaign['judge_cutoff'] if role=='official_judge'else model_cutoff,
                    episode_budget=.4 if role=='official_judge'else record['episode_budget'],role=role)
                aux[role]=scope['host_path']
            cfg['agents'][0]['kwargs']['evaluation_aux_quota_channels']=aux
        if parallel:
            cfg['agents'][0]['kwargs']['evaluation_pair_barrier']=str(root/'start-barrier')
        if record.get('agent_import'):
            cfg['agents'][0]['import_path']=record['agent_import']
        code=execute_harbor(cfg,root,env,time.monotonic()+max(1,container_cutoff-time.time()),20.)
        results=trial_results(root/'harbor'/cfg['job_name'])
        if len(results)!=1:
            raise RuntimeError('expected exactly one actual trial')
        path,result=next(iter(results.values()))
        aux=[]
        if record['family']=='state':
            aux=[Path(record['agent_options']['state_evaluator_output'])/path.parent.name]
        host_score=None
        if record['family']=='state':
            from .state_postscore import score_state_trial
            try:host_score=score_state_trial(cfg['agents'][0]['kwargs'],path.parent)
            except Exception as error:  # noqa: BLE001 -- preserve actor evidence and all quota traces if post-judge fails.
                host_score={'status':'POST_JUDGE_FAILED','error_class':type(error).__name__,'requires_repair':True}
        collection=collect_episode(path.parent,arm=arm,ledger=ledger,auxiliary_roots=aux,expected_episode=episode)
        outcome={'arm':arm,'exit_code':code,'result_path':str(path),'result_sha256':file_digest(path),
            'exception':result.get('exception_info'),'verifier':result.get('verifier_result'),'host_official_score':host_score,
            'collection':collection,'finished_at':datetime.now(UTC).isoformat()}
        atomic_json(root/(arm+'-collected.json'),outcome,immutable=True)
        print(json.dumps({'case_id':record['case_id'],'arm':arm,'status':'TERMINAL',
            'requests':collection['requests'],'estimated_usd':collection['estimated_usd'],
            'exception':outcome['exception']},ensure_ascii=False),flush=True)
        return outcome
    try:
        if parallel:
            with ThreadPoolExecutor(max_workers=2)as pool:
                arms=list(pool.map(arm_run,['pi-native','pi-memweave']))
        else:
            arms=[arm_run(a)for a in policy['sequential_order']]
        arms.sort(key=lambda x:x['arm']!='pi-native')
        atomic_json(root/'pair-result.json',{'case_id':record['case_id'],'arms':arms,'finished_at':datetime.now(UTC).isoformat()},immutable=True)
        from .fixed35_report import single_report
        official=None
        if record['family']=='slop':
            from .fixed35_slop import score_pair
            official=score_pair(root,root/'official-slop')
        report=single_report(root,official_outcomes=official)
        atomic_json(root/'run.json',{'status':'TERMINAL','case_id':record['case_id'],
            'run_id':run_id,'arms':arms,'report':report,'finished_at':datetime.now(UTC).isoformat()})
        return {'root':str(root),'case_id':record['case_id'],'arms':len(arms)}
    finally:
        check=subprocess.run(['docker','ps','--filter','label=org.memweave.eval.run='+run_id,
            '--format','{{.ID}}'],env=env,capture_output=True,text=True,timeout=15,check=False)
        if check.returncode==0 and not check.stdout.strip():
            (root/'.watchdog-stop').touch();watch.wait(timeout=20)
            atomic_json(root/'cleanup.json',{'confirmed_stopped':True,'at':datetime.now(UTC).isoformat()},immutable=True)
        sleep_guard.terminate();sleep_guard.wait(timeout=10)
