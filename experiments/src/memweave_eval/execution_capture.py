"""Independent native stdout identities for each actual Pi CLI invocation."""
from __future__ import annotations

import json
from pathlib import Path

from .evidence_replay import read_object
from .storage import file_digest


def _hookless_preparation_rejection(trial,invocation,call_id,native,events,manifest):
    calls=[p for row in native if row.get('type')=='message_end'and
        (row.get('message')or{}).get('role')=='assistant'
        for p in row['message'].get('content',[])if p.get('type')=='toolCall'and p.get('id')==call_id]
    starts=[r for r in native if r.get('type')=='tool_execution_start'and r.get('toolCallId')==call_id]
    ends=[r for r in native if r.get('type')=='tool_execution_end'and r.get('toolCallId')==call_id]
    results=[r['message']for r in native if r.get('type')=='message_end'and
        (r.get('message')or{}).get('role')=='toolResult'and r['message'].get('toolCallId')==call_id]
    if any(len(rows)!=1 for rows in [calls,starts,ends,results]):return None
    call,start,end,result=calls[0],starts[0],ends[0],results[0];name=call.get('name')
    if not isinstance(name,str)or not name or any(r.get('toolName')!=name for r in [start,end,result]) \
            or start.get('args')!=call.get('arguments')or end.get('isError')is not True \
            or result.get('isError')is not True or 'durationMs'in end:return None
    content=(end.get('result')or{}).get('content')
    if content!=result.get('content')or not isinstance(content,list)or len(content)!=1 \
            or content[0].get('type')!='text'or not isinstance(content[0].get('text'),str):return None
    text=content[0]['text'];prefixes=[
        ('invalid_arguments','Invalid arguments for tool "'+name+'":'),
        ('schema_validation','Validation failed for tool "'+name+'":'),
        ('unknown_tool','Tool '+name+' not found'),
        ('truncated_output','Tool call "'+name+'" was not executed: the response hit the output token limit, so its arguments may be truncated. Re-issue the tool call with complete arguments.')]
    reason=next((kind for kind,prefix in prefixes if
        (text==prefix if kind in {'unknown_tool','truncated_output'}else text.startswith(prefix))),None)
    if reason is None:return None
    related=[e for e in events if e.get('execution_invocation_id')==invocation and e.get('call_id')==call_id]
    proofs=[]
    for kind,record in [('tool_execution_start',start),('tool_execution_end',end)]:
        matches=[e for e in related if e['event']==kind and e.get('tool')==name]
        if len(matches)!=1:return None
        event=matches[0];ref=event.get('record_ref');verified=False
        if not isinstance(ref,dict):return None
        for store in trial.rglob('request-content'):
            try:actual=json.loads(read_object(store,ref))
            except (OSError,ValueError,EOFError,KeyError):continue
            if actual==record:verified=True;break
        if not verified:return None
        proofs.append({'event':kind,'record_sha256':ref['sha256']})
    return {'invocation_id':invocation,'call_id':call_id,'tool':name,'reason':reason,
        'native_stdout_sha256':manifest['stdout_sha256'],'cas_records':proofs,
        'scope':'Pi1.4 original preparation rejection, no execute duration and matching independent native result; no fabricated tool_call hook'}


