"""Frozen official-task adapters; deterministic observations, never a free-text judge."""
from pathlib import Path
import hashlib
import os
import json
import re
from .behavior_metrics import evaluate_behavior
from .engineering_metrics import read_events
from .wasm_metrics import _originals, _text, wasm_metrics


def marathon_metrics(agent: Path,gold:dict,*,task_id:str,enabled:bool):
    if 'tasks' not in gold:
        return wasm_metrics(agent,gold,enabled=enabled)
    spec=gold['tasks'][task_id]
    trace,status=read_events(agent/'request-trace.jsonl')
    checkpoints=[(i,e)for i,e in enumerate(trace,1)if e.get('workspace')]
    protected=spec.get('protected_hashes',{})
    protection=[(i,all(e['workspace'].get('files',{}).get(k)==v for k,v in protected.items()))for i,e in checkpoints]
    results,_=_originals(agent)
    tests=[]
    for entry,message,call in results:
        command=(call.get('arguments')or{}).get('command','')
        if re.search(spec['public_test_pattern'],command):
            tests.append({'entry_id':entry['id'],'passed':not message.get('isError',False),'call_id':message.get('toolCallId')})
    def item(value,ids):return {'value':value,'evidence_ids':ids}
    evidence={}
    if protected:
        evidence['protected-files']={'unchanged':item(all(v for _,v in protection)if protection else None,
            [f'request-trace.jsonl:{i}'for i,_ in protection])}
    evidence['public-validation']={'executed_successfully':item(any(t['passed']for t in tests)if tests else False if results else None,
        [t['entry_id']for t in tests]or ['pi/sessions:complete']if results else [])}
    # Original verifier anti-shortcut checks remain the business correctness oracle.
    metrics_file=agent.parent/'verifier/metrics.json'
    original=json.loads(metrics_file.read_text())if metrics_file.is_file()else None
    evidence['original-verifier']={'passed':item(original.get('reward')==1 if original and 'reward'in original else None,['verifier/metrics.json']if original else [])}
    requests=[(i,e)for i,e in enumerate(trace,1)if e.get('event')=='request_ready'and e.get('request_kind')=='agent']
    evicted=next(((i,e)for i,e in requests if e.get('original_instruction_visible')is False),None)
    retention={'value':None,'status':'unknown','reason':'no_confirmed_instruction_eviction','evidence_ids':[]}
    if not enabled:retention.update(status='not_applicable',reason='native has no State')
    elif evicted:
        before=[(i,e)for i,e in requests if i<evicted[0]]
        # Actual delivered State bits are conservative program-recognized clauses; null is unknown.
        early=[(i,e.get('state_constraint_bits',{}).get('task_constraint'))for i,e in before]
        late=[(i,e.get('state_constraint_bits',{}).get('task_constraint'))for i,e in requests if i>=evicted[0]]
        values=[v for _,v in early+late]
        boundary_correct=all(v for i,v in protection if i<evicted[0])if protected else None
        retention.update(reason='constraint_retention_proxy_not_adoption',
            pre_boundary_protection=boundary_correct,instruction_evicted=True,
            evidence_ids=[f'request-trace.jsonl:{i}'for i,_ in early+late])
        if early and late and all(type(v)is bool for v in values):
            retention.update(value=bool(any(v for _,v in early)and all(v for _,v in late)),status='scored')
    result=evaluate_behavior({'version':gold['version'],'cases':spec['cases']},evidence)
    handoff_path=agent/'sealed-handoff.json'
    handoff={'status':'not_applicable','reason':'task_has_no_sealed_handoff'}
    if task_id=='zstd-decoder':
        handoff={'status':'unknown','reason':'handoff_manifest_missing'}
        if handoff_path.is_file():
            manifest=json.loads(handoff_path.read_text());directory=agent.parent/'artifacts/src'
            missing=[];mismatch=[]
            for name,value in manifest.get('handoff_files',{}).items():
                target=directory/name
                if value['type']=='symlink':
                    if not target.is_symlink()or os.readlink(target)!=value['target']:mismatch.append(name)
                elif not target.is_file()or target.is_symlink()or not target.resolve().is_relative_to(directory.resolve()):missing.append(name)
                elif hashlib.sha256(target.read_bytes()).hexdigest()!=value['sha256']:mismatch.append(name)
            handoff={'status':'verified_host_artifact'if not missing and not mismatch and not manifest.get('unsupported_inputs')else'adapter_issue',
                'file_count':len(manifest.get('handoff_files',{})),'missing':missing,'mismatched':mismatch,
                'unsupported':manifest.get('unsupported_inputs',[]),'fresh_verifier_per_file_hash':'not_observed',
                'scope':'source-side manifest vs Harbor collected input artifact; original verifier executes in fresh image'}
    result.update(adapter=gold['version'],adapter_handoff=handoff,task_id=task_id,source_status=status,original_metrics=original,
        public_test_calls=tests,constraint_retention_proxy=retention,
        progress_inputs=[e for e in trace if e.get('event')=='case_input'],
        interpretation='Original verifier preserved; clause retention is a conservative proxy, not causal memory adoption. Offline C1-C8/Task fixtures are separate implementation validation.')
    return result
