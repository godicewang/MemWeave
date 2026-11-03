"""Read existing trial-local Pi originals at frozen anchors; no new Session store."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime

from .fixed35_collection import unique_sessions


class MissingSessionOriginals(ValueError):
    pass


def load_original_sessions(trial):
    result={}
    try:paths=unique_sessions(trial)
    except (ValueError,OSError)as error:raise MissingSessionOriginals('conflicting or unavailable original Session copies')from error
    for path in paths:
        raw=path.read_bytes()
        if not raw.endswith(b'\n'):raise MissingSessionOriginals('incomplete original Session JSONL')
        try:records=[json.loads(line)for line in raw.decode().splitlines()]
        except (ValueError,UnicodeError)as error:raise MissingSessionOriginals('corrupt original Session JSONL')from error
        if not records:raise MissingSessionOriginals('original Session header missing')
        header=records[0]
        if not isinstance(header,dict):raise MissingSessionOriginals('original Session header unavailable')
        identity=header.get('id')
        if header.get('type')!='session'or header.get('version')!=3 or not isinstance(identity,str)or not identity:
            raise MissingSessionOriginals('unsupported original Session header')
        if identity in result:raise MissingSessionOriginals('ambiguous original Session identity')
        entries={}
        for record in records[1:]:
            if not isinstance(record,dict):raise MissingSessionOriginals('corrupt original Session entry')
            if not isinstance(record.get('id'),str)or not record['id']or record['id']in entries:
                raise ValueError('duplicate or missing original entry identity')
            entries[record['id']]=record
        result[identity]={'entries':entries,'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    return result


def branch_at(original,anchor):
    entries=original['entries'];chain=[];seen=set();current=anchor
    while current is not None:
        if current not in entries:raise MissingSessionOriginals('original branch anchor or ancestor missing')
        if current in seen:raise ValueError('original Session parent cycle')
        seen.add(current);entry=entries[current];chain.append(entry)
        if 'parentId'not in entry:raise MissingSessionOriginals('original parent identity missing')
        current=entry['parentId']
    return list(reversed(chain))


def time_value(value):
    try:parsed=datetime.fromisoformat(value)
    except (TypeError,ValueError,AttributeError)as error:raise MissingSessionOriginals('original boundary timestamp missing')from error
    if parsed.tzinfo is None:raise MissingSessionOriginals('original boundary timezone missing')
    return parsed


def with_foreign_originals(shape,descriptors,source,originals,requested_at):
    """Enrich only in evaluator memory; never modify raw records or actor inputs."""
    ledger=shape.get('branch_ledger')
    if not isinstance(ledger,list)or not ledger:raise MissingSessionOriginals('target lifecycle branch missing')
    receipt=next((e for e in reversed(ledger)if e.get('custom_type')in {'memweave.resume.v1','memweave.restart.v1'}),None)
    if not receipt or receipt.get('custom_type')!='memweave.resume.v1':return shape,descriptors,source,{}
    data=receipt.get('data')or{};sid=data.get('source_session_id');target=shape.get('session_id')
    if sid==target:return shape,descriptors,source,{}
    if sid not in originals or target not in originals:raise MissingSessionOriginals('source or target original Session absent from trial')
    target_original=originals[target];target_branch=branch_at(target_original,ledger[-1]['id'])
    if [e['id']for e in target_branch]!=[e['id']for e in ledger]:raise MissingSessionOriginals('target ancestry differs from original file')
    for captured,raw in zip(ledger,target_branch,strict=True):
        if captured.get('type')!=raw.get('type')or captured.get('parent_id')!=raw.get('parentId'):
            raise ValueError('target captured identity differs from original')
        if captured.get('custom_type')and(captured['custom_type']!=raw.get('customType')or captured.get('data')!=raw.get('data')):
            raise ValueError('target captured metadata differs from original')
    for descriptor,message in zip(descriptors,source,strict=True):
        identity=descriptor.get('entry_id')
        if identity is not None and target_original['entries'].get(identity,{}).get('message')!=message:
            raise ValueError('target source content differs from original')
    raw_receipt=target_original['entries'].get(receipt['id'],{})
    origin=originals[sid];source_branch=branch_at(origin,data.get('source_anchor_entry_id'))
    if not source_branch:raise MissingSessionOriginals('empty foreign source branch')
    if not time_value(source_branch[-1].get('timestamp'))<=time_value(raw_receipt.get('timestamp'))<=time_value(requested_at):
        raise MissingSessionOriginals('original clock evidence cannot establish anchor availability at restore/request boundary')
    source_shape={'session_id':sid,'branch_ledger':[],'messages':[]}
    added=[];bodies=[]
    for e in source_branch:
        row={'id':e['id'],'parent_id':e['parentId'],'type':e['type']}
        if e['type']=='custom'and e.get('customType','').startswith('memweave.'):
            row.update(custom_type=e['customType'],data=deepcopy(e.get('data')))
        source_shape['branch_ledger'].append(row)
        if e['type']!='message':continue
        message=e['message'];digest=hashlib.sha256(json.dumps(message,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        parts=message.get('content');calls=[p['id']for p in parts if p.get('type')=='toolCall']if isinstance(parts,list)else[]
        source_shape['messages'].append({'id':e['id'],'sha256':digest,'role':message['role'],
            'stop_reason':message.get('stopReason'),'calls':calls,'result_id':message.get('toolCallId')})
        added.append({'entry_id':sid+':'+e['id'],'sha256':digest});bodies.append(message)
    updated=deepcopy(shape);updated['foreign_source']={'version':'trial-original-prefix-v1','shape':source_shape}
    proof={'source_original_sha256':origin['sha256'],'target_original_sha256':target_original['sha256'],
        'source_anchor_entry_id':data['source_anchor_entry_id'],'source_session_id':sid,
        'source_message_hash_encoding':'evaluator python-json-v1; body comes from original Session, not provider output',
        'only_evaluator_memory_enriched':True}
    return updated,descriptors+added,source+bodies,proof
