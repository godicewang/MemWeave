"""Versioned, explicit TB01 verifier isolation adapter; source tests stay intact."""
from __future__ import annotations

import shutil
from pathlib import Path

from .storage import file_digest

SOURCE_HASHES={
 'test.sh':'b6a9b6a83e86e234dac10d6762bed1532b36a54e830b6a4a474e919f2e21cf14',
 'test_eval_parity.py':'be20c405ee0c0d8dd88d07a952db25c886300f09a327936e7f95d63c127f0cad',
 'oracle_eval.py':'22280202dcdd5c21ef03c02bed1afde36e4e46f99c14d3e1bc451600a1e1d82b',
}
SOURCE_INSTRUCTION_SHA256='5da93cdf030a3d4a10bcb463fe313c8b317d99568dae74c52ebb493ab63308dc'
DERIVED_ID='derived_semantics_test.py::test_repeat_fixture_matches_independent_oracle'
DERIVED_TEST='''"""Derived correctness check; original five tests and reward are separate."""
import test_eval_parity as original

def test_repeat_fixture_matches_independent_oracle(tmp_path):
    all_examples=original.make_hidden_examples()
    support=[e for e in all_examples if e["type"]=="support"]
    rows=[e for e in all_examples if e["type"]!="support"]
    examples=support+rows[::7]
    data=tmp_path/"repeat-oracle-input.jsonl"
    original.write_jsonl(data,examples)
    expected=original.evaluate_dataset(examples)
    actual=original.run_evaluator(data,tmp_path/"repeat-oracle-output.json",9,"right","packed")
    original.assert_result_matches(actual,expected)
'''
WRAPPER='''#!/bin/bash
# Evaluator-only adapter: protects gold from the nobody artifact subprocess.
# The upstream script, five tests, timeout and reward calculation are unchanged.
chmod 700 /tests /logs/verifier || exit 90
printf '{"isolation_ready":true}\\n' > /logs/verifier/isolation-ready.json
bash /tests/test.original.sh
cd /tests || exit 91
# A derived failure is a behavior failure; never overwrite the upstream reward.
python -m pytest -p no:cacheprovider --ctrf /logs/verifier/derived-ctrf.json /tests/derived_semantics_test.py -rA
exit 0
'''


def control_evidence_ok(trial:Path,passed:bool):
    """A cached upstream verifier image must never masquerade as the adapter."""
    import json

    from .primary_report import ctrf_assertions

    trial=Path(trial)
    try:
        ready=json.loads((trial/'verifier/isolation-ready.json').read_text())
        derived=json.loads((trial/'verifier/derived-ctrf.json').read_text())
    except (OSError,ValueError):return False
    return (isinstance(ready,dict)and ready.get('isolation_ready')is True
            and ctrf_assertions(derived,[DERIVED_ID])['test:'+DERIVED_ID]==('pass'if passed else'fail'))


def prepare_tb01_case(source:Path,destination:Path):
    source=Path(source);destination=Path(destination)
    if file_digest(source/'instruction.md')!=SOURCE_INSTRUCTION_SHA256:
        raise ValueError('TB01 original instruction changed')
    for name,expected in SOURCE_HASHES.items():
        if file_digest(source/'tests'/name)!=expected:raise ValueError('TB01 original verifier changed')
    if destination.exists():raise ValueError('new versioned task directory required')
    shutil.copytree(source,destination)
    tests=destination/'tests';(tests/'test.sh').rename(tests/'test.original.sh');(tests/'test.sh').write_text(WRAPPER);(tests/'derived_semantics_test.py').write_text(DERIVED_TEST)
    if file_digest(tests/'test.original.sh')!=SOURCE_HASHES['test.sh']:raise ValueError('upstream verifier script not preserved')
    manifest={'case_version':'tb01-default-secure.v1','source_verifier_sha256':SOURCE_HASHES,
        'runtime_changes':{n:file_digest(tests/n)for n in ('test.sh','test.original.sh','derived_semantics_test.py')},
        'original_five_tests_unchanged':True,'original_reward_file_unchanged':True,
        'changes':['root-only /tests before untrusted artifact execution','additional repeat-fixture independent oracle check'],
        'derived_assertion_id':DERIVED_ID,'official_leaderboard_claim':False}
    return manifest


