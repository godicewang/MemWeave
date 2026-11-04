"""Replay multi-stage originals once; cumulative Harbor copies are not new samples."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from .engineering_metrics import episode_telemetry, error_class, quantile
from .evidence_replay import read_object, replay_content
from .finance_metrics import cache_metrics
from .state_metrics import task_state_metrics

TRACKED_TOOLS=('bash','edit','modify_fact','read','state_append','task_clarify','task_create','write')


def known_zero_tools(tools,*,complete):
    """Only a complete independent execution log establishes zero opportunities."""
    result=dict(tools)
    if complete:
        for name in TRACKED_TOOLS:
            result.setdefault(name,{'attempts':0,'successes':0,'errors':0,'unknown_results':0,
                'executions':0,'error_classes':{},'duration_ms':{'samples':0,'p50':None,'p95':None,'max':None}})
    return result


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


def qualified_actor_calls(requests,responses,*,fixture_control=False):
    if fixture_control:return []
    result=[]
    for identity,payload in requests.items():
        response=responses.get(identity,{})
        usage=response.get('usage')or{}
        if (response.get('http_status')in range(200,300)and response.get('stream_done')is True
            and response.get('successful_finish')is True and response.get('assistant_payload_present')is True
            and response.get('provider_error')is False and type(usage.get('prompt_tokens'))is int
            and usage['prompt_tokens']>0 and type(usage.get('completion_tokens'))is int
            and usage['completion_tokens']>0 and any(t.get('function',{}).get('name')=='bash'
                for t in payload.get('tools')or[])):
            result.append(identity)
    return result


def tool_metrics(events,locations):
    tools=defaultdict(lambda:{'attempts':0,'successes':0,'errors':0,'unknown_results':0,
        'durations':[],'executions':0,'invalid_duration_records':0,'error_classes':defaultdict(int)})
    calls={};ends={}
    for event in events:
        if event['event']not in {'tool_call','tool_execution_start','tool_execution_end','tool_result'}:continue
        key=event['producer_id'],event.get('call_id')
        record=json.loads(read_object(locations[event['producer_id'],event['sequence']],event['record_ref']))
        if event['event']in {'tool_call','tool_execution_start'}:
            name=event.get('tool')
            if not isinstance(name,str)or not name or key in calls and calls[key]!=name:
                raise ValueError('conflicting or missing observed tool identity')
            calls[key]=name
        elif event['event']=='tool_execution_end'or key not in ends:ends[key]=record
    for key,name in calls.items():
        end=ends.get(key,{});value=end.get('isError');metric=tools[name];metric['attempts']+=1
        metric['unknown_results'if type(value)is not bool else'errors'if value else'successes']+=1
        if value is True:metric['error_classes'][error_class(end.get('result'))]+=1
        if 'durationMs'in end:
            duration=end['durationMs']
            if type(duration)in (int,float)and math.isfinite(duration)and duration>=0:
                metric['durations'].append(duration);metric['executions']+=1
            else:metric['invalid_duration_records']+=1
    for metric in tools.values():
        values=metric.pop('durations');metric['error_classes']=dict(metric['error_classes'])
        if metric['invalid_duration_records']:metric['executions']=None
        metric['duration_ms']={'samples':len(values),'p50':quantile(values,.5),'p95':quantile(values,.95),
            'max':max(values)if values else None}
        metric['execution_scope']='Pi1.4 timed execute-end only; native start includes argument/preparation rejection'
    return dict(tools)


def collect_episode(trial: Path, *, arm, ledger: Path,auxiliary_roots=(),expected_episode=None,fixture_control=False):
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
    transport={};transport_records=[]
    actor_http=set()
    transport_paths=list(trial.rglob('request-trace.jsonl'))
    if fixture_control:transport_paths.extend(trial.rglob('cli-request-trace.jsonl'))
    actor_paths=set(transport_paths)
    for private in auxiliary_roots:transport_paths.extend(private.rglob('*-transport.jsonl'))
    for path in transport_paths:
        for line in path.read_text().splitlines():
            item=json.loads(line)
            transport_records.append(item)
            if item.get('event')=='http_attempt':
                if item['request_id']in transport and transport[item['request_id']]!=item:
                    raise ValueError('conflicting HTTP attempt copies')
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
    tools=tool_metrics(events,locations)
    sessions=unique_sessions(trial)
    archives=sorted(trial.rglob('memory.tar.gz'),key=lambda p:p.stat().st_mtime_ns)
    from .fixed35_business import execution_boundaries
    from .stage_execution import stage_execution
    from .state_journal_sources import registry_journals
    boundary=execution_boundaries(trial,events)
    stages=stage_execution(trial,events)
    source=registry_journals(events,locations,complete=boundary['complete']and stages['evidence_complete']is True)if arm=='pi-memweave'else {'complete':False}
    state=task_state_metrics(sessions,archives or None,enabled=arm=='pi-memweave',
        committed_journals=source.get('journals'),baseline_journals=source.get('baseline'),
        episode_returns=sum(e['event']=='assistant_return'for e in events),require_initial_inventory=True)
    state['registry_recovery_evidence']={k:v for k,v in source.items()if k not in {'journals','baseline'}}
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
    qualified=qualified_actor_calls({i:requests[i]for i in actor_http},responses,fixture_control=fixture_control)
    from .contract_evidence import confirmed_receipts
    from .fixed35_delivery import delivery_metrics
    receipts=confirmed_receipts(sessions,source.get('journals'),complete=source['complete'])if arm=='pi-memweave'else None
    delivery=delivery_metrics(transport_records,actor_http,enabled=arm=='pi-memweave',confirmed_receipts=receipts,request_payloads=requests)
    tools=known_zero_tools(tools,complete=boundary['complete'])
    from .fixed35_references import grade_known_references
    references=grade_known_references(trial,events=events,locations=locations)
    return {'collection_complete':not unresolved and boundary['complete']and delivery['complete']and stages['evidence_complete']is True,
        'stage_execution':stages,'protocol_execution_complete':stages['protocol_execution_complete'],
        'fixture_control':fixture_control,
        'transport_collection_complete':not unresolved,'execution_boundary_collection':boundary,'requests':len(requests),
        'delivery_metrics':delivery,
        'episode_engineering':episode_telemetry(events,transport_records,actor_http),
        'known_reference_integrity':references,
        'actor_http_attempts':len(actor_http),'auxiliary_http_attempts':len(requests)-len(actor_http),
        'completed_unique_actor_agent_calls':len(qualified),
        'completed_unique_actor_agent_call_ids':sorted(qualified),
        'usage_assistant_returns':sum(e['event']=='assistant_return'for e in events),
        'known_settled_usage':known_usage,'usage_request_coverage':len(settled)/len(requests)if requests else None,
        'request_ids':sorted(requests),'unsettled_request_ids':unresolved,
        'requested_models':sorted({requests[i].get('model')for i in actor_http if isinstance(requests[i].get('model'),str)}),
        'ledger_path':str(ledger.resolve()),
        'estimated_usd':sum(r['charge_usd']for r in settled),
        'unsettled_exposure_usd':sum(account[i]['charge_usd']for i in unresolved),
        'usage':usage,'all_role_usage':all_usage,'cache':cache_metrics(usage),
        'all_role_cache':cache_metrics(all_usage),'tools':dict(tools),'state_metrics':state,
        'session_sources':[str(p)for p in sessions],'unique_events':len(events),
        'content_roots':[str(p)for p in stores]}
