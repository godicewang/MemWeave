"""Pinned Switch-SWE business components; no Task or memory success is inferred.

The route ledger is evaluator-only. Source logical response IDs are deliberately
separate from runtime MemWeave Task IDs, which require a real seeded corpus.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from .fixed35 import checkpoint_verdict
from .storage import file_digest

VERSION='fixed35-switch-source-components-20261102-v1'
REVISION='992e3709c906e1801e2a4494d875d501950cccdc'
CASES={
    'INT-06': {'path':'near/sf101','focus':'w01',
        'routes':['w01','w03','w03','w00','w01','w02','w04','w02','w00','w04','w01','w04','w00','w04','w00'],
        'current_constraint_turn':11,'return_turn':5},
    'INT-07': {'path':'far/sf001','focus':'w00',
        'routes':['w00','w02','w03','w04','w02','w02','w01','w01','w01','w01','w02','w03','w04','w03','w00','w00','w00','w04'],
        'current_constraint_turn':15,'return_turn':15},
}


def switch_contract(source:Path,case_id:str):
    spec=CASES[case_id]
    if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=REVISION:
        raise ValueError('Switch-SWE source revision differs from selected pin')
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):
        raise ValueError('Switch-SWE source checkout changed')
    task=source/'tasks'/spec['path']
    config=tomllib.loads((task/'task.toml').read_text())
    steps=[s['name']for s in config['steps']]
    if steps!=[f'turn-{i:02}'for i in range(1,len(spec['routes'])+1)]+['final']:
        raise ValueError('Switch stage order differs from case route ledger')
    native=task/'steps/final/tests/contract.json'
    gold=json.loads(native.read_text())
    instruction=task/'steps/final/instruction.md'
    match=re.search(r'\{"task_id":\s*"([^"]+)"',instruction.read_text())
    if not match or gold['focus_path']!='/work/'+spec['focus']:
        raise ValueError('Switch final response identity or focus scope missing')
    return {'version':VERSION,'case_id':case_id,'upstream_case_id':gold['case_id'],
        'source_revision':REVISION,'source_contract_sha256':file_digest(native),
        'source_final_instruction_sha256':file_digest(instruction),
        'source_grader_sha256':file_digest(native.with_name('grader.py')),
        'response_task_id':match[1],'source_grader_task_id':gold['task_id'],
        'runtime_memweave_task_ids':None,'focus_path':gold['focus_path'],'base_commit':gold['base_commit'],
        'f2p':gold['derived_fail_to_pass'],'p2p':gold['derived_pass_to_pass'],
        'protected_paths':gold['protected_paths'],
        'route_ledger':[{'stage_id':str(i),'source_step':name,'goal_slot':slot,
            'instruction_sha256':file_digest(task/'steps'/name/'instruction.md'),
            'allowed_routes':['create','resume']if slot not in spec['routes'][:i-1]else['continue','resume'],
            'route_qualification':'No forced create without proving the query-time reusable corpus; '
                'slot denotes this source workspace/goal, not a runtime Task ID'}
            for i,(name,slot)in enumerate(zip(steps[:-1],spec['routes'],strict=True),1)],
        'final_stage_id':str(len(steps)),'return_stage_id':str(spec['return_turn']),
        'latest_constraint_stage_id':str(spec['current_constraint_turn']),
        'checkpoints':{'final_delivery':['strict_json','source_response_identity','nonempty_analysis','unified_diff_paths'],
            'business_tests':['all_original_f2p','all_original_p2p','original_grader_graded']},
        'status':'SOURCE_BUSINESS_COMPONENT_ONLY',
        'remaining':['Task corpus/Goal semantic binding and same-goal reuse oracle',
            'actual first-critical-action restore oracle and current State adoption',
            'ephemeral overlay and return dependency are not implemented by this source component'],
        'scope':'Final delivery and original source business tests only. Not Task restoration or memory adoption; '
            'test/answer gold remains evaluator-only; no new scoring weight or historical score mutation.'}


def _point(name,values):
    return checkpoint_verdict({'id':VERSION+':'+name,'required_assertions':list(values)},values)


def grade_switch_final(contract,*,answer,outcomes,original_result):
    """Independent final-delivery and native-test checkpoints; never one case-wide AND."""
    parsed=None;valid=None if answer is None else False
    if isinstance(answer,str):
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate JSON member')
                result[key]=value
            return result
        def nonfinite(value):raise ValueError('nonfinite JSON number')
        try:
            parsed=json.loads(answer,object_pairs_hook=unique,parse_constant=nonfinite)
            valid=isinstance(parsed,dict)and set(parsed)=={'task_id','analysis','patch'}
        except ValueError:
            pass
    elif answer is not None:raise ValueError('final answer must be text or missing')
    paths=None
    if valid:
        patch=parsed.get('patch')
        if isinstance(patch,str):
            headers=re.findall(r'^diff --git a/(.+) b/(.+)$',patch,re.MULTILINE)
            paths=bool(headers)and bool(re.search(r'^@@ .+ @@',patch,re.MULTILINE))
            for old,new in headers:
                for value in (old,new):
                    path=PurePosixPath(value)
                    if path.is_absolute()or'..'in path.parts or value in contract['protected_paths']:
                        paths=False
            # This checks delivery shape, not actual base applicability or code correctness.
        else:paths=False
    delivery=_point('final-delivery',{
        'strict_json':valid,
        'source_response_identity':parsed.get('task_id')==contract['response_task_id']if valid else None if answer is None else False,
        'nonempty_analysis':isinstance(parsed.get('analysis'),str)and bool(parsed['analysis'].strip())if valid else None if answer is None else False,
        'unified_diff_paths':paths if valid else None if answer is None else False})
    def tests(ids):
        if not isinstance(outcomes,dict):return None
        values=[outcomes.get(identity)for identity in ids]
        if any(isinstance(value,str)and value in {'fail','error'}for value in values):return False
        return True if values and all(value=='pass'for value in values)else None
    graded=(original_result.get('status')=='graded')if isinstance(original_result,dict)else None
    # Infrastructure errors are unknown business outcomes, not an agent failure.
    if graded is False:graded=None
    business=_point('original-business-tests',{'all_original_f2p':tests(contract['f2p']),
        'all_original_p2p':tests(contract['p2p']),'original_grader_graded':graded})
    return {'version':VERSION,'case_id':contract['case_id'],'checkpoints':[delivery,business],
        'collection_complete':delivery['collection_complete']and business['collection_complete'],
        'memory_adoption_score':None,'task_restore_score':None,
        'interpretation':contract['scope'],'runtime_memweave_task_ids':None}
