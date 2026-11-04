"""Compare actor-owned logs with independent authority and terminal records."""
from __future__ import annotations


def reconcile(events,ledger,terminal,*,arm,episode):
    result={'status':'missing','arm':arm,'episode':episode}
    if not isinstance(events,list)or not isinstance(ledger,dict)or not isinstance(terminal,dict)or terminal.get('schema_version')!='trusted-transport-terminal.v1'or terminal.get('finalized')is not True:
        return result|{'reason':'trusted finalized ledger and terminal records required'}
    entries=terminal.get('entries');requests=ledger.get('requests')
    if not isinstance(entries,list)or not isinstance(requests,dict):return result|{'status':'invalid','reason':'malformed trusted records'}
    matches=[e for e in entries if isinstance(e,dict)and e.get('arm')==arm and e.get('episode')==episode]
    if len(matches)!=1:return result|{'reason':'unique trusted arm/episode terminal required'}
    entry=matches[0];sets={}
    for name in ('admitted_request_ids','http_request_ids','terminal_request_ids'):
        values=entry.get(name)
        if not isinstance(values,list)or any(not isinstance(v,str)or not v for v in values)or len(set(values))!=len(values):
            return result|{'status':'invalid','reason':'trusted ID lists must be explicit and unique'}
        sets[name]=set(values)
    expected={i for i,r in requests.items()if isinstance(r,dict)and r.get('arm')==arm and r.get('episode')==episode}
    if expected!=sets['admitted_request_ids']or not sets['http_request_ids']<=expected or sets['terminal_request_ids']!=expected:
        return result|{'status':'invalid','reason':'authority ledger and terminal disagree'}
    by_event={kind:[]for kind in ('budget_reserved','request_ready','http_attempt','request_end')}
    for e in events:
        if not isinstance(e,dict):return result|{'status':'invalid','reason':'malformed actor event'}
        if e.get('event')in by_event:by_event[e['event']].append(e.get('request_id'))
    if any(any(not isinstance(i,str)for i in ids)or len(ids)!=len(set(ids))for ids in by_event.values()):
        return result|{'status':'invalid','reason':'duplicate or invalid actor request IDs'}
    observed={k:set(v)for k,v in by_event.items()}
    missing=expected-observed['budget_reserved'];extra=observed['budget_reserved']-expected
    missing_http=sets['http_request_ids']-observed['http_attempt'];extra_http=observed['http_attempt']-sets['http_request_ids']
    missing_ready=expected-observed['request_ready'];extra_ready=observed['request_ready']-expected
    missing_end=expected-observed['request_end'];extra_end=observed['request_end']-expected
    gaps=missing|extra|missing_http|extra_http|missing_ready|extra_ready|missing_end|extra_end
    return result|{'status':'invalid_missing'if gaps else'observed','reason':'exact actor/authority/terminal request-set comparison',
        'expected_requests':len(expected),'missing_admitted_ids':sorted(missing),'extra_admitted_ids':sorted(extra),
        'missing_http_ids':sorted(missing_http),'extra_http_ids':sorted(extra_http),
        'missing_ready_ids':sorted(missing_ready),'extra_ready_ids':sorted(extra_ready),
        'missing_end_ids':sorted(missing_end),'extra_end_ids':sorted(extra_end)}


def verify_audit(events,terminal):
    import hashlib
    import json

    if not isinstance(events,list)or not isinstance(terminal,dict)or terminal.get('finalized')is not True:
        return {'status':'missing','reason':'trusted terminal and audit required'}
    previous='0'*64
    for index,event in enumerate(events,1):
        if not isinstance(event,dict):return {'status':'invalid','reason':'malformed trusted audit'}
        value={k:v for k,v in event.items()if k!='event_hash'}
        digest=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        if event.get('sequence')!=index or event.get('previous_hash')!=previous or event.get('event_hash')!=digest:
            return {'status':'invalid','reason':'trusted audit chain mismatch'}
        previous=digest
    if terminal.get('audit_events')!=len(events)or terminal.get('audit_head')!=previous:
        return {'status':'invalid_missing','reason':'whole-tail deletion or terminal mismatch'}
    return {'status':'observed','events':len(events),'head':previous}
