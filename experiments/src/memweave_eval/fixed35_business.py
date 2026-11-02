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


def readonly_checkpoint(required_paths,texts,initial,observations,*,changed_boundary_known):
    checks={}
    for path in required_paths:
        checks['remember:'+path]=None if texts is None else any(
            re.search(r'(?:^|[;\n])\s*READ_ONLY\s+'+re.escape(path)+r'(?=$|[\s,;]|\.(?:$|\s))',text)for text in texts)
        values=[row.get(path)for row in observations]if observations is not None else []
        checks['preserve:'+path]=(all(value==initial[path]for value in values)
            if isinstance(initial,dict)and isinstance(initial.get(path),str)and re.fullmatch(r'[a-f0-9]{64}',initial[path])and values
                and all(isinstance(value,str)for value in values)else None)
    checks['memory_before_first_persistent_change']=changed_boundary_known
    return checkpoint_verdict({'id':'F35.C3.readonly-before-first-change-v1','required_assertions':list(checks)},checks)


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
    initial=files(frames[0])if frames else None
    observations=[files(e)for e in frames]
    mutable=contract['mutable_files'];first=None
    if initial is not None:
        first=next((e for e in frames if any(
            files(e).get(p)!=initial.get(p)for p in mutable)),None)
    call=next((e for e in events if first and first.get('call_id')and e['event']=='tool_call'and e.get('call_id')==first['call_id']),None)
    texts=None;before=False if frames and not first else None
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
    point=readonly_checkpoint(contract['readonly_paths'],texts,initial,observations,
        changed_boundary_known=before)
    timely=memory_rate([item['value']if before is not None else None for name,item in point['assertions'].items()
        if name.startswith('remember:')])
    common={k:v for k,v in point['assertions'].items()if k.startswith('preserve:')}
    common_point=checkpoint_verdict({'id':'F35.common.readonly-boundaries-v1',
        'required_assertions':list(common)},{k:v['value']for k,v in common.items()})
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
    retained=readonly_checkpoint(contract['readonly_paths'],final_texts,initial,observations,changed_boundary_known=True)
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
        'timely_write':timely,
        'retention':retention,'write_precision':precision,'pollution':pollution,
        'controlled_record_coverage':{'judged_events':len(controlled),'fd_events':len(creations),
            'fraction':len(controlled)/len(creations)if creations else None},
        'scope':'all observed request/tool boundaries; exact READ_ONLY path records required by shared derived overlay'}