def scoped_execution_boundaries(trial:Path,events,*,stage_id=None):
    sources=list(trial.rglob('execution-invocations/*.json'))
    if not sources and not any(e.get('execution_invocation_id')for e in events):return None
    manifests={};stdout={};errors=[]
    for source in sources:
        if source.is_symlink()or not source.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected invocation evidence')
        value=json.loads(source.read_text());identity=value.get('invocation_id')
        if value.get('schema_version')!=1 or not isinstance(identity,str)or source.stem!=identity:
            raise ValueError('invalid invocation identity')
        if stage_id is not None and value.get('stage_id')!=str(stage_id):continue
        if identity in manifests and manifests[identity]!=value:
            raise ValueError('conflicting cumulative invocation copies')
        manifests[identity]=value
        if value.get('capture_status')!='CAPTURED' or value.get('status')not in {'RETURNED','EXECUTION_RAISED'}:
            errors.append('invocation_stdout_or_terminal_capture_missing');continue
        name=value.get('stdout_file')
        if name!=identity+'.stdout.jsonl':raise ValueError('invalid native stdout name')
        target=source.parent/name
        if target.is_symlink()or not target.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected native stdout')
        if not target.exists():errors.append('invocation_stdout_file_missing');continue
        if file_digest(target)!=value.get('stdout_sha256')or target.stat().st_size!=value.get('stdout_bytes'):
            raise ValueError('native invocation stdout hash differs')
        try:stdout[identity]=[json.loads(line)for line in target.read_text().splitlines()]
        except (ValueError,UnicodeError):errors.append('incomplete_native_invocation_stdout')
    expected=set();completed=set();observed=set();post=set();terminal=True
    if not manifests:errors.append('native_invocation_manifest_missing')
    for identity,manifest in manifests.items():
        native=stdout.get(identity,[])
        begins=[i for i,r in enumerate(native)if r.get('type')=='agent_start']
        ends=[i for i,r in enumerate(native)if r.get('type')=='agent_end']
        if not begins or not ends or ends[-1]<begins[-1]:terminal=False
        for row in native:
            if row.get('type')=='tool_execution_start':expected.add((identity,row.get('toolCallId')))
            if row.get('type')=='tool_execution_end':completed.add((identity,row.get('toolCallId')))
            message=row.get('message')or{}
            if row.get('type')=='message_end'and message.get('role')=='assistant':
                expected.update((identity,p.get('id'))for p in message.get('content',[])if p.get('type')=='toolCall')
            if row.get('type')=='message_end'and message.get('role')=='toolResult':
                completed.add((identity,message.get('toolCallId')))
        related=[e for e in events if e.get('execution_invocation_id')==identity]
        expected_returns=sum(r.get('type')=='message_end'and(r.get('message')or{}).get('role')=='assistant'for r in native)
        if expected_returns!=sum(e['event']=='assistant_return'for e in related):
            errors.append('assistant_return_callbacks_differ_from_native_stdout')
        if any(str(e.get('stage_id'))!=manifest['stage_id']for e in related):
            errors.append('invocation_stage_differs_from_observer')
        starts=[e for e in related if e['event']=='workspace_checkpoint'and e.get('phase')=='agent_start']
        finishes=[e for e in related if e['event']=='workspace_checkpoint'and e.get('phase')=='agent_end']
        if not starts or not finishes:errors.append('initial_or_terminal_boundary_missing')
        elif starts[0]['timestamp']>finishes[-1]['timestamp']:errors.append('boundary_order_invalid')
    identities=set(manifests)
    scoped=[]
    for e in events:
        if e['event']not in {'tool_call','workspace_checkpoint'}:continue
        identity=e.get('execution_invocation_id')
        if identity not in identities:errors.append('observer_invocation_not_in_native_capture');continue
        if e['event']=='tool_call':
            observed.add((identity,e.get('call_id')));scoped.append((e['producer_id'],e.get('call_id')))
        elif e.get('phase')in {'tool_end','tool_result'}:post.add((identity,e.get('call_id')))
    if len(scoped)!=len(set(scoped)):errors.append('reused_call_identity_within_execution')
    rejected=[]
    for identity,call_id in expected-observed:
        proof=_hookless_preparation_rejection(trial,identity,call_id,stdout.get(identity,[]),events,manifests[identity])
        if proof is not None:rejected.append(proof)
    explained={(p['invocation_id'],p['call_id'])for p in rejected}
    if expected!=observed|explained:errors.append('call_boundary_set_differs_from_Pi_log')
    if not expected<=completed:errors.append('tool_completion_missing_or_pending')
    if not completed<=post:errors.append('completed_tool_workspace_snapshot_missing')
    if not terminal:errors.append('native_terminal_execution_missing')
    if any(key[1]is None for key in expected|completed|observed):errors.append('call_identity_missing')
    return {'complete':not errors,'reasons':sorted(set(errors)),'expected_tool_calls':len(expected),
        'completed_tool_calls':len(completed),'post_tool_snapshots':len(post),
        'terminal_execution_observed':terminal,'scope':'independent-native-Pi-invocation-v1',
        'invocations':len(manifests),'pre_execution_rejections':rejected,
        'observed_tool_call_hooks':len(observed)}
