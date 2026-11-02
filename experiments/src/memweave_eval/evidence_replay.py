"""Verify original content-addressed request evidence; never mutate actor originals."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from .storage import contained


def read_object(root: Path, reference):
    if not isinstance(reference, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(reference.get('sha256'))):
        raise ValueError('invalid evidence reference')
    path = contained(root, reference['object'])
    if path.is_symlink():
        raise ValueError('redirected evidence object')
    data = gzip.decompress(path.read_bytes())
    if hashlib.sha256(data).hexdigest() != reference['sha256'] or len(data) != reference['bytes']:
        raise ValueError('evidence object hash/length mismatch')
    return data


def replay_content(root: Path, *, expected_request_ids=None):
    streams = defaultdict(dict)
    damaged, duplicates = [], 0
    for path in sorted(root.glob('producer-*.jsonl')):
        for line_no, raw in enumerate(path.read_bytes().splitlines(), 1):
            try:
                value = json.loads(raw)
                prefix, delimiter, _ = raw.rpartition(b',"event_sha256":')
                if not delimiter or hashlib.sha256(prefix+b'}').hexdigest() != value['event_sha256']:
                    raise ValueError('hash')
                producer, sequence = value['producer_id'], value['sequence']
                if type(sequence) is not int or sequence < 1:
                    raise ValueError('sequence')
                old = streams[producer].get(sequence)
                if old is not None:
                    if old != value:
                        raise RuntimeError('conflicting valid producer event')
                    duplicates += 1
                streams[producer][sequence] = value
            except (KeyError, ValueError, TypeError):
                damaged.append({'file': path.name, 'line': line_no, 'reason': 'invalid_or_truncated_record'})
    records = []
    for events in streams.values():
        previous = None
        for seq in range(1, max(events)+1):
            if seq not in events or events[seq]['previous_sha256'] != previous:
                raise ValueError('unrecoverable sequence gap or chain mismatch')
            previous = events[seq]['event_sha256']
            records.append(events[seq])
    requests, chunks, receipts, http = {}, defaultdict(dict), {}, {}
    for event in records:
        identity = event.get('request_id')
        if event['event'] == 'request_ready':
            if identity in requests:
                raise ValueError('request identity reused across producers')
            requests[identity] = json.loads(read_object(root, event['payload_ref']))
        elif event['event'] == 'response_chunk':
            if event['ordinal'] in chunks[identity]:
                raise ValueError('conflicting response chunk ordinal')
            chunks[identity][event['ordinal']] = read_object(root, event['chunk_ref'])
        elif event['event'] == 'provider_receipt':
            receipts[identity] = event
        elif event['event']=='http_response':
            http[identity]=event.get('status')
    if expected_request_ids is not None and set(requests) != set(expected_request_ids):
        raise ValueError('request delivery set does not match independent transport evidence')
    rebuilt = {}
    for identity, parts in chunks.items():
        if set(parts) != set(range(1, len(parts)+1)):
            raise ValueError('incomplete provider chunk sequence')
        raw = b''.join(parts[i] for i in sorted(parts)).decode()
        data = [line[5:].strip() for line in raw.splitlines() if line.startswith('data:')]
        values = [json.loads(v) for v in data if v != '[DONE]']
        usage = next((v['usage'] for v in reversed(values) if isinstance(v.get('usage'), dict)), None)
        rebuilt[identity] = {'stream_done': '[DONE]' in data, 'usage': usage,
            'receipt_recorded': identity in receipts, 'chunks': len(parts),'http_status':http.get(identity),
            'assistant_payload_present':any(isinstance(c.get('delta'),dict)and
                (bool(c['delta'].get('content'))or bool(c['delta'].get('tool_calls')))
                for v in values for c in v.get('choices',[])if isinstance(c,dict)),
            'successful_finish':any(c.get('finish_reason')in {'stop','tool_calls'}
                for v in values for c in v.get('choices',[])if isinstance(c,dict)),
            'provider_error':any('error'in v for v in values)}
    return {'requests': requests, 'responses': rebuilt, 'events': records,
            'duplicate_records_deduplicated': duplicates, 'damaged_source_records': damaged,
            'repair': 'valid mirror and content objects used; originals unchanged' if damaged else None}
