"""Replay multi-stage originals once; cumulative Harbor copies are not new samples."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .evidence_replay import read_object, replay_content
from .finance_metrics import cache_metrics
from .state_metrics import task_state_metrics


def unique_sessions(trial: Path):
    groups=defaultdict(list)
    for path in trial.rglob('*.jsonl'):
        if path.parent.name!='sessions':
            continue
        data=path.read_bytes()
        groups[path.name].append((data,path))
    chosen=[]
    for copies in groups.values():
        copies.sort(key=lambda item:len(item[0]))
        full,path=copies[-1]
        if any(not full.startswith(data) for data,_ in copies):
            raise ValueError('conflicting cumulative Session copies')
        chosen.append(path)
    return chosen


def collect_episode(trial: Path, *, arm, ledger: Path):
    records={};requests={};responses={};locations={}
    for store in sorted(trial.rglob('request-content')):
        replay=replay_content(store)
        for event in replay['events']:
            identity=(event['producer_id'],event['sequence'])
            if identity in records and records[identity]!=event:
                raise ValueError('conflicting copied evaluator event')
            records[identity]=event;locations[identity]=store
        for identity,payload in replay['requests'].items():
            if identity in requests and requests[identity]!=payload:
                raise ValueError('conflicting request copies')
            requests[identity]=payload
        responses.update(replay['responses'])
    events=sorted(records.values(),key=lambda e:(e['timestamp'],e['producer_id'],e['sequence']))
    transport={}
    for path in trial.rglob('request-trace.jsonl'):
        for line in path.read_text().splitlines():
            item=json.loads(line)
            if item.get('event')=='http_attempt':
                transport[item['request_id']]=item
    if set(requests)!=set(transport):
        raise ValueError('actual HTTP attempts and request content do not match')
    account=json.loads(ledger.read_text())['requests']
    if not set(requests)<=set(account):
        raise ValueError('request bypassed global ledger')
    tools=defaultdict(lambda:{'attempts':0,'successes':0,'errors':0,'unknown_results':0})
    calls={};ends={}
    for event in events:
        if event['event'] not in {'tool_call','tool_execution_end','tool_result'}:
            continue
        key=(event['producer_id'],event.get('call_id'))
        record=json.loads(read_object(locations[(event['producer_id'],event['sequence'])],event['record_ref']))
        if event['event']=='tool_call':
            calls[key]=event['tool']
        elif event['event']=='tool_execution_end' or key not in ends:
            ends[key]=record
    for key,name in calls.items():
        value=ends.get(key,{}).get('isError')
        metric=tools[name];metric['attempts']+=1
        metric['unknown_results' if type(value)is not bool else 'errors' if value else 'successes']+=1
    sessions=unique_sessions(trial)
    archives=sorted(trial.rglob('memory.tar.gz'),key=lambda p:p.stat().st_mtime_ns)
    state=task_state_metrics(sessions,archives[-1] if archives else None,enabled=arm=='pi-memweave')
    settled=[account[i]for i in requests if account[i]['status']=='settled']
    unresolved=[i for i in requests if account[i]['status']!='settled']
    usage={'input_tokens':sum(r['input']for r in settled),'output_tokens':sum(r['output']for r in settled)}
    raw=[responses.get(i,{}).get('usage') for i in requests]
    if raw and all(isinstance(u,dict)and type(u.get('prompt_cache_hit_tokens'))is int for u in raw):
        usage['cache_tokens']=sum(u['prompt_cache_hit_tokens']for u in raw)
    else:
        usage['cache_tokens']=None
    return {'collection_complete':not unresolved,'requests':len(requests),
        'usage_assistant_returns':sum(e['event']=='assistant_return'for e in events),
        'request_ids':sorted(requests),'unsettled_request_ids':unresolved,
        'estimated_usd':sum(r['charge_usd']for r in settled),
        'unsettled_exposure_usd':sum(account[i]['charge_usd']for i in unresolved),
        'usage':usage,'cache':cache_metrics(usage),'tools':dict(tools),'state_metrics':state,
        'session_sources':[str(p)for p in sessions],'unique_events':len(events),
        'content_roots':[str(p)for p in trial.rglob('request-content')]}
