"""Adapt existing Pi/State originals to v2 contracts without fabricating boundaries."""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path

from .contract_metrics import (
    _item,
    logical_operation_metrics,
    reference_integrity,
    state_freshness,
    summarize,
    window_integrity,
)
from .engineering_metrics import read_events
from .state_metrics import _committed, _sessions, stable_id


def _journal(archive):
    valid, _ = _committed(archive)
    if valid is None:
        return None
    tasks = {}
    with tarfile.open(archive) as source:
        for member in source:
            if member.isfile() and member.name.endswith('/state.json'):
                task = Path(member.name).parent.name
                lines = source.extractfile(member).read().decode().splitlines()
                tasks[task] = {json.loads(line)['op_id']: version
                               for version, line in enumerate(lines, 1)}
    return tasks


def _receipts(paths, journal):
    sessions, errors = _sessions(paths)
    if errors or journal is None:
        return None
    receipts = {}
    for header, entries, _ in sessions:
        by_id = {e.get('id'): e for e in entries}
        for entry in entries:
            message = entry.get('message') or {}
            if message.get('role') != 'toolResult' or message.get('isError') is not False:
                continue
            text = '\n'.join(p.get('text', '') for p in message.get('content', [])
                             if isinstance(p, dict) and p.get('type') == 'text')
            call_id = message.get('toolCallId')
            associations = set()
            if message.get('toolName') == 'task_create':
                try:
                    result = json.loads(text)
                    task, version = result.get('task_id'), result.get('state_version')
                    if task in journal and type(version) is int and 0 < version <= len(journal[task]):
                        associations.add((task, version))
                except (ValueError, AttributeError):
                    pass
            else:
                match = re.fullmatch(r'State updated: v(\d+)\s*', text)
                parent, visited, caller = entry.get('parentId'), set(), None
                while parent in by_id and parent not in visited:
                    visited.add(parent)
                    ancestor = by_id[parent]
                    parts = (ancestor.get('message') or {}).get('content') or []
                    found = next((p for p in parts if isinstance(p, dict) and
                                  p.get('type') == 'toolCall' and p.get('id') == call_id), None)
                    if found:
                        caller = (ancestor.get('id'), found)
                        break
                    parent = ancestor.get('parentId')
                if match and caller and isinstance(header.get('id'), str):
                    assistant, call = caller
                    args = call.get('arguments') or {}
                    for task, operations in journal.items():
                        base = stable_id(task, header['id'], assistant, call_id)
                        if call.get('name') == 'state_append' and isinstance(args.get('items'), list):
                            ids = [stable_id(base, n) for n in range(len(args['items']))]
                        elif call.get('name') in ('modify_fact', 'update_goal'):
                            ids = [base]
                        else:
                            ids = []
                        version = int(match[1])
                        if ids and all(i in operations for i in ids) and max(operations[i] for i in ids) <= version <= len(operations):
                            associations.add((task, version))
            if associations:
                receipts.setdefault(call_id, set()).update(associations)
    return receipts


def causal_state_minimum(requests, receipts, *, enabled):
    """Only a lower-bound contract: visible acknowledged writes precede preparation.

    This deliberately does not call journal.time a commit time, nor claim that the
    current shared Task could not have newer concurrent writes.
    """
    if not enabled:
        return summarize([_item('scope', reason='State unavailable in native mode', na=True)])
    checks = []
    for request in requests:
        identity = request.get('request_id')
        if receipts is None:
            checks.append(_item(identity, reason='journal_or_receipt_provenance_missing'))
            continue
        visible = [m.get('tool_call_id') for m in request.get('messages', []) if m.get('role') == 'tool']
        observed = [receipts[c] for c in visible if c in receipts]
        if any(len(values) != 1 for values in observed):
            checks.append(_item(identity, reason='ambiguous_reused_tool_call_identity'))
            continue
        versions = [next(iter(v)) for v in observed]
        if not versions:
            checks.append(_item(identity, reason='no_visible_confirmed_write_dependency', na=True))
            continue
        blocks = request.get('state_blocks')
        if not isinstance(blocks, list) or len(blocks) != 1:
            checks.append(_item(identity, reason='current_scope_or_State_block_missing'))
            continue
        task = blocks[0].get('task_id')
        required = [v for t, v in versions if t == task]
        delivered = blocks[0].get('version')
        if not required or type(delivered) is not int:
            checks.append(_item(identity, reason='no_confirmed_version_for_delivered_scope'))
        else:
            value = delivered >= max(required)
            checks.append(dict(_item(identity, value, None if value else 'older_than_visible_write_receipt',
                                     evidence=[c for c in visible if c in receipts]),
                               task_id=task, minimum_confirmed_version=max(required), delivered_version=delivered))
    return summarize(checks)


