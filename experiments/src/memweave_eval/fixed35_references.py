"""Known complete U/A text fidelity, not a full read-budget or image oracle."""
from __future__ import annotations

import json

from .contract_metrics import _item, summarize
from .evidence_replay import read_object
from .fixed35_business import case_events


def known_text_read(source,result,*,read_source):
    expected=source.get('items');actual=(result or{}).get('items')
    if not isinstance(expected,list)or not expected:return summarize([_item('scope',reason='known source arguments missing')])
    if not isinstance(actual,list)or len(actual)!=len(expected):
        return summarize([_item(str(i),reason='read result or item count missing')for i in range(len(expected))])
    checks=[];remaining=source.get('max_total_chars')
    for i,(gold,observed)in enumerate(zip(expected,actual,strict=True)):
        identity=str(i)
        if not isinstance(observed,dict):
            checks.append(_item(identity,reason='structured reference item missing'));continue
        if gold.get('status')!='CAPTURED_KNOWN_TEXT'or not gold.get('source_ref_cas'):
            checks.append(_item(identity,reason='immutable plain-text source unavailable'));continue
        body=read_source(gold['source_ref_cas'])
        offset,limit=gold.get('offset'),gold.get('limit')
        if type(offset)is not int or offset<0 or type(remaining)is not int or remaining<0 or \
            limit is not None and(type(limit)is not int or limit<0):
            checks.append(_item(identity,reason='valid frozen character range or total budget absent'));continue
        wanted=body[offset:offset+min(remaining,limit if limit is not None else len(body))]
        fields={'ref':gold['requested_ref'],'source_task_id':gold['source_task_id'],
            'source_ref':gold['source_ref'],'source_session_id':gold['source_session_id'],'entry_id':gold['entry_id']}
        if any(observed.get(k)!=v for k,v in fields.items()):
            checks.append(_item(identity,False,'source_scope_or_immutable_entry_mismatch'));continue
        if observed.get('source_complete')is not True or observed.get('range_complete')is not True \
            or type(observed.get('truncated'))is not bool or observed.get('status')!='ok':
            checks.append(_item(identity,reason='token pool/partial or image projection requires a separately frozen oracle'));continue
        valid=observed.get('offset')==offset and observed.get('total_chars')==len(body) \
            and observed.get('content')==wanted and gold.get('total_chars')==len(body) \
            and observed['truncated']==(offset>0 or len(wanted)<len(body))
        checks.append(_item(identity,valid,None if valid else'complete_text_range_content_or_unicode_length_mismatch',
            evidence=[gold['source_ref_cas']['sha256']]))
        remaining-=len(wanted)
    return summarize(checks,reason='complete immutable U/A text only; not tokenizer-budget optimality or adoption')


def grade_known_references(trial,*,events=None,locations=None):
    if events is None or locations is None:events,locations=case_events(trial)
    sources={};results={};calls=[]
    for e in events:
        key=e['producer_id'],e.get('call_id')
        if e['event']=='reference_source':sources[key]=e
        if e['event']=='tool_call'and e.get('tool')in {'memory_read','state_read'}:calls.append(key)
        if e['event']=='tool_execution_end'or e['event']=='tool_result'and key not in results:results[key]=e
    items=[]
    for key in calls:
        source=sources.get(key);result=results.get(key)
        if not source or not result:
            items.append(_item(':'.join(str(k)for k in key),reason='known source or actual read result missing'));continue
        store=locations[(result['producer_id'],result['sequence'])]
        row=json.loads(read_object(store,result['record_ref']))
        if row.get('isError')is True and source['source'].get('complete')is True:
            items.append(_item(str(key),False,'error_receipt_for_known_qualifying_reference'));continue
        if type(row.get('isError'))is not bool:
            items.append(_item(str(key),reason='actual tool result success/error status missing'));continue
        try:
            text=next(p['text']for p in row.get('result',row)['content']if p.get('type')=='text')
            actual=json.loads(text)
        except (KeyError,ValueError,StopIteration,TypeError):
            items.append(_item(str(key),False if source['source'].get('complete')is True else None,
                reason='known qualifying read returned invalid structured projection'));continue
        original=locations[(source['producer_id'],source['sequence'])]
        metric=known_text_read(source['source'],actual,read_source=lambda ref,store=original:read_object(store,ref).decode())
        items.extend(dict(item,id=str(key)+':'+item['id'])for item in metric['items'])
    return summarize(items,reason='targeted immutable complete U/A text projection; no calls is zero opportunities; other reads remain unknown')
