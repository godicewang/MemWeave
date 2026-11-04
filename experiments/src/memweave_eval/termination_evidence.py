"""Prove a real deadline cancellation without inventing a native end/result."""
from __future__ import annotations

import json
import math
from datetime import datetime


def _seconds(value):
    if type(value)in (int,float):return value if math.isfinite(value)else None
    if isinstance(value,str):
        try:return datetime.fromisoformat(value).timestamp()
        except ValueError:return None
    return None


def deadline_termination(trial,manifest,events):
    """A captured signal plus independent PID guard and invocation time envelope.

    Missing or early signals never excuse missing callbacks. The native stdout
    digest is checked by execution_capture before this function is called.
    """
    identity=manifest.get('invocation_id')
    rows=[e for e in events if e.get('event')=='execution_terminated'and
        e.get('execution_invocation_id')==identity]
    if len(rows)!=1:return None
    row=rows[0];pid=row.get('owner_pid');deadline=_seconds(row.get('scheduled_deadline'))
    at=_seconds(row.get('timestamp'));start=_seconds(manifest.get('started_at'));end=_seconds(manifest.get('finished_at'))
    if row.get('capture_status')!='CAPTURED'or row.get('signal')!='SIGTERM'or type(pid)is not int or pid<=1 \
            or row.get('observation_source')!='evaluation_signal_microtask_not_native_agent_end' \
            or str(row.get('stage_id'))!=manifest.get('stage_id') \
            or any(v is None for v in [deadline,at,start,end])or not start<=end \
            or not deadline-2<=at<=deadline+5 or not start-2<=at<=end+5:
        return None
    if manifest.get('status')!='EXECUTION_RAISED'or manifest.get('error_class')not in {
            'NonZeroAgentExitCodeError','AgentTimeoutError','TimeoutError'}:return None
    workspace=row.get('workspace');registry=row.get('registry')
    if not isinstance(workspace,dict)or not isinstance(workspace.get('files'),dict)or \
            not isinstance(registry,dict)or registry.get('complete')is not True or not isinstance(registry.get('tasks'),list):return None
    for name,digest in workspace['files'].items():
        status=workspace.get('file_status',{}).get(name,{})
        if not (isinstance(digest,str)and status.get('status')=='present'or digest is None and status.get('status')=='absent'):return None
    if any(v.get('complete')is not True for v in workspace.get('tree_projections',{}).values()):return None
    if any(v.get('status')not in {'captured','absent'}for v in workspace.get('artifacts',{}).values()):return None
    stops=[]
    for path in [*trial.rglob('request-trace.jsonl'),*trial.rglob('cli-request-trace.jsonl')]:
        if path.is_symlink()or not path.resolve().is_relative_to(trial.resolve()):raise ValueError('redirected deadline evidence')
        for line in path.read_text().splitlines():
            event=json.loads(line);when=_seconds(event.get('timestamp'))
            if event.get('event')=='local_deadline_stop'and event.get('pid')==pid and when is not None \
                    and deadline-2<=when<=deadline+5 and abs(when-at)<=5:stops.append(event)
    if not stops:return None
    return {'invocation_id':identity,'stage_id':manifest['stage_id'],'producer_id':row['producer_id'],
        'owner_pid':pid,'signal':'SIGTERM','scheduled_deadline':deadline,'observed_at':at,
        'native_agent_end_observed':False,'native_stdout_sha256':manifest['stdout_sha256'],
        'boundary_sequence':row['sequence'],'scope':'frozen-deadline-cancellation-with-independent-PID-guard-v1'}
