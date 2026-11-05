"""Independent capture, memory delivery and bounded business predicates for TB-01.

No predicate infers mental adoption or a causal memory benefit. Historical v1 is
left executable; this module is selected only by the new frozen v2 contract.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path

from .tb01_capsules import (
    GOLD,
    NOTE,
    _journals,
    _read_jsonl,
    _replay_prefixes,
    collect_capsules,
    truth,
)
from .tb01_capsules import (
    PUBLIC_PROTOCOL as V1_PUBLIC_PROTOCOL,
)

PROTOCOL = 'tb01-capsule.v2'
PUBLIC_PROTOCOL = V1_PUBLIC_PROTOCOL.replace('TB01-capsule.v1', 'TB01-capsule.v2').replace(
    'Before first editing evaluate.py/scheduler.py (row), evaluate.py/scoring.py (pmi), or generation.py/byte_stops.py (stop), explicitly consult the saved current capsules: state_read if State is available, otherwise the read tool on the note file. Consult them again after your final source changes and before your final response. Merely saying you checked does not substitute for a read.',
    'Persist the correct current capsules before first editing evaluate.py/scheduler.py (row), evaluate.py/scoring.py (pmi), or generation.py/byte_stops.py (stop). At those decisions and when preparing your final response, the current capsules should be available through your memory interface: automatic current State injection is sufficient; otherwise use an ordinary read of the note or a dedicated State read as appropriate. No extra read is required when the correct current content is already present. This protocol checks persistence, actual memory-channel delivery and business behavior separately; no step substitutes for implementing the complete task.',
)


def assertion_ids():
    return {f'flow:{key}:{group}:{leaf}' for key in GOLD for group, leaves in {
        'capture': ('schema', 'values', 'no_conflict'),
        'delivery': ('at_action', 'at_final'), 'behavior': ('probe1', 'probe2'),
    }.items() for leaf in leaves}


def _read_projection_issues(agent, requests, starts, variant):
    """An empty parser summary cannot silently turn a real delivered read into 0."""
    results, refs, issues = {}, {}, []
    for path in sorted((agent/'pi/sessions').glob('*.jsonl')):
        for entry in _read_jsonl(path) or []:
            m = entry.get('message') or {}
            if m.get('role') == 'toolResult':
                results.setdefault(m.get('toolCallId'), []).append((entry.get('id'), m))
            if entry.get('customType') == 'memweave.references.v1':
                data = entry.get('data') or {}
                for b in data.get('bindings', []):
                    refs.setdefault(b.get('entry_id'), set()).add((b.get('ref'), data.get('task_id')))
    for _, q in requests:
        for wire in q.get('messages', []):
            identity = wire.get('tool_call_id')
            start = starts.get(identity)
            if wire.get('role') != 'tool' or not start:
                continue
            e = start[1]
            relevant = (e.get('tool_name') == 'state_read' if variant == 'pi-memweave' else
                        e.get('tool_name') == 'read' and e.get('tool_path') == NOTE)
            if not relevant:
                continue
            rows = results.get(identity, [])
            if len(rows) != 1:
                issues.append('flow_original_read_source_missing_or_duplicate')
                continue
            entry_id, m = rows[0]
            content = m.get('content')
            if (not isinstance(content, list) or type(m.get('isError')) is not bool
                    or any(not isinstance(b, dict) or b.get('type') == 'text' and not isinstance(b.get('text'), str) for b in content)):
                issues.append('flow_original_read_source_malformed')
                continue
            body = '\n'.join(b['text'] for b in content if b.get('type') == 'text')
            heads = ['']
            for ref, task in refs.get(entry_id, set()):
                heads.extend([f'[{ref}]\n\n', f'[{task}:{ref}]\n\n'])
            hashes = {hashlib.sha256(json.dumps({'role': 'tool', 'content': h+body, 'tool_call_id': identity},
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest() for h in heads}
            if wire.get('sha256') not in hashes:
                issues.append('flow_original_read_wire_hash_mismatch')
                continue
            values = []
            if variant == 'pi-memweave' and body.startswith('# Symbolic State'):
                candidates = [re.sub(r'^[FD]\d+\s+', '', line) for line in body.splitlines() if re.match(r'^[FD]\d+\s+\{', line)]
            else:
                try:
                    obj = json.loads(body.removesuffix('\n\n[TRUNCATED]'))
                except ValueError:
                    obj = None
                candidates = [i.get('content', '') for i in obj['items'] if re.fullmatch(r'[FD]\d+', i.get('id', '')) and i.get('archived') is not True] if isinstance(obj, dict) and isinstance(obj.get('items'), list) else body.splitlines()
            for candidate in candidates:
                try:
                    value = json.loads(candidate)
                    if isinstance(value, dict) and value.get('k') in GOLD:
                        values.append(value)
                except ValueError:
                    pass
            projections = [d for d in q.get('capsule_deliveries', []) if d.get('tool_call_id') == identity]
            if values and (len(projections) != 1 or projections[0].get('values') != values
                           or projections[0].get('message_sha256') != wire.get('sha256')):
                issues.append('flow_read_summary_disagrees_with_original')
    return issues


def collect_flow_v2(trial, variant, *, expected_reducer_sha256=None):
    trial = Path(trial)
    validated = collect_capsules(trial, variant, expected_reducer_sha256=expected_reducer_sha256)
    trace = _read_jsonl(trial/'agent/request-trace.jsonl')
    if trace is None:
        return {'protocol': PROTOCOL, 'complete': False, 'issues': ['raw_trace_missing'],
                'assertions': dict.fromkeys(assertion_ids(), 'missing'), 'opportunities': {}}
    boundaries = [(i, e) for i, e in enumerate(trace) if e.get('event') == 'workspace_checkpoint']
    ends = [(i, e) for i, e in boundaries if e.get('phase') == 'agent_end']
    starts = {e.get('call_id'): (i, e) for i, e in boundaries if e.get('phase') == 'tool_start'}
    tool_ends = {e.get('call_id'): (i, e) for i, e in boundaries if e.get('phase') == 'tool_end'}
    requests = [(i, e) for i, e in enumerate(trace) if e.get('event') == 'request_ready']
    issues = list(validated.get('issues', []))
    if not validated.get('complete') and not issues:
        issues.append(validated.get('reason', 'flow_base_chain_incomplete'))
    projection_complete = bool(requests) and all(isinstance(e.get('memory_state_deliveries'), list)
        and all(isinstance(d, dict) for d in e['memory_state_deliveries'])
        and isinstance(e.get('capsule_deliveries'), list)
        and all(isinstance(d, dict) for d in e['capsule_deliveries']) for _, e in requests)
    if variant == 'pi-memweave' and projection_complete:
        projection_complete = all(isinstance(q.get('state_blocks'), list)
            and all(isinstance(b, dict) and isinstance(b.get('sha256'), str) for b in q['state_blocks'])
            and all(isinstance(d.get('body_sha256'), str) for d in q['memory_state_deliveries'])
            and sorted(d.get('body_sha256', '') for d in q['memory_state_deliveries']) == sorted(b.get('sha256', '') for b in q['state_blocks'])
            for _, q in requests)
    if not projection_complete:
        issues.append('flow_delivery_projection_missing')
    read_issues = _read_projection_issues(trial/'agent', requests, starts, variant) if projection_complete else []
    issues.extend(read_issues)
    projection_complete = projection_complete and not read_issues
    base_complete = validated.get('complete') is True and len(ends) == 1
    try:
        journals = _journals(trial/'agent/memory.tar.gz') if variant == 'pi-memweave' else {}
    except (OSError, ValueError, tarfile.TarError):
        journals = {}
        base_complete = False
        issues.append('flow_journal_invalid')
    versions = set()
    for _, e in boundaries:
        b = e.get('state_boundary') or {}
        if isinstance(b.get('expected_task_id'), str) and type(b.get('expected_version_at_prepare')) is int:
            versions.add((b['expected_task_id'], b['expected_version_at_prepare']))
    for _, e in requests:
        if isinstance(e.get('expected_task_id'), str) and type(e.get('expected_version_at_prepare')) is int:
            versions.add((e['expected_task_id'], e['expected_version_at_prepare']))
    try:
        replayed = _replay_prefixes(journals, versions) if journals else {}
    except (ValueError, OSError, subprocess.SubprocessError):
        replayed = {}
        base_complete = False
        issues.append('flow_journal_replay_invalid')

    def entries(boundary):
        if variant == 'pi-native':
            note = (boundary.get('workspace') or {}).get('memory_capsules')
            if not isinstance(note, dict) or not isinstance(note.get('values'), list):
                return None
            return [{'value': v, 'archived': False} for v in note['values']]
        b = boundary.get('state_boundary') or {}
        task, version = b.get('expected_task_id'), b.get('expected_version_at_prepare')
        if task is None:
            return []
        rows = replayed.get((task, version))
        if rows is None or hashlib.sha256(b''.join(journals[task][:version])).hexdigest() != b.get('expected_journal_sha256'):
            return None
        result = []
        for row in rows:
            try:
                value = json.loads(row['content'])
            except ValueError:
                continue
            result.append({'value': value, 'archived': row['archived']})
        return result

    def valid_values(values, key):
        return isinstance(values, list) and all(s == 'pass' for s in
            truth([{'value': v, 'archived': False} for v in values], key).values())

    def delivered(request, key):
        if request is None:
            return False, []
        q = request[1]
        evidence = []
        if variant == 'pi-memweave':
            blocks = q.get('state_blocks', [])
            for d in q.get('memory_state_deliveries', []):
                task, version = d.get('task_id'), d.get('state_version')
                matched = [b for b in blocks if b.get('task_id') == task and b.get('version') == version
                           and b.get('sha256') == d.get('body_sha256')]
                if (len(matched) == 1 and isinstance(task, str) and type(version) is int
                        and q.get('expected_task_id') == task and q.get('expected_version_at_prepare') == version
                        and all(s == 'pass' for s in truth(entries({'state_boundary': q}), key).values())
                        and valid_values(d.get('values'), key)):
                    evidence.append({'channel': 'automatic_state', 'task_id': task, 'version': version,
                                     'body_sha256': d['body_sha256']})
        for d in q.get('capsule_deliveries', []):
            identity = d.get('tool_call_id')
            start = starts.get(identity)
            end = tool_ends.get(identity)
            if (start is None or end is None or not start[0] < end[0] < request[0]
                    or end[1].get('tool_is_error') is not False):
                continue
            event = start[1]
            if variant == 'pi-native':
                eligible = event.get('tool_name') == 'read' and event.get('tool_path') == NOTE
            else:
                boundary = end[1].get('state_boundary') or {}
                eligible = (event.get('tool_name') == 'state_read' and d.get('task_id') == q.get('expected_task_id')
                    and d.get('task_id') == boundary.get('expected_task_id')
                    and type(d.get('state_version')) is int
                    and d['state_version'] == boundary.get('expected_version_at_prepare')
                    and type(q.get('expected_version_at_prepare')) is int
                    and d['state_version'] <= q['expected_version_at_prepare'])
            if eligible and valid_values(d.get('values'), key):
                evidence.append({'channel': 'tool_read', 'call_id': identity})
        return bool(evidence), evidence

    probe_status = {}
    path = trial/'verifier/derived-ctrf.json'
    if path.is_file():
        try:
            for row in json.loads(path.read_text())['results']['tests']:
                name = row.get('name')
                probe_status[name] = 'invalid' if name in probe_status else {
                    'passed': 'pass', 'failed': 'fail'}.get(row.get('status'), 'missing')
        except (ValueError, KeyError, TypeError):
            pass
    assertions, details = {}, {}
    final_request = requests[-1] if requests else None
    for key in GOLD:
        first = validated.get('opportunities', {}).get(key, {}).get('first_dependency_trace_position')
        deadline = trace[first] if type(first) is int else ends[0][1] if ends else {}
        capture = truth(entries(deadline), key) if base_complete else dict.fromkeys(('schema', 'values', 'no_conflict'), 'missing')
        for leaf, value in capture.items():
            assertions[f'flow:{key}:capture:{leaf}'] = value
        action_request = next(((i, e) for i, e in reversed(requests) if i < first), None) if type(first) is int else final_request
        actions = {}
        for leaf, request in (('at_action', action_request), ('at_final', final_request)):
            passed, proof = delivered(request, key) if base_complete and projection_complete else (False, [])
            assertions[f'flow:{key}:delivery:{leaf}'] = ('pass' if passed else 'fail') if base_complete and projection_complete else 'missing'
            actions[leaf] = {'trace_position': request[0] if request else None, 'evidence': proof}
        for n in (1, 2):
            assertions[f'flow:{key}:behavior:probe{n}'] = probe_status.get(f'tb01_capsule_actions.py::test_{key}_{n}', 'missing')
        details[key] = {'first_dependency_trace_position': first,
            'capture_deadline': 'first_dependency_edit' if first is not None else 'episode_end_no_edit',
            'capture_truth': capture, 'deliveries': actions}
    return {'protocol': PROTOCOL, 'complete': base_complete and projection_complete,
        'issues': sorted(set(issues)), 'assertions': assertions, 'opportunities': details,
        'delivery_recoveries': validated.get('delivery_recoveries', []),
        'interpretation': 'Three independently scored components, no explicit-read requirement or repeated gate; '
                          'bounded source constraints, mechanical delivery and final business predicates; no causal adoption claim.'}
