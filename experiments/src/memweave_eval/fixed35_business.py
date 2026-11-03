"""Case-specific program predicates over original actions, not fixture labels."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .evidence_replay import read_object, replay_content
from .fixed35 import checkpoint_verdict
from .fixed35_mab import active_text


def case_events(trial:Path):
    records={};locations={}
    for store in trial.rglob('request-content'):
        for event in replay_content(store)['events']:
            identity=event['producer_id'],event['sequence']
            if identity in records and records[identity]!=event:raise ValueError('conflicting case event')
            records[identity]=event;locations[identity]=store
    events=sorted(records.values(),key=lambda e:(e['timestamp'],e['producer_id'],e['sequence']))
    return events,locations


def readonly_checkpoint(required_paths,texts,initial,observations,*,changed_boundary_known,boundaries_complete=None):
    checks={}
    for path in required_paths:
        checks['remember:'+path]=None if texts is None else any(
            re.search(r'(?:^|[;\n])\s*READ_ONLY\s+'+re.escape(path)+r'(?=$|[\s,;]|\.(?:$|\s))',text)for text in texts)
        values=[row.get(path)for row in observations]if observations is not None else []
        valid_initial=isinstance(initial,dict)and isinstance(initial.get(path),str)and re.fullmatch(r'[a-f0-9]{64}',initial[path])
        violation=bool(valid_initial)and any(isinstance(value,str)and value!=initial[path]for value in values)
        checks['preserve:'+path]=(False if violation else True if valid_initial and boundaries_complete is True
            and len(values)>=2 and all(isinstance(value,str)for value in values)else None)
    checks['memory_before_first_persistent_change']=changed_boundary_known
    return checkpoint_verdict({'id':'F35.C3.readonly-before-first-change-v2','required_assertions':list(checks)},checks)


def execution_boundaries(trial,events,*,stage_id=None):
    """Cross-check workspace hooks against independent Pi stdout call/end records."""
    from .execution_capture import scoped_execution_boundaries
    scoped_result=scoped_execution_boundaries(trial,events,stage_id=stage_id)
    if scoped_result is not None:return scoped_result
    expected=set();completed=set();errors=[];terminal=True;sources=list(trial.rglob('pi.txt'))
    if not sources:errors.append('independent_Pi_execution_log_missing')
    for source in sources:
        if source.is_symlink()or not source.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected Pi execution log')
        rows=[]
        try:rows=[json.loads(line)for line in source.read_text().splitlines()]
        except (ValueError,OSError):errors.append('incomplete_Pi_execution_log')
        starts=[i for i,r in enumerate(rows)if r.get('type')=='agent_start']
        ends=[i for i,r in enumerate(rows)if r.get('type')=='agent_end']
        if not starts or not ends or ends[-1]<starts[-1]:terminal=False
        for row in rows:
            if row.get('type')=='tool_execution_start':expected.add(row.get('toolCallId'))
            if row.get('type')=='tool_execution_end':completed.add(row.get('toolCallId'))
            message=row.get('message')or{}
            if row.get('type')=='message_end'and message.get('role')=='assistant':
                expected.update(p.get('id')for p in message.get('content',[])if p.get('type')=='toolCall')
            if row.get('type')=='message_end'and message.get('role')=='toolResult':completed.add(message.get('toolCallId'))
    observed={e.get('call_id')for e in events if e['event']=='tool_call'}
    scoped=[(e['producer_id'],e.get('call_id'))for e in events if e['event']=='tool_call']
    if len(scoped)!=len(set(scoped)):errors.append('reused_call_identity_within_execution')
    post={e.get('call_id')for e in events if e['event']=='workspace_checkpoint'and e.get('phase')in {'tool_end','tool_result'}}
    starts=[e for e in events if e['event']=='workspace_checkpoint'and e.get('phase')=='agent_start']
    ends=[e for e in events if e['event']=='workspace_checkpoint'and e.get('phase')=='agent_end']
    if expected!=observed:errors.append('call_boundary_set_differs_from_Pi_log')
    if not expected<=completed:errors.append('tool_completion_missing_or_pending')
    if not completed<=post:errors.append('completed_tool_workspace_snapshot_missing')
    if not terminal or not starts or not ends:errors.append('initial_or_terminal_boundary_missing')
    if starts and ends and starts[0]['timestamp']>ends[-1]['timestamp']:errors.append('boundary_order_invalid')
    if None in expected|completed|observed:errors.append('call_identity_missing')
    return {'complete':not errors,'reasons':errors,'expected_tool_calls':len(expected),
        'completed_tool_calls':len(completed),'post_tool_snapshots':len(post),'terminal_execution_observed':terminal,
        'scope':'legacy-call-id-set-without-invocation-binding'}


def memory_rate(values):
    known=[v for v in values if type(v)is bool]
    success=sum(known);unknown=len(values)-len(known)
    return {'value':success/len(known)if known and not unknown else None,
        'numerator':success,'denominator':len(known),'unknown':unknown,
        'status':'unknown'if unknown else'scored'if known else'not_applicable'}


def grade_readonly(trial:Path,contract,*,arm):
    events,locations=case_events(trial);frames=[e for e in events if e['event']in {'workspace_checkpoint','request_ready'}and 'workspace'in e]
    def files(event):
        out={}
        for name,value in event['workspace']['files'].items():
            status=event['workspace'].get('file_status',{}).get(name,{})
            if value is None and (status.get('status')=='absent'or status.get('error_class')in {'EACCES','EPERM'}):value='ABSENT_OR_ACCESS_VIOLATION'
            out[str(Path(contract['workspace_root'])/name)]=value
        return out
    coverage=execution_boundaries(trial,events)
    starts=[e for e in frames if e.get('phase')=='agent_start']
    initial=files(starts[0])if starts else None
    observations=[files(e)for e in frames]
    mutable=contract['mutable_files'];first=None
    if initial is not None:
        first=next((e for e in frames if any(
            files(e).get(p)!=initial.get(p)for p in mutable)),None)
    call=next((e for e in events if first and first.get('call_id')and e['event']=='tool_call'and e.get('call_id')==first['call_id']),None)
    texts=None;before=None
    for event in events:
            if event is call:break
            store=locations[(event['producer_id'],event['sequence'])]
            snapshot=None
            if event['event']=='request_ready':
                b=event.get('prepared_boundary')or{}
                texts=None
                if call:before=None
                if b.get('expected_journal_ref'):snapshot=b['expected_journal_ref']
                elif 'expected_task_id'in b and b['expected_task_id']is None:
                    texts=[]
                    if call:before=True
            elif event['event']=='state_after_tool':
                b=event.get('state',{});texts=None
                if call:before=None
                snapshot=b.get('journal_ref')
                if b.get('status')=='NO_BOUND_TASK':
                    texts=[]
                    if call:before=True
            if snapshot:
                texts=active_text([json.loads(line)for line in read_object(store,snapshot).decode().splitlines()])
                if call:before=True
    if not call:texts=None
    point=readonly_checkpoint(contract['readonly_paths'],texts,initial,observations,
        changed_boundary_known=before,boundaries_complete=coverage['complete'])
    point['collection_complete']&=coverage['complete']
    opportunity=('OBSERVED_SOURCE_CHANGE'if call else'OBSERVED_CHANGE_ACTION_BOUNDARY_MISSING'if first else
        'NO_OBSERVED_SOURCE_CHANGE_COMPLETE_EPISODE'if coverage['complete']else'UNKNOWN_INCOMPLETE_EXECUTION')
    if not first:
        point.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY'if coverage['complete']else'MISSING_EVIDENCE',
            opportunity_status=opportunity,collection_complete=coverage['complete'])
    timely=memory_rate([item['value']if before is not None and call else None for name,item in point['assertions'].items()
        if name.startswith('remember:')])
    if not first and coverage['complete']:timely=memory_rate([])
    common={k:v for k,v in point['assertions'].items()if k.startswith('preserve:')}
    common_point=checkpoint_verdict({'id':'F35.common.readonly-observed-boundaries-v2',
        'required_assertions':list(common)},{k:v['value']for k,v in common.items()})
    common_point['collection_complete']&=coverage['complete']
    final_texts=None;journals={}
    for event in events:
        store=locations[(event['producer_id'],event['sequence'])]
        b=event.get('prepared_boundary')if event['event']=='request_ready'else event.get('state')if event['event']=='state_after_tool'else None
        if not isinstance(b,dict):continue
        ref=b.get('expected_journal_ref',b.get('journal_ref'));task=b.get('expected_task_id',b.get('task_id'))
        if ref:
            rows=[json.loads(line)for line in read_object(store,ref).decode().splitlines()]
            if task in journals and journals[task]!=rows[:len(journals[task])]:raise ValueError('non-append-only State evidence')
            journals[task]=rows;final_texts=active_text(rows)
        elif ('expected_task_id'in b and b['expected_task_id']is None)or b.get('status')=='NO_BOUND_TASK':final_texts=[]
        else:final_texts=None
    retained=readonly_checkpoint(contract['readonly_paths'],final_texts,initial,observations,
        changed_boundary_known=True,boundaries_complete=coverage['complete'])
    retention=memory_rate([v['value']for k,v in retained['assertions'].items()if k.startswith('remember:')])
    protected={Path(p).name.casefold()for p in contract['readonly_paths']}
    def classified(text):
        match=re.match(r'^(READ_ONLY|ALLOW_MODIFY|READ_WRITE)\s+(\S+)',text)
        if not match:return None
        path=match[2].rstrip(';,')
        if Path(path).name.casefold()not in protected:return None
        return match[1]=='READ_ONLY'and path in contract['readonly_paths']
    creations=[]
    for rows in journals.values():
        for event in rows:
            if event['op']=='append_fact':creations.append(event['fact'])
            elif event['op']=='append_decision':creations.append(event['decision'])
            elif event['op']=='modify_fact':creations.append(event['append_fact']['content'])
    controlled=[value for text in creations if (value:=classified(text))is not None]
    precision=memory_rate(controlled)if final_texts is not None else memory_rate([None])
    pollution=memory_rate([any(classified(t)is False for t in final_texts)])if final_texts is not None else memory_rate([None])
    return {'plugin_memory':point if arm=='pi-memweave'else {'score':None,'status':'DESIGN_NA'},
        'common_constraint':common_point,'first_changed_call_id':first.get('call_id')if first else None,
        'opportunity_status':opportunity,'boundary_coverage':coverage,
        'timely_write':timely,
        'retention':retention,'write_precision':precision,'pollution':pollution,
        'controlled_record_coverage':{'judged_events':len(controlled),'fd_events':len(creations),
            'fraction':len(controlled)/len(creations)if creations else None},
        'scope':'preserved at complete declared public observation boundaries, not proof of no intra-tool transient edits; exact READ_ONLY records required by shared derived overlay'}
