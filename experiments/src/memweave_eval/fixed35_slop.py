"""Pinned Slop checkpoint tasks and official, host-only post-run evaluation."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import toml

from .storage import atomic_json, file_digest

PROBLEMS={'circuit_eval':8,'database_migration':5,'trajectory_api':5}


def slop_task(case,prompts:Path,output:Path,*,base_image,snapshot_excludes):
    name=case['upstream_case_id'];count=PROBLEMS[name]
    if not re.fullmatch(r'[a-z0-9._:/@-]+',base_image):raise ValueError('invalid frozen Slop image reference')
    files=[prompts/f'part_{i}.md'for i in range(1,count+1)]
    if not all(p.is_file()for p in files):raise ValueError('official rendered checkpoint missing')
    if any('%%%ENTRYPOINT:'in p.read_text()for p in files):raise ValueError('unrendered official prompt')
    task=output/case['pack_case_id'];(task/'environment').mkdir(parents=True,exist_ok=False)
    (task/'environment/Dockerfile').write_text('FROM '+base_image+'\nUSER root\nWORKDIR /workspace\nUSER 1000:1000\n')
    steps=[]
    for i,source in enumerate(files,1):
        stage=f'checkpoint_{i}';folder=task/'steps'/stage;folder.mkdir(parents=True)
        shutil.copyfile(source,folder/'instruction.md')
        steps.append({'name':stage,'artifacts':[{'source':'/workspace','destination':'submission',
            'exclude':sorted(snapshot_excludes)}]})
    config={'schema_version':'1.4','multi_step_reward_strategy':'final',
        'metadata':{'category':'software','derived_adapter':'fixed35-slop-pi-v1','source_revision':case['source_revision']},
        'agent':{'timeout_sec':1800},'environment':{'build_timeout_sec':600,'cpus':2,'memory_mb':8192,'storage_mb':20480},
        'verifier':{'timeout_sec':30},'steps':steps}
    (task/'task.toml').write_text(toml.dumps(config));(task/'tests').mkdir()
    (task/'tests/test.sh').write_text('exit 1 # official host Slop evaluator required; never a fabricated reward\n')
    return {'case_id':case['pack_case_id'],'problem':name,'task_path':str(task),
        'stages':[s['name']for s in steps],'prompt_sha256':{p.name:file_digest(p)for p in files},
        'public_inputs_only':True,'original_scoring':'pinned official eval-snapshot for every checkpoint',
        'verifier_resource_policy':'same2 CPU/8192 MiB caps on owned Docker SDK/CLI controller; actual HostConfig verified; upstream tests untouched; owned-run watchdog',
        'actor_resources':config['environment'],'total_actor_seconds':1800,
        'model_visible_adaptations':['full native Pi interface','persistent Session and workspace across checkpoints',
            'common cumulative case time cap; official rendered prompt bytes unchanged']}


def checkpoint_outcome(report):
    if not isinstance(report,dict):return {'score':None,'status':'MISSING_EVIDENCE','reason':'official evaluation report missing'}
    submission=report.get('submission_contract')
    if isinstance(submission,dict)and submission.get('handoff_complete')is True and isinstance(submission.get('missing_required_files'),list)and submission['missing_required_files']and all(isinstance(p,str)and p for p in submission['missing_required_files']):
        return {'score':0,'partial_score':None,'status':'SCORED','reason':'required submitted file absent',
            'original_all_reported_tests_score':0,
            'missing_required_files':submission['missing_required_files'],'passed':None,'total':None,
            'official_test_execution':'not started because the source submission violates the native required-file contract'}
    required=('infrastructure_failure','pytest_exit_code','pytest_collected','pass_counts','total_counts')
    if any(k not in report for k in required):return {'score':None,'status':'MISSING_EVIDENCE','reason':'official report field missing'}
    if type(report['infrastructure_failure'])is not bool:return {'score':None,'status':'MISSING_EVIDENCE','reason':'invalid infrastructure flag'}
    if report['infrastructure_failure']or type(report['pytest_exit_code'])is not int or report['pytest_exit_code']not in (0,1):
        return {'score':None,'status':'REPAIR_REQUIRED','reason':'official verifier infrastructure failure'}
    passed,total=report['pass_counts'],report['total_counts']
    if not isinstance(passed,dict)or not isinstance(total,dict)or set(passed)!=set(total)or not total:
        return {'score':None,'status':'MISSING_EVIDENCE','reason':'official test group counts missing'}
    if any(type(passed[k])is not int or type(total[k])is not int or not 0<=passed[k]<=total[k]for k in total):
        return {'score':None,'status':'INVALID','reason':'invalid official pass/total counts'}
    s,n=sum(passed.values()),sum(total.values())
    if n==0 or type(report['pytest_collected'])is not int or report['pytest_collected']<=0:
        return {'score':None,'status':'REPAIR_REQUIRED','reason':'no actual tests collected'}
    skipped=[]
    if report.get('problem_name')=='database_migration'and report.get('checkpoint_name')in {'checkpoint_3','checkpoint_4','checkpoint_5'}:
        groups=report.get('tests')
        if not isinstance(groups,dict):return {'score':None,'status':'MISSING_EVIDENCE','reason':'per-test skip evidence required for fixed applicable-test contract'}
        for group,counts in groups.items():
            for identity in counts.get('skipped',[]):
                if group=='checkpoint_1-Regression'and identity=='test_foreign_keys_disabled_during_drop_column':
                    skipped.append((group,identity))
        if len(skipped)>1:return {'score':None,'status':'INVALID','reason':'duplicate fixed skipped test'}
    effective=n-len(skipped)
    if effective<s or effective<=0:return {'score':None,'status':'INVALID','reason':'inconsistent applicable test denominator'}
    return {'score':100*int(s==effective and report['pytest_exit_code']==0),'partial_score':100*s/effective,
        'passed':s,'total':effective,'collected':report['pytest_collected'],'status':'SCORED',
        'original_reported_passed':s,'original_reported_total':n,'original_reported_partial_score':100*s/n,
        'original_all_reported_tests_score':100*int(s==n and report['pytest_exit_code']==0),
        'source_conditional_skips':skipped,'mapping_version':'fixed35-slop-applicable-tests-v2',
        'score_channel':'derived strict all applicable checkpoints; original reported counts retained unchanged',
        'raw_formula':'all original checkpoint and applicable regression groups AND; only pinned checkpoint-1/2-only test excluded at checkpoints3-5'}


def sequential_outcome(reports,expected_stages):
    if len(set(expected_stages))!=len(expected_stages)or not expected_stages:raise ValueError('unique nonempty checkpoint sequence required')
    if set(reports)-set(expected_stages):raise ValueError('unexpected checkpoint result')
    points={stage:checkpoint_outcome(reports.get(stage))for stage in expected_stages}
    complete=all(p['status']=='SCORED'for p in points.values())
    # A known failure proves the whole strict outcome failed even if another
    # checkpoint is missing, but collection is still rejected until repaired.
    failed=any(p.get('score')==0 for p in points.values())
    original=[p.get('original_all_reported_tests_score')for p in points.values()]
    return {'score':0 if failed else 100 if complete else None,
        'partial_score':sum(p['partial_score']for p in points.values())/len(points)if complete and all(p['partial_score']is not None for p in points.values())else None,
        'status':'SCORED'if complete else'REPAIR_REQUIRED','collection_complete':complete,
        'checkpoints':points,'original_all_reported_tests_AND':0 if 0 in original else 100 if all(v==100 for v in original)else None,
        'aggregation':'derived strict AND over every fixed applicable checkpoint; partial is equal-checkpoint mean; original counts separate'}


def score_channels(outcome):
    """Never relabel the derived applicable-test success as the source result."""
    if not isinstance(outcome,dict):raise TypeError('Slop score channels require an outcome object')
    result={}
    for channel,field,formula in [
        ('original_strict','original_all_reported_tests_AND','AND of strict all-reported-test verdicts at every source checkpoint'),
        ('derived_applicable','score','AND of all applicable-test verdicts at every source checkpoint; fixed conditional skip is separate')]:
        value=outcome.get(field)
        if value is not None and(type(value)not in (int,float)or value not in (0,100)):
            raise ValueError('invalid Slop binary score in '+field)
        result[channel]={'score':value,'status':'SCORED'if value is not None else'MISSING_EVIDENCE',
            'source_field':field,'raw_formula':formula,'score_formula':'identity on the 0–100 binary scale',
            'reason':None if value is not None else'Explicit source score absent; no fallback to the other channel'}
    complete=outcome.get('collection_complete')
    result['collection_complete']=complete if type(complete)is bool else None
    return result


def evaluate_trial(trial:Path,*,problem,stages,runner,environment,sources,output:Path,deadline,env,expected_image,cpus=2,memory_mb=8192,fixture_only=False):
    if problem not in PROBLEMS or stages!=[f'checkpoint_{i}'for i in range(1,PROBLEMS[problem]+1)]:
        raise ValueError('Slop fixed checkpoint sequence mismatch')
    if problem=='database_migration'and file_digest(Path(sources)/problem/'tests/test_checkpoint_1.py')!='59568d555215b985f90da89e3a9d072565c6fd1fc73c826a214b8207cc148f9c':
        raise ValueError('fixed conditional skip source changed; do not infer applicability from a new verifier')
    output.mkdir(parents=True,exist_ok=False);reports={};evidence={}
    for index,stage in enumerate(stages,1):
        artifacts=trial/'steps'/stage/'artifacts'
        snapshot=artifacts/'submission'
        manifest=artifacts/'manifest.json'
        try:receipt=json.loads(manifest.read_text())if manifest.is_file()else None
        except (OSError,ValueError,UnicodeError):receipt=None
        if not isinstance(receipt,list)or not any(isinstance(r,dict)and r.get('source')=='/workspace'and
                r.get('destination')=='artifacts/submission'and r.get('status')in {'ok','empty'}for r in receipt):
            reports[stage]=None;evidence[stage]={'status':'HANDOFF_RECEIPT_MISSING_OR_FAILED'};continue
        if not snapshot.is_dir():
            reports[stage]=None;evidence[stage]={'status':'MISSING_SUBMISSION_SNAPSHOT'};continue
        for path in snapshot.rglob('*'):
            if path.is_symlink()and not path.resolve().is_relative_to(snapshot.resolve()):
                raise ValueError('submission link escapes the isolated snapshot')
        entry={'circuit_eval':'circopt.py','database_migration':'migration_tool.py','trajectory_api':'trajectory_api.py'}[problem]
        missing=[name for name in ('requirements.txt',entry)if not (snapshot/name).is_file()]
        if missing:
            reports[stage]={'problem_name':problem,'checkpoint_name':stage,'submission_contract':{
                'handoff_complete':True,'missing_required_files':missing,'handoff_manifest_sha256':file_digest(manifest)}}
            receipt_path=output/(stage+'-submission-contract.json')
            atomic_json(receipt_path,reports[stage],immutable=True)
            evidence[stage]={'status':'KNOWN_SUBMISSION_CONTRACT_FAILURE','manifest_path':str(manifest),
                'manifest_sha256':file_digest(manifest),'report':str(receipt_path),'sha256':file_digest(receipt_path)};continue
        remaining=deadline-time.time()
        if remaining<=30:
            evidence[stage]={'status':'GLOBAL_VERIFIER_DEADLINE'};reports[stage]=None;continue
        target=output/stage;log=output/(stage+'.log')
        run_id='slopverify-'+uuid4().hex
        stop=min(deadline-15,time.time()+900)
        watch_root=output/(stage+'-control');watch_root.mkdir()
        watch=subprocess.Popen([sys.executable,'-m','memweave_eval.deadline_watchdog',str(watch_root),run_id,str(stop),str(stop)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        call=[str(Path(runner).with_name('python')),str(Path(__file__).with_name('slop_eval_entry.py')),'--quiet','eval-snapshot',str(snapshot),'-o',str(target),'-p',problem,'-c',str(index),'-e',str(environment),'--json']
        operation_env=dict(env,SCBENCH_PROBLEMS_PATH=str(sources),MEMWEAVE_SLOP_VERIFIER_RUN=run_id,
            MEMWEAVE_SLOP_VERIFIER_CPUS=str(cpus),MEMWEAVE_SLOP_VERIFIER_MEMORY_MB=str(memory_mb),
            MEMWEAVE_SLOP_VERIFIER_IMAGE=expected_image,MEMWEAVE_SLOP_VERIFIER_DEADLINE=str(stop),
            MEMWEAVE_SLOP_VERIFIER_AUDIT=str(watch_root/'containers.jsonl'))
        try:
            with log.open('w')as stream:
                process=subprocess.Popen(call,stdout=stream,stderr=subprocess.STDOUT,env=operation_env,cwd=output,start_new_session=True)
                try:exit_code=process.wait(timeout=max(1,stop-time.time()+5))
                except subprocess.TimeoutExpired:
                    import os
                    import signal
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    exit_code=None
        finally:
            query=['docker','ps','--filter','label=org.memweave.eval.run='+run_id,'--format','{{.ID}}']
            result=subprocess.run(query,env=env,capture_output=True,text=True,timeout=15,check=False)
            if result.returncode==0:
                for identity in result.stdout.split():subprocess.run(['docker','kill',identity],env=env,capture_output=True,timeout=15,check=False)
                check=subprocess.run(query,env=env,capture_output=True,text=True,timeout=15,check=False)
                if check.returncode==0 and not check.stdout.strip():
                    (watch_root/'.watchdog-stop').touch();watch.wait(timeout=20)
                    atomic_json(watch_root/'cleanup.json',{'confirmed_stopped':True,'run_id':run_id},immutable=True)
        report=target/'evaluation.json'
        reports[stage]=json.loads(report.read_text())if report.exists()else None
        evidence[stage]={'exit_code':exit_code,'report':str(report),'sha256':file_digest(report)if report.exists()else None}
    result=dict(sequential_outcome(reports,stages),problem=problem,source_evidence=evidence,
        verifier='original pinned Slop eval-snapshot, no LLM judge; applicable strict score and original reported counts separate',fixture_scores_included=fixture_only)
    atomic_json(output/'official-outcome.json',result,immutable=True)
    return result


def score_pair(root:Path,output:Path,*,fixture_only=False):
    from concurrent.futures import ThreadPoolExecutor

    from .fixed35_campaign import trusted_environment
    from .fixed35_campaign_config import campaign_config
    admission=json.loads((root/'admission.json').read_text());pair=json.loads((root/'pair-result.json').read_text())
    campaign=campaign_config(admission);deadline=campaign['container_cutoff']
    config=admission['slop_verifier']
    if file_digest(Path(config['environment']))!=config['environment_sha256']:raise ValueError('frozen Slop verifier config changed')
    for path,sha in [(config['sources'],config['problem_revision']),(config['runner_source'],config['runner_revision'])]:
        if subprocess.check_output(['git','-C',path,'rev-parse','HEAD'],text=True).strip()!=sha or subprocess.check_output(['git','-C',path,'status','--porcelain'],text=True).strip():
            raise ValueError('Slop official source not clean and pinned')
    env=trusted_environment(Path(admission['code_path']))
    env.update(SCBENCH_HOME=str(output.parent/'slop-home'),TMPDIR=str(output.parent/'slop-tmp'))
    Path(env['TMPDIR']).mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=False)
    def score(arm):
        outcome=next(x for x in pair['arms']if x['arm']==arm)
        return arm,evaluate_trial(Path(outcome['result_path']).parent,problem=config['problem'],stages=config['stages'],
            runner=config['runner'],environment=config['environment'],sources=config['sources'],output=output/arm,
            deadline=deadline,env=env,expected_image=config['image_id'],fixture_only=fixture_only)
    with ThreadPoolExecutor(max_workers=2)as pool:arms=dict(pool.map(score,['pi-native','pi-memweave']))
    record={'case_id':admission['case_id'],'arms':arms,'fixture_scores_included':fixture_only,
        'version':'fixed35-slop-applicable-20261102-v2','admission_sha256':file_digest(root/'admission.json'),
        'campaign_sha256':admission['campaign']['sha256'],'verifier_deadline_unix':deadline,
        'deadline_source':'hash_bound_campaign.container_cutoff'}
    atomic_json(output/'pair-official-outcomes.json',record,immutable=True)
    return output/'pair-official-outcomes.json'