def task_contract_metrics(agent: Path, *, enabled, contracts=None):
    contracts = contracts or {}
    tools, tool_status = read_events(agent/'pi.txt')
    trace, trace_status = read_events(agent/'request-trace.jsonl')
    requests = [e for e in trace if e.get('event') == 'request_ready']
    if tool_status == 'available' and (agent/'pi.txt').stat().st_size and not any(
            e.get('type') in ('tool_execution_start', 'tool_execution_end', 'agent_start', 'agent_end') for e in tools):
        tool_status = 'legacy_no_execution_telemetry'
    paths = list((agent/'pi/sessions').glob('*.jsonl'))
    if trace_status == 'available' and not requests:
        sessions, _ = _sessions(paths)
        if any((e.get('message') or {}).get('role') == 'assistant' and
               isinstance((e.get('message') or {}).get('usage'), dict)
               for _, entries, _ in sessions for e in entries):
            trace_status = 'request_boundaries_missing'
    journal = _journal(agent/'memory.tar.gz') if enabled else None
    receipts = _receipts(paths, journal) if enabled else None
    boundaries = contracts.get('request_boundaries', {})
    strict_requests = [dict(e, **boundaries.get(e.get('request_id'), {})) for e in requests]
    strict = state_freshness(contracts.get('state_commits', []), strict_requests,
                             commits_complete=contracts.get('state_commits_complete') is True, enabled=enabled)
    windows = contracts.get('window_observations')
    if windows is None:
        # A hash of an assistant message does not expose its tool call IDs.
        windows = [{'window_id': e.get('request_id')} for e in requests]
    references = contracts.get('reference_observations')
    if references is None:
        references = [{'read_id': e.get('toolCallId')} for e in tools
                      if e.get('type') == 'tool_execution_end' and e.get('toolName') in ('memory_read', 'state_read')]
    result = {
        'version': 'mechanical-contracts-v2', 'source_status': {'tools': tool_status, 'requests': trace_status},
        'logical_operations': logical_operation_metrics(tools, contracts.get('logical_operations')),
        'state_latest_at_prepare': strict,
        'state_confirmed_receipt_lower_bound': causal_state_minimum(requests, receipts, enabled=enabled),
        'reference_integrity': reference_integrity(contracts.get('reference_gold', []), references),
        'window_integrity': window_integrity(contracts.get('window_gold', []), windows),
        'interpretation': 'Causal State minimum is not global latest; mechanical fidelity is not semantic adoption',
    }
    if trace_status != 'available':
        for field in ('state_latest_at_prepare', 'state_confirmed_receipt_lower_bound', 'window_integrity'):
            if enabled or field == 'window_integrity':
                result[field].update(status='unknown', numerator=None, denominator=None, unknown=None,
                                     reason='request_trace_missing', value=None, coverage=None)
    if tool_status != 'available':
        for field in ('recovery', 'retry_load'):
            result['logical_operations'][field].update(status='unknown', numerator=None, denominator=None,
                                                       unknown=None, reason='tool_trace_missing', value=None)
        result['reference_integrity'].update(status='unknown', reason='tool_trace_missing',
                                            value=None, numerator=None, denominator=None, unknown=None)
    return result