def align_primary_time_instruction(task:Path):
    """A new prepared copy must disclose the same cap that Harbor will enforce."""
    import hashlib
    import re
    import tomllib

    task=Path(task)
    seconds=tomllib.loads((task/'task.toml').read_text()).get('agent',{}).get('timeout_sec')
    if type(seconds)is not int or not 0<seconds<=28800:
        raise ValueError('invalid effective actor timer')
    path=task/'instruction.md';before=path.read_bytes();text=before.decode('utf-8')
    pattern=r'You have (\d+) seconds to complete this task\.'
    if re.findall(pattern,text)!=['28800']:
        raise ValueError('unique original source time declaration required')
    after=re.sub(pattern,f'You have {seconds} seconds to complete this task.',text).encode('utf-8')
    # Keep every unrelated byte unchanged. Source/raw task is never written.
    path.write_bytes(after)
    return {'version':'tb01-visible-timer.v1','source_actor_seconds':28800,'actor_seconds':seconds,
        'source_instruction_sha256':hashlib.sha256(before).hexdigest(),
        'effective_instruction_sha256':hashlib.sha256(after).hexdigest(),
        'model_visible_task_changed':before!=after,
        'only_change':f'original time declaration 28800 -> {seconds} seconds'}


def build_secure_verifier(task:Path,base_reference:str,log:Path,env:dict,*,timeout=300):
    import hashlib
    import subprocess
    import tomllib

    import toml

    from .images import inspect_image

    base=inspect_image(base_reference,env)
    context=Path(task)/'tests'
    (context/'Dockerfile.original').write_bytes((context/'Dockerfile').read_bytes())
    (context/'Dockerfile').write_text('FROM '+base_reference+'\nCOPY . /tests/\nRUN chmod 700 /tests /logs/verifier\n')
    identity=hashlib.sha256((base['id']+WRAPPER+DERIVED_TEST).encode()).hexdigest()
    reference='memweave-eval:tb01-secure-'+identity[:24]
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('wb')as output:
        result=subprocess.run(['docker','build','--network','none','--pull=false','--platform',base['platform'],'--tag',reference,str(context)],
            env=env,stdout=output,stderr=subprocess.STDOUT,timeout=timeout,check=False)
    if result.returncode:raise RuntimeError('TB01 secure verifier build failed')
    image=inspect_image(reference,env)
    config=tomllib.loads((Path(task)/'task.toml').read_text());config['verifier']['environment']['docker_image']=reference
    (Path(task)/'task.toml').write_text(toml.dumps(config))
    return {'base_image':base,'secure_image':image,'dockerfile_sha256':file_digest(context/'Dockerfile'),
            'adapter_version':'tb01-default-secure.v1','model_visible_task_changed':False,'original_tests_and_reward_preserved':True}


def secure_prepared_task(root,record,env,deadline):
    import time

    from .storage import atomic_json, contained
    from .suites import task_digest

    source=contained(root,record['runtime_path']);task=root/'runtime-tasks-secure'/source.name
    task.parent.mkdir(parents=True,exist_ok=True);adapter=prepare_tb01_case(source,task)
    timer=align_primary_time_instruction(task)
    image=build_secure_verifier(task,record['images']['verifier']['reference'],root/'preparation'/source.name/'secure-build.log',env,
        timeout=min(300,max(1,deadline-time.monotonic())))
    path=root/'preparation'/source.name/'secure-manifest.json'
    manifest={'upstream_preparation_manifest':record['manifest_path'],'upstream_preparation_sha256':record['manifest_sha256'],
              'adapter':adapter,'time_instruction':timer,'secure_verifier':image,'runtime_path':task.relative_to(root).as_posix(),'runtime_sha256':task_digest(task)}
    atomic_json(path,manifest,immutable=True)
    return {**record,'runtime_path':manifest['runtime_path'],'runtime_sha256':manifest['runtime_sha256'],
        'manifest_path':path.relative_to(root).as_posix(),'manifest_sha256':file_digest(path),
        'images':{**record['images'],'verifier':image['secure_image']},'verifier_adapter':adapter,
        'protocol_equivalent':False,'declared_adaptation':{**record.get('declared_adaptation',{}),
            'verifier_security_and_additional_assertion':'tb01-default-secure.v1','time_instruction':timer}}
