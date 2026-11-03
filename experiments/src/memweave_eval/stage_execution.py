"""Separate actual request/log coverage from a complete planned stage sequence."""
from __future__ import annotations

import json


def stage_execution(trial,events):
    expected=None;registered=False
    for path in trial.rglob('experiment-setup.json'):
        if path.is_symlink()or not path.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected stage declaration')
        setup=json.loads(path.read_text());registered |= 'expected_actor_stage_names'in setup
        names=setup.get('expected_actor_stage_names')
        if not names:continue
        if not isinstance(names,list)or any(not isinstance(n,str)or not n for n in names)or len(set(names))!=len(names):
            raise ValueError('invalid declared stage sequence')
        if expected is not None and expected!=names:raise ValueError('conflicting stage declarations')
        expected=names
    starts={e.get('stage_id')for e in events if e['event']=='workspace_checkpoint'and e.get('phase')=='agent_start'}
    ends={e.get('stage_id')for e in events if e['event']=='workspace_checkpoint'and e.get('phase')=='agent_end'}
    source=trial/'result.json'
    raw=json.loads(source.read_text())if source.exists()else{}
    steps=raw.get('step_results')or[]
    failures=[{'name':s.get('step_name',s.get('name')),'exception':s['exception_info']}
        for s in steps if s.get('exception_info')]
    if expected is None:return {'status':'NO_FIXED_SOURCE_STAGE_SEQUENCE'if registered else'EXPECTED_SEQUENCE_NOT_REGISTERED','expected_names':[]if registered else None,
        'observed_stage_ids':sorted(starts,key=str),'protocol_execution_complete':None,
        'evidence_complete':True if registered else None,'known_step_failures':failures,
        'reason':'single/dynamic dialogue has no fixed source-step denominator; actual invocation/request coverage is separate'
            if registered else'actual requests do not prove that every intended actor stage ran'}
    by_name={s.get('step_name',s.get('name')):s for s in steps};rows=[];aborted=bool(raw.get('exception_info'))
    for index,name in enumerate(expected,1):
        identity=str(index);step=by_name.get(name,{})
        if identity in starts:status='EXECUTED'if identity in ends else'INTERRUPTED_WITH_KNOWN_ERROR'if step.get('exception_info')else'MISSING_TERMINAL_EVIDENCE'
        elif step.get('exception_info'):status='FAILED_BEFORE_PI'
        elif aborted:status='NOT_STARTED_AFTER_ABORT'
        else:status='MISSING_REQUIRED_INVOCATION'
        rows.append({'stage_id':identity,'source_step_name':name,'status':status,
            'exception_type':(step.get('exception_info')or{}).get('exception_type')})
        if step.get('exception_info'):aborted=True
    extra=starts-{str(i)for i in range(1,len(expected)+1)}
    complete=all(r['status']=='EXECUTED'for r in rows)and not extra
    return {'status':'COMPLETE'if complete else'INCOMPLETE_PROTOCOL','expected_names':expected,'stages':rows,
        'observed_stage_ids':sorted(starts,key=str),'unexpected_stage_ids':sorted(extra,key=str),
        'protocol_execution_complete':complete,
        'evidence_complete':not extra and not any(r['status'].startswith('MISSING')for r in rows),
        'known_step_failures':failures,'reason':None if complete else
            'source stage execution failure and not-started stages are distinct from lost evidence; no model score is inferred'}
