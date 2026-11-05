"""Interface receipt conformance and separate action outcome categories.

An assertion failing inside a correctly executed shell is not a malformed tool
interface. These categories diagnose recorded results, not intrinsic fault cause.
"""
from __future__ import annotations

from .primary_evidence import COMMON_TOOLS


def tool_contract_metric(events, status, *, sessions=None):
    if status != 'observed':
        return {'metric': {'raw': None, 'status': status}, 'calls': []}
    calls, duplicate = {}, False
    for e in events:
        kind = e.get('type')
        if kind not in ('tool_execution_start', 'tool_execution_end') or e.get('toolName') not in COMMON_TOOLS:
            continue
        identity = e.get('toolCallId')
        if not isinstance(identity, str) or not identity:
            duplicate = True
            continue
        row = calls.setdefault(identity, {})
        if kind in row:
            duplicate = True
        row[kind] = e
    rows, s, f, u = [], 0, 0, 0
    for identity, events_for_call in calls.items():
        start, end = (events_for_call.get(k) for k in ('tool_execution_start', 'tool_execution_end'))
        result = end.get('result') if end else None
        if not start or not end:
            u += 1
            rows.append({'call_id': identity, 'outcome_category': 'unknown_incomplete_receipt'})
            continue
        content = result.get('content') if isinstance(result, dict) else None
        valid = (start['toolName'] == end['toolName'] and type(end.get('isError')) is bool
                 and isinstance(content, list) and all(isinstance(b, dict) and b.get('type') in ('text', 'image')
                    and (isinstance(b.get('text'), str) if b['type'] == 'text' else isinstance(b.get('data'), str)) for b in content))
        s += bool(valid)
        f += not valid
        structured = result.get('structuredContent', {}) if isinstance(result, dict) else {}
        code = structured.get('exit_code') if isinstance(structured, dict) else None
        text = '\n'.join(b.get('text', '') for b in content if isinstance(b, dict)) if isinstance(content, list) else ''
        if not valid:
            category = 'tool_interface_contract_error'
        elif end['isError'] is False:
            category = 'success'
        elif start['toolName'] != 'bash':
            category = 'tool_operation_rejected'
        elif code == 127:
            category = 'environment_missing_dependency'
        elif 'AssertionError' in text or 'FAILED ' in text or '\nDIFF ' in '\n'+text:
            category = 'business_assertion_failure'
        else:
            category = 'command_nonzero_other'
        rows.append({'call_id': identity, 'tool': start['toolName'], 'interface_valid': valid,
                     'is_error': end.get('isError'), 'exit_code': code, 'outcome_category': category})
    source_issue = None
    if sessions is not None:
        assistant_calls, results = {}, {}
        for entry in sessions:
            message = entry.get('message') or {}
            if message.get('role') == 'assistant':
                for block in message.get('content', []):
                    if isinstance(block, dict) and block.get('type') == 'toolCall' and block.get('name') in COMMON_TOOLS:
                        identity = block.get('id')
                        if identity in assistant_calls:
                            source_issue = 'duplicate_original_session_call'
                        assistant_calls[identity] = block
            if message.get('role') == 'toolResult' and message.get('toolName') in COMMON_TOOLS:
                identity = message.get('toolCallId')
                if identity in results:
                    source_issue = 'duplicate_original_session_result'
                results[identity] = message
        if set(assistant_calls) != set(calls) or set(results) != set(calls):
            source_issue = 'original_session_call_result_set_mismatch'
        for identity, call in calls.items():
            end, result, original_call = call.get('tool_execution_end'), results.get(identity), assistant_calls.get(identity)
            if end and result and original_call and (result.get('toolName') != end['toolName']
                    or original_call.get('name') != end['toolName'] or result.get('isError') != end.get('isError')
                    or result.get('content') != (end.get('result') or {}).get('content')):
                source_issue = 'original_session_receipt_disagrees'
    n = len(calls)
    state = 'invalid' if duplicate else 'missing' if u else 'not_comparable' if not n else 'observed'
    if source_issue:
        state = 'missing'
    return {'metric': {'raw': s/n if state == 'observed' else None, 'status': state,
            'support': {'s': s, 'f': f, 'u': u, 'n': n},
            'reason': 'Interface receipt shape/identity only; business command failures remain separate, not intrinsic tool reliability'},
            'calls': rows, 'classification_version': 'tool-outcomes.v1', 'source_issue': source_issue}
