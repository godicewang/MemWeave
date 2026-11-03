"""Independent complete-event checks for uncut, plain-text request windows.

The scope is explicit: eviction, compaction, multimodal and token-truncated
windows require the larger policy oracle and remain missing, never design NA.
"""
from __future__ import annotations

import json
import re

from .contract_metrics import _item, summarize
from .evidence_replay import read_object
from .fixed35_business import case_events

TRANSIENT_PREFIXES=('# Symbolic State','Recent Window 移出提醒：','当前未绑定 Task。\n\n【本次预算快照')


def _text(message):
    content=message.get('content')
    if isinstance(content,str):return content
    if isinstance(content,list):return '\n'.join(p['text']for p in content
        if isinstance(p,dict)and p.get('type')=='text'and isinstance(p.get('text'),str))
    return ''


def _without_protocol_head(message,*,enabled):
    text=_text(message)
    if not enabled:return text
    text=re.sub(r'^\[(?:task_[A-Za-z0-9_-]+:)?[UATR]\d+\](?:\n{1,2})?','',text,count=1)
    marker='[CURRENT_USER_MESSAGE]\nLatest real user request: supersede conflicting earlier user requests; compatible requirements still apply.'
    if text.startswith(marker):text=text[len(marker):].removeprefix('\n\n').removeprefix('\n')
    return text


def small_window_checkpoint(source,payload,*,recent_turns,max_source_bytes=100000,enabled):
    if not isinstance(source,list)or not isinstance(payload,dict)or not isinstance(payload.get('messages'),list):
        return None,'source_or_final_payload_missing',{}
    native=[];pending=set();count=0
    for message in source:
        if not isinstance(message,dict):return None,'malformed_source_message',{}
        role=message.get('role')
        if role=='system':continue
        if role=='assistant'and message.get('stopReason')in {'error','aborted'}:continue
        if role not in {'user','assistant','toolResult'}:return None,'compaction_or_custom_source_requires_policy_oracle',{}
        parts=message.get('content')
        if not isinstance(parts,(str,list))or isinstance(parts,list)and any(not isinstance(p,dict)for p in parts):
            return None,'source_content_schema_missing',{}
        if isinstance(parts,list)and any(p.get('type')not in {'text','toolCall'}for p in parts if isinstance(p,dict)):
            return None,'multimodal_or_reasoning_projection_requires_provider_oracle',{}
        if _text(message).startswith((*TRANSIENT_PREFIXES,'[CURRENT_USER_MESSAGE]')):
            return None,'source_collides_with_transient_message_marker',{}
        if role in {'user','assistant'}:
            if pending:return False,'source_event_is_incomplete',{}
            count+=1
            calls=[p for p in parts or[]if isinstance(p,dict)and p.get('type')=='toolCall']if isinstance(parts,list)else[]
            ids=[p.get('id')for p in calls]
            if len(set(ids))!=len(ids)or any(not isinstance(i,str)for i in ids):return False,'invalid_source_call_identity',{}
            pending=set(ids)
        else:
            identity=message.get('toolCallId')
            if identity not in pending:return False,'source_result_is_unpaired',{}
            pending.remove(identity)
        native.append(message)
    if pending:return None,'incomplete_pending_source_event',{}
    if enabled and(type(recent_turns)is not int or recent_turns<1):
        raise ValueError('frozen positive Recent Window capacity required')
    if enabled and count>recent_turns:return None,'eviction_range_requires_full_policy_oracle',{'source_events':count}
    size=len(json.dumps(native,ensure_ascii=False).encode())
    if size>max_source_bytes:return None,'source_exceeds_frozen_small_window_scope',{'source_bytes':size}
    actual=[]
    for message in payload['messages']:
        if not isinstance(message,dict):return None,'malformed_provider_message',{}
        if message.get('role')=='system':continue
        body=_text(message)
        if enabled and message.get('role')=='user'and body.startswith(TRANSIENT_PREFIXES):continue
        if '[TRUNCATED]'in body or '[TRUNCATED:'in body:
            return None,'truncated_body_requires_frozen_budget_projection_oracle',{}
        actual.append(message)
    checks={'all_native_messages_represented':len(actual)==len(native),'roles_order_text_calls_and_results_preserved':True}
    for expected,observed in zip(native,actual,strict=False):
        role='tool'if expected['role']=='toolResult'else expected['role']
        valid=observed.get('role')==role and _text(expected)==_without_protocol_head(observed,enabled=enabled)
        if expected['role']=='toolResult':valid &= observed.get('tool_call_id')==expected.get('toolCallId')
        if expected['role']=='assistant':
            wanted=[p for p in expected.get('content',[])if isinstance(p,dict)and p.get('type')=='toolCall']
            got=observed.get('tool_calls')or[]
            valid &= isinstance(got,list)and len(wanted)==len(got)
            for call,received in zip(wanted,got,strict=False):
                try:arguments=json.loads(received.get('function',{}).get('arguments'))
                except (ValueError,TypeError):arguments=None
                valid &= received.get('id')==call.get('id')and received.get('function',{}).get('name')==call.get('name')and arguments==call.get('arguments')
        checks['roles_order_text_calls_and_results_preserved'] &= valid
    return all(checks.values()),None if all(checks.values())else'message_event_or_argument_projection_mismatch',checks


def grade_small_windows(trial,request_ids,*,recent_turns,enabled,max_source_bytes=100000):
    events,locations=case_events(trial)
    ready={e['request_id']:e for e in events if e['event']=='request_ready'and e.get('request_id')in request_ids}
    items=[]
    for identity in sorted(request_ids):
        event=ready.get(identity);b=(event or{}).get('prepared_boundary')or{}
        if not event or not event.get('payload_ref')or not isinstance(b.get('source_messages'),list):
            items.append(_item(identity,reason='independent source boundary or HTTP payload missing'));continue
        store=locations[(event['producer_id'],event['sequence'])]
        source=[json.loads(read_object(store,m['source_ref']))for m in b['source_messages']]
        payload=json.loads(read_object(store,event['payload_ref']))
        value,reason,checks=small_window_checkpoint(source,payload,recent_turns=recent_turns,
            max_source_bytes=max_source_bytes,enabled=enabled)
        items.append(dict(_item(identity,value,reason),assertions=checks))
    return dict(summarize(items),scope='Uncut plain-text native event ledger only; no eviction/compaction/token-budget/multimodal proof. '
        'Unsupported actual boundaries remain unknown and block collection acceptance.')
