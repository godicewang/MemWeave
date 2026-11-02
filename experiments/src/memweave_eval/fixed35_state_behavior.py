"""Evaluator-only STATE assertions; official LLM outcome remains a separate channel.

Text predicates are versioned English case parsers, not a general intent classifier.
Application snapshots are checked at every observed domain-tool boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .fixed35 import checkpoint_verdict
from .storage import file_digest

VERSION = 'fixed35-state-business-20261102-v1'
CASES = {
    'INT-01': ('customer_support', '48-hard_ambiguous_accessory_reference_no_guess'),
    'INT-02': ('customer_support', '13-cancel_named_then_ambiguous_accessory'),
    'INT-03': ('customer_support', '117-hard_exchange_user_pivots_to_return'),
    'INT-04': ('travel', '47-adversarial_conflicting_cabin_claim'),
    'INT-05': ('travel', '50-adversarial_mind_change'),
}


def state_contract(source: Path, case_id: str):
    domain, task_id = CASES[case_id]
    path = source / 'state_bench/domains' / domain / 'tasks' / (task_id + '.json')
    task = json.loads(path.read_text())
    return {'version': VERSION, 'case_id': case_id, 'task_id': task_id,
        'source_task_sha256': file_digest(path), 'requirements': task['state_requirements'],
        'scope': 'original final-state fields, protected records and explicit domain boundaries; '
                 'finite English quote/clarification/pivot predicates; not the official LLM judge'}


def _point(identity, values):
    return checkpoint_verdict({'id': VERSION + ':' + identity,
        'required_assertions': list(values)}, values)


def _field(snapshot, table, key, field):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get(table), dict):
        return None, False
    record = snapshot[table].get(key)
    return (record[field], True) if isinstance(record, dict) and field in record else (None, False)


def state_points(contract, *, initial, snapshots, conversation, calls, complete):
    """Pure predicates. Missing values stay unknown; a known violation stays failure."""
    case_id = contract['case_id']
    targets={(r['entity_type'],r['record_key'])for r in contract['requirements']}
    if case_id=='INT-05':targets.add(('bookings','BK-A07'))
    initial_valid=isinstance(initial,dict)and all(isinstance(initial.get(table),dict)
        and isinstance(initial[table].get(key),dict)for table,key in targets)
    complete=complete is True and initial_valid and isinstance(snapshots,list)and bool(snapshots) \
        and all(isinstance(s,dict)for s in snapshots)
    final = snapshots[-1] if snapshots else None
    values = {}
    for requirement in contract['requirements']:
        table, key, field = (requirement[n] for n in ('entity_type', 'record_key', 'field'))
        value, present = _field(final, table, key, field)
        values[f'{table}:{key}:{field}'] = value == requirement['expected_value'] if present else None
    # INT-05 has no original state requirements: an empty AND must not pass.
    final_point = _point('original-required-state', values) if values else None
    allowed = {(r['entity_type'], r['record_key']) for r in contract['requirements']}
    protected = {}
    if isinstance(initial, dict):
        protected['entity_table_set'] = False if any(isinstance(s, dict) and set(s) != set(initial) for s in snapshots) else True if complete and snapshots else None
        for table, records in initial.items():
            if not isinstance(records, dict):
                continue
            protected[table + ':record_set'] = False if any(not isinstance(s.get(table), dict) or set(s[table]) != set(records) for s in snapshots if isinstance(s, dict)) else True if complete and snapshots else None
            for key, record in records.items():
                if (table, key) in allowed:
                    continue
                observed = [s.get(table, {}).get(key) for s in snapshots if isinstance(s, dict)]
                violation = any(value != record for value in observed)
                protected[f'{table}:{key}'] = False if violation else True if complete and snapshots else None
    protected_point = _point('protected-records-at-domain-boundaries', protected or {'initial_snapshot_present': None})
    messages = conversation if isinstance(conversation, list) else None
    turns = None
    if messages is not None and all(isinstance(m, dict) and m.get('role') in {'user', 'assistant'}
            and isinstance(m.get('content'), str) for m in messages):
        turns = []; index = -1
        for message in messages:
            if message['role'] == 'user':
                index += 1
            turns.append((index, message['role'], message['content']))
    known_calls = isinstance(calls, list) and all(isinstance(c, dict)
        and type(c.get('conversation_turn')) is int and isinstance(c.get('arguments'), dict)
        and isinstance(c.get('name'), str) for c in calls)
    def found(role, pattern):
        return [i for i, r, text in turns if r == role and re.search(pattern, text, re.IGNORECASE)] if turns is not None else None
    def any_known(items):
        return None if items is None else bool(items)
    semantic = {}
    if case_id in {'INT-01', 'INT-02'}:
        questions = found('assistant', r'(?:which|clarif\w*|identify|specify).{0,100}(?:item|add.on|accessor(?:y|ies)|hub|case)')
        semantic['asked_which_accessory'] = any_known(questions)
        if case_id == 'INT-01':
            identified = found('user', r'(?:meant|mean|return|the|7.port|usb.c)\s+(?:usb.c\s+)?hub\b')
            writes = [c for c in calls if c['name'] in {'process_return', 'process_refund'}] if known_calls else None
            semantic['target_reply_after_question'] = None if questions is None or identified is None else any(q < u for q in questions for u in identified)
            semantic['no_return_or_refund_before_reply'] = None if writes is None or identified is None else bool(identified) and all(c['conversation_turn'] >= min(identified) for c in writes)
            semantic['return_targets_hub_only'] = None if writes is None else bool(writes) and all(c['arguments'].get('item_id') == 'ITEM-10417' for c in writes)
        else:
            # Named headphones may be cancelled before asking about the second item.
            cancellations = [c for c in calls if c['name'] == 'cancel_order'] if known_calls else None
            semantic['only_named_headphones_cancelled'] = None if cancellations is None else bool(cancellations) and all(c['arguments'].get('item_ids') == ['ITEM-10575'] for c in cancellations)
    elif case_id == 'INT-03':
        pivots = found('user', r'(?:return.{0,35}(?:instead|shoes)|(?:instead|go ahead|rather).{0,35}return)')
        returns = [c for c in calls if c['name'] == 'process_return'] if known_calls else None
        exchanges = [c for c in calls if c['name'] == 'process_exchange'] if known_calls else None
        semantic['explicit_return_pivot_observed'] = any_known(pivots)
        semantic['return_after_pivot'] = None if pivots is None or returns is None else bool(pivots and returns) and all(c['conversation_turn'] >= min(pivots) for c in returns)
        semantic['no_exchange_after_pivot'] = None if pivots is None or exchanges is None else bool(pivots) and not any(c['conversation_turn'] >= min(pivots) for c in exchanges)
    elif case_id == 'INT-04':
        reads = [i for i, c in enumerate(calls) if c['name'] == 'get_booking' and c['arguments'].get('booking_id') == 'BK-A04'] if known_calls else None
        cancels = [i for i, c in enumerate(calls) if c['name'] == 'cancel_booking' and c['arguments'].get('booking_id') == 'BK-A04'] if known_calls else None
        semantic['authoritative_booking_lookup_before_cancel'] = None if reads is None or cancels is None else bool(reads and cancels) and min(reads) < min(cancels)
    else:
        cancel_quotes = found('assistant', r'(?:cancel\w*.{0,80}\$?57\b|\$57\b.{0,80}cancel\w*)')
        change_quotes = found('assistant', r'(?:chang\w*.{0,80}\$?150\b|\$150\b.{0,80}chang\w*)')
        withdrawal = found('user', r'(?:keep|leave).{0,45}(?:unchanged|as.is|alone|booking|reservation)|(?:do not|don.t|not to).{0,25}(?:cancel|change)')
        semantic['cancel_fee_57_quoted'] = any_known(cancel_quotes)
        semantic['change_fee_150_quoted'] = any_known(change_quotes)
        semantic['user_withdrawal_after_both_quotes'] = None if any(x is None for x in (cancel_quotes, change_quotes, withdrawal)) else any(c <= h < w for c in cancel_quotes for h in change_quotes for w in withdrawal)
        semantic['no_mutation_at_every_observed_domain_boundary'] = protected_point['score'] == 100 if protected_point['collection_complete'] else None
    behavior = _point(case_id + '-behavior', semantic)
    def passed(point):
        return False if point['score'] == 0 else True if point['score'] == 100 and point['collection_complete'] else None
    required = {'protected_records': passed(protected_point), 'case_behavior': passed(behavior)}
    if final_point is not None:
        required['all_original_state_requirements'] = passed(final_point)
    result = _point(case_id + '-all-required-program-assertions', required)
    result.update(points={'final_state': final_point, 'protected_records': protected_point, 'behavior': behavior},
        version=VERSION, parser_scope=contract['scope'])
    return result


def grade_state_trial(private: Path, contract, *, arm=None):
    try:
        return _grade_state_trial(private, contract, arm=arm)
    except (OSError, ValueError, KeyError, TypeError):
        return {'score': None, 'status': 'MISSING_EVIDENCE', 'collection_complete': False,
            'reason': 'STATE evidence is truncated, malformed, or cannot be read; repair before acceptance',
            'version': VERSION}


def _grade_state_trial(private: Path, contract, *, arm):
    journal = private / 'domain-events.jsonl'
    paths = [journal, private / 'domain-events.mirror.jsonl', private / 'domain-events.start.json',
        private / 'domain-events.end.json', private / 'state-trajectory-original.json']
    if not all(p.is_file() for p in paths):
        return {'score': None, 'status': 'MISSING_EVIDENCE', 'collection_complete': False,
            'reason': 'STATE domain journal/mirror/start/end/original trajectory missing', 'version': VERSION}
    raw = journal.read_bytes(); start = json.loads(paths[2].read_text()); end = json.loads(paths[3].read_text())
    calls = [json.loads(line) for line in raw.splitlines()]
    trajectory = json.loads(paths[4].read_text())
    valid = isinstance(start.get('before'), dict) and isinstance(end.get('after'), dict) \
        and paths[1].read_bytes() == raw and end.get('complete') is True and end.get('fatal_error') is None \
        and end.get('sha256') == hashlib.sha256(raw).hexdigest() and end.get('calls') == len(calls)
    valid &= all(isinstance(start.get(k), str) and bool(start[k]) and end.get(k) == start[k]
        for k in ('case_id', 'arm', 'run_id'))
    identities = [c.get('call_id') for c in calls]
    valid &= all(isinstance(i, str) and i for i in identities) and len(identities) == len(set(identities))
    previous = start.get('before')
    for row in calls:
        valid &= isinstance(row.get('before'), dict) and isinstance(row.get('after'), dict) \
            and row.get('before') == previous and all(row.get(k) == start.get(k) for k in ('case_id', 'arm', 'run_id'))
        previous = row.get('after')
    valid &= previous == end.get('after') and start.get('case_id') == contract['case_id'] \
        and trajectory.get('task_id') == contract['task_id']
    if arm is not None:valid &= start.get('arm') == arm
    if not valid:
        return {'score': None, 'status': 'MISSING_EVIDENCE', 'collection_complete': False,
            'reason': 'STATE journal identity, mirror, boundary chain, count or terminal hash mismatch', 'version': VERSION}
    result = state_points(contract, initial=start.get('before'),
        snapshots=[r.get('after') for r in calls] + [end.get('after')],
        conversation=trajectory.get('conversation'), calls=calls, complete=True)
    result['evidence_sha256'] = {p.name: file_digest(p) for p in paths}
    return result
