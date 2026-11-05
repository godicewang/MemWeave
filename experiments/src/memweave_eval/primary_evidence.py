"""Strict first-case read-only evidence adapter; no inferred semantic retries."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from .finance_metrics import aggregate_cache
from .primary_reconciliation import reconcile, verify_audit
from .primary_report import ctrf_assertions
from .storage import file_digest

COMMON_TOOLS={'read','write','edit','bash'}


def _metric(raw,status='observed',**details):return {'raw':raw,'status':status,**details}


def _events(path,*,pi=False):
    if not path.is_file():return None,'missing'
    rows=[]
    for line in path.read_text().splitlines():
        if not line.strip():continue
        try:
            value=json.loads(line)
            if not isinstance(value,dict):return rows,'invalid'
            rows.append(value)
        except ValueError:
            if pi and not line.lstrip().startswith(('{','[')):continue
            return rows,'invalid'
    return rows,'observed'


def _tools(events,status):
    if status!='observed':return _metric(None,status,reason='missing or malformed original Pi events')
    calls={};invalid=False
    for e in events:
        kind=e.get('type')
        if kind not in {'tool_execution_start','tool_execution_end'}or e.get('toolName')not in COMMON_TOOLS:continue
        identity=e.get('toolCallId')
        if not isinstance(identity,str)or not identity:invalid=True;continue
        call=calls.setdefault(identity,{})
        if kind in call:invalid=True
        call[kind]=e
    s=f=u=0;per_tool={}
    for call in calls.values():
        start=call.get('tool_execution_start');end=call.get('tool_execution_end')
        name=(start or end)['toolName'];counts=per_tool.setdefault(name,{'s':0,'f':0,'u':0,'n':0});counts['n']+=1
        if start and end and start['toolName']!=end['toolName']:invalid=True
        error=end.get('isError')if end else None
        # Missing start is a collection gap, not a fabricated complete attempt.
        kind='u'if not start or type(error)is not bool else'f'if error else's'
        counts[kind]+=1;s+=kind=='s';f+=kind=='f';u+=kind=='u'
    n=len(calls);state='invalid'if invalid else'missing'if u else'not_comparable'if not n else'observed'
    return _metric(s/n if state=='observed'else None,state,support={'s':s,'f':f,'u':u,'n':n},per_tool=per_tool,
                   observed_raw=s/(s+f)if s+f else None,reason='execute attempts of the four common native tools; retries counted separately')


def _transport(events,status):
    missing=_metric(None,status,reason='missing or malformed original transport events')
    if status!='observed':return missing,dict(missing),{'source_status':status},aggregate_cache([])
    by_id={};invalid=False
    keys={'budget_reserved','request_ready','http_attempt','http_response','http_error','budget_settled','request_end'}
    for position,e in enumerate(events):
        kind=e.get('event')
        if kind not in keys:continue
        identity=e.get('request_id')
        if not isinstance(identity,str)or not identity:invalid=True;continue
        row=by_id.setdefault(identity,{})
        if kind in row:invalid=True
        row[kind]=(position,e)
    attempts={k:r for k,r in by_id.items()if 'http_attempt'in r};reserved={k:r for k,r in by_id.items()if 'budget_reserved'in r}
    s=f=u=0;cost=0.;unsettled=[];usages=[];unknown_cache=[]
    for identity,r in attempts.items():
        sequence=[r[k][0]for k in ('budget_reserved','request_ready','http_attempt')if k in r]
        if len(sequence)!=3 or sequence!=sorted(sequence):invalid=True
        end=r.get('request_end',(None,{}))[1];usage=end.get('usage')
        valid_usage=isinstance(usage,dict)and all(type(usage.get(k))is int and usage[k]>=0 for k in ('input','output'))
        http=r.get('http_response',(None,{}))[1].get('status')
        complete=http==200 and end.get('stream_done')is True and valid_usage
        if complete:s+=1
        elif 'http_error'in r or 'request_end'in r or type(http)is int and http!=200:f+=1
        else:u+=1
        usages.append({'input_tokens':usage.get('input')if isinstance(usage,dict)else None,
                       'cache_tokens':usage.get('cache_hit')if isinstance(usage,dict)else None,
                       'output_tokens':usage.get('output')if isinstance(usage,dict)else None})
    for identity,r in reserved.items():
        end=r.get('request_end',(None,{}))[1];bill=r.get('budget_settled',(None,{}))[1].get('charge_usd')
        if end.get('settled')is True and type(bill)in(int,float)and math.isfinite(bill)and bill>=0:cost+=bill
        else:unsettled.append(identity)
        usage=end.get('usage')
        if not isinstance(usage,dict)or usage.get('cache_hit')is None:unknown_cache.append(identity)
        elif type(usage.get('cache_hit'))is not int or type(usage.get('input'))is not int or not 0<=usage['cache_hit']<=usage['input']:invalid=True
    if set(attempts)-set(reserved)or any('budget_settled'in r and k not in reserved for k,r in by_id.items()):invalid=True
    n=len(attempts);service_state='invalid'if invalid else'missing'if u else'not_comparable'if not n else'observed'
    cost_state='invalid'if invalid else'missing'if unsettled or unknown_cache else'not_comparable'if not reserved else'observed'
    return (_metric(s/n if service_state=='observed'else None,service_state,support={'s':s,'f':f,'u':u,'n':n}),
            _metric(cost if cost_state=='observed'else None,cost_state,known_receipt_charge_usd=cost,unsettled_requests=len(unsettled),unknown_cache_requests=len(unknown_cache)),
            {'source_status':'invalid'if invalid else'observed','http_attempts':n,'admitted_requests':len(reserved),
             'unsettled_request_ids':sorted(unsettled),'unknown_cache_request_ids':sorted(unknown_cache),'request_ids':sorted(attempts),'scope':'all roles sharing the guarded transport, including native compaction'},
            aggregate_cache(usages))


def collect_arm(trial:Path,test_names,*,authority=None,arm=None,episode=None,tool_contract=False):
    trial=Path(trial);agent=trial/'agent';events,ps=_events(agent/'pi.txt',pi=True);transport,ts=_events(agent/'request-trace.jsonl')
    service,cost,counts,cache=_transport(transport,ts)
    result={};ctrf={};derived={};issues=[]
    for path,target in [(trial/'result.json',result),(trial/'verifier/ctrf.json',ctrf),(trial/'verifier/derived-ctrf.json',derived)]:
        if path.is_file():
            try:
                value=json.loads(path.read_text())
                if not isinstance(value,dict):raise TypeError('original JSON object required')
                target.update(value)
            except (ValueError,TypeError):issues.append(str(path))
    phase=result.get('agent_execution')or{};seconds=None
    try:
        seconds=(datetime.fromisoformat(phase['finished_at'])-datetime.fromisoformat(phase['started_at'])).total_seconds()
        if not math.isfinite(seconds)or seconds<0:seconds=None
    except (KeyError,ValueError,TypeError):pass
    tests=[]
    for report in (ctrf,derived):
        results=report.get('results');values=results.get('tests')if isinstance(results,dict)else None
        if isinstance(values,list):tests.extend(values)
    integrity={'status':'missing','reason':'independent authority ledger and terminal not provided'}
    if isinstance(authority,dict):
        integrity=reconcile(transport,authority.get('ledger'),authority.get('terminal'),arm=arm,episode=episode)
        audit=verify_audit(authority.get('audit'),authority.get('terminal'));integrity['trusted_audit']=audit
        if audit['status']!='observed':integrity['status']=audit['status']
        if integrity['status']=='observed':
            expected={i for i,r in authority['ledger']['requests'].items()if r.get('arm')==arm and r.get('episode')==episode}
            authoritative=[e for e in authority['audit']if e.get('request_id')in expected]
            service,cost,counts,cache=_transport(authoritative,'observed')
            counts['authority']='credential_isolated_broker'
        else:
            for metric in (service,cost):metric.update(observed_raw=metric['raw'],raw=None,status='missing',reason='actor/authority/terminal reconciliation failed')
    result={'metrics':{'common_tool_rate':_tools(events,ps),'service_complete_rate':service,'model_cost_usd':cost,
        'actor_wall_seconds':_metric(seconds,'observed'if seconds is not None else'missing')},
        'transport':counts,'transport_integrity':integrity,'cache':cache,'assertions':ctrf_assertions({'results':{'tests':tests}},test_names),'parse_issues':issues,
        'original_business_result':{'rewards':(result.get('verifier_result')or{}).get('rewards'),'exception':result.get('exception_info')},
        'sources':{str(p.relative_to(trial)):file_digest(p)for p in [trial/'result.json',trial/'verifier/ctrf.json',trial/'verifier/derived-ctrf.json',agent/'pi.txt',agent/'request-trace.jsonl']if p.is_file()},
        'interpretation':'Business test assertions are bounded task behavior, not proof of valuable State or model adoption.'}
    if tool_contract:
        from .tool_outcomes import tool_contract_metric
        session_events=[];session_status=ps
        session_paths=sorted((agent/'pi/sessions').glob('*.jsonl'))
        if not session_paths:session_status='missing'
        for path in session_paths:
            values,state=_events(path)
            if state!='observed':session_status=state
            session_events.extend(values or[])
        outcomes=tool_contract_metric(events,session_status,sessions=session_events)
        result['metrics']['tool_contract_complete_rate']=outcomes['metric']
        result['tool_outcomes']=outcomes
    return result
