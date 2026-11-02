"""Replay multi-stage originals once; cumulative Harbor copies are not new samples."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .engineering_metrics import error_class, quantile
from .evidence_replay import read_object, replay_content
from .finance_metrics import cache_metrics
from .state_metrics import task_state_metrics


def unique_sessions(trial: Path):
    groups=defaultdict(list)
    for path in trial.rglob('*.jsonl'):
        if path.parent.name!='sessions':
            continue
        if path.is_symlink()or not path.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected Session evidence')
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


def collect_episode(trial: Path, *, arm, ledger: Path,auxiliary_roots=(),expected_episode=None):
    records={};requests={};responses={};locations={}
    stores=list(trial.rglob('request-content'))
    for private in auxiliary_roots:
        stores.extend(private.rglob('*-content'))
    for store in sorted(stores):
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
    actor_http=set()
    transport_paths=list(trial.rglob('request-trace.jsonl'))
    actor_paths=set(transport_paths)
    for private in auxiliary_roots:transport_paths.extend(private.rglob('*-transport.jsonl'))
    for path in transport_paths:
        for line in path.read_text().splitlines():
            item=json.loads(line)
            if item.get('event')=='http_attempt':
                transport[item['request_id']]=item
                if path in actor_paths:actor_http.add(item['request_id'])
    if set(requests)!=set(transport):
        raise ValueError('actual HTTP attempts and request content do not match')
    account=json.loads(ledger.read_text())['requests']
    if not set(requests)<=set(account):
        raise ValueError('request bypassed global ledger')
    if expected_episode is not None:
        expected={i for i,r in account.items()if r.get('episode')in {expected_episode,expected_episode+':judge'} and r.get('arm')==arm}
        if set(requests)!=expected:
            raise ValueError('case ledger contains a request absent from the complete actor/auxiliary evidence set')
    tools=defaultdict(lambda:{'attempts':0,'successes':0,'errors':0,'unknown_results':0,
        'durations':[],'error_classes':defaultdict(int)})
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
        if value is True:metric['error_classes'][error_class(ends[key].get('result'))]+=1
        duration=ends.get(key,{}).get('durationMs')
        if type(duration)in (int,float)and duration>=0:metric['durations'].append(duration)
    for metric in tools.values():
        durations=metric.pop('durations');metric['error_classes']=dict(metric['error_classes'])
        metric['duration_ms']={'samples':len(durations),'p50':quantile(durations,.5),'p95':quantile(durations,.95),
            'max':max(durations)if durations else None}
    sessions=unique_sessions(trial)
    archives=sorted(trial.rglob('memory.tar.gz'),key=lambda p:p.stat().st_mtime_ns)
    state=task_state_metrics(sessions,archives[-1] if archives else None,enabled=arm=='pi-memweave')
    settled=[account[i]for i in requests if account[i]['status']=='settled']
    unresolved=[i for i in requests if account[i]['status']!='settled']
    def totals(ids):
        known=[account[i]for i in ids if account[i]['status']=='settled']
        full=len(known)==len(ids)
        values={'input_tokens':sum(r['input']for r in known)if full else None,
            'output_tokens':sum(r['output']for r in known)if full else None}
        raw=[responses.get(i,{}).get('usage')for i in ids]
        values['cache_tokens']=sum(u['prompt_cache_hit_tokens']for u in raw)if raw and all(
            isinstance(u,dict)and type(u.get('prompt_cache_hit_tokens'))is int for u in raw)else None
        return values
    usage=totals(actor_http);all_usage=totals(requests)
    known_usage={'input_tokens':sum(r['input']for r in settled),'output_tokens':sum(r['output']for r in settled)}
    qualified=[i for i in actor_http if responses.get(i,{}).get('stream_done') and
        isinstance(responses[i].get('usage'),dict)and any(
            t.get('function',{}).get('name')=='bash'for t in requests[i].get('tools')or[])]
    return {'collection_complete':not unresolved,'requests':len(requests),
        'actor_http_attempts':len(actor_http),'auxiliary_http_attempts':len(requests)-len(actor_http),
        'completed_unique_actor_agent_calls':len(qualified),
        'usage_assistant_returns':sum(e['event']=='assistant_return'for e in events),
        'known_settled_usage':known_usage,'usage_request_coverage':len(settled)/len(requests)if requests else None,
        'request_ids':sorted(requests),'unsettled_request_ids':unresolved,
        'estimated_usd':sum(r['charge_usd']for r in settled),
        'unsettled_exposure_usd':sum(account[i]['charge_usd']for i in unresolved),
        'usage':usage,'all_role_usage':all_usage,'cache':cache_metrics(usage),
        'all_role_cache':cache_metrics(all_usage),'tools':dict(tools),'state_metrics':state,
        'session_sources':[str(p)for p in sessions],'unique_events':len(events),
        'content_roots':[str(p)for p in stores]}
