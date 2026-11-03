"""Independent plain-text Window selection oracle from native entry identities.

No production reducer is imported. Native IDs/links and earlier committed
metadata establish the expected range; actual HTTP bodies establish delivery.
Resumed/restarted, compacted, multimedia or token-truncated projections are
explicitly outside this version and remain missing, never design NA.
"""
from __future__ import annotations

import hashlib
import json

from .contract_metrics import _item, summarize
from .evidence_replay import read_object
from .fixed35_business import case_events
from .fixed35_window import small_window_checkpoint


class MissingWindowEvidence(ValueError):
    pass


def identity_selection(shape,*,recent_turns,evict_turns):
    if not isinstance(shape,dict)or shape.get('version')!='native-window-shape-v1' or 'previous_window'not in shape:
        raise MissingWindowEvidence('native identity ledger missing')
    if shape.get('unsupported_lifecycle')is not False:
        raise MissingWindowEvidence('resume/restart requires a separately frozen seed projection oracle')
    n,b=recent_turns,evict_turns
    if any(type(v)is not int or v<=0 for v in (n,b))or b>n:raise ValueError('invalid frozen N/B')
    messages=shape.get('messages');session=shape.get('session_id')
    if not isinstance(messages,list)or not isinstance(session,str)or not session:
        raise MissingWindowEvidence('native branch identity list missing')
    events=[];pending=set();seen=set();anchor=None
    for m in messages:
        if not isinstance(m,dict)or not isinstance(m.get('id'),str)or not m['id']:
            raise MissingWindowEvidence('native message identity missing')
        identity=m['id']
        if identity in seen:raise ValueError('duplicate native entry identity')
        seen.add(identity);role=m.get('role')
        if role=='system':continue
        anchor=identity
        if role=='assistant'and m.get('stop_reason')in {'error','aborted'}:continue
        if role not in {'user','assistant','toolResult'}:
            raise MissingWindowEvidence('unsupported native message representation')
        if role=='toolResult':
            result=m.get('result_id')
            if not events or result not in pending:raise ValueError('unpaired native tool result')
            pending.remove(result);events[-1]['messages'].append(identity)
        else:
            if pending:raise ValueError('incomplete native tool event')
            calls=m.get('calls')
            if not isinstance(calls,list)or any(not isinstance(c,str)or not c for c in calls):
                raise MissingWindowEvidence('native tool identities missing')
            if len(calls)!=len(set(calls)):raise ValueError('duplicate native tool call')
            if role=='user'and calls:raise ValueError('user event cannot own tool calls')
            events.append({'id':identity,'messages':[identity]});pending=set(calls)
    if pending:raise MissingWindowEvidence('pending native result at request boundary')
    ids=[e['id']for e in events];prior=shape['previous_window']
    boundary=None;old_batches=[];reset=False
    if prior is not None:
        if not isinstance(prior,dict)or not {'recent_turns','evict_turns','boundary_entry_id','pending'}<=set(prior):
            raise MissingWindowEvidence('prior committed Window metadata missing')
        reset=(prior['recent_turns'],prior['evict_turns'])!=(n,b)
        boundary=ids[-n-1]if reset and len(ids)>n else None if reset else prior['boundary_entry_id']
        old_batches=[]if reset else prior['pending']
        if not isinstance(old_batches,list):raise ValueError('invalid prior pending batches')
    if boundary is not None and boundary not in ids:raise ValueError('committed boundary not on native branch')
    visible=events[ids.index(boundary)+1:]if boundary is not None else events
    consumed=0;previous=boundary;batches=[]
    def expected_batch(candidates):
        digest=hashlib.sha256(json.dumps([session,previous or'',*candidates],separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        return {'batch_id':digest,'candidate_event_ids':candidates}
    for old in old_batches:
        candidates=[e['id']for e in visible[consumed:consumed+b]]
        if len(candidates)!=b or old!=expected_batch(candidates):raise ValueError('invalid ordered pending candidate batch')
        batches.append(old);consumed+=b;previous=candidates[-1]
    while len(visible)-consumed>n:
        candidates=[e['id']for e in visible[consumed:consumed+b]]
        batches.append(expected_batch(candidates));consumed+=len(candidates);previous=candidates[-1]
    computed={'stage':'reset'if reset else'prepare','recent_turns':n,'evict_turns':b,
        'boundary_entry_id':boundary,'pending':batches,'request_anchor_entry_id':anchor,'completed_by':None}
    durable=computed if prior is None or reset or batches else prior
    return [identity for e in visible for identity in e['messages']],durable


def identity_window_checkpoint(shape,descriptors,source,payload,observed_window,*,recent_turns,evict_turns,max_source_bytes=4000000):
    try:ids,expected_window=identity_selection(shape,recent_turns=recent_turns,evict_turns=evict_turns)
    except MissingWindowEvidence as error:return None,str(error),{}
    except (ValueError,KeyError,TypeError)as error:return False,str(error),{}
    if not isinstance(descriptors,list)or not isinstance(source,list)or len(descriptors)!=len(source):
        return None,'independent source content references missing',{}
    expected_hash={m['id']:m.get('sha256')for m in shape['messages']}
    lookup={}
    for descriptor,message in zip(descriptors,source,strict=True):
        identity=descriptor.get('entry_id')
        if identity is None:continue
        if identity in lookup or expected_hash.get(identity)!=descriptor.get('sha256'):
            return None,'ambiguous or inconsistent native-to-source identity',{}
        lookup[identity]=message
    if any(identity not in lookup for identity in ids):
        return None,'selected native content unavailable or compacted before evaluation hook',{}
    if not isinstance(observed_window,dict):return None,'post-transform durable Window metadata missing',{}
    metadata=observed_window==expected_window
    chosen=[lookup[identity]for identity in ids]
    value,reason,checks=small_window_checkpoint(chosen,payload,
        recent_turns=max(1,len(chosen)),enabled=True,max_source_bytes=max_source_bytes)
    checks.update(durable_window_candidates_match_independent_native_range=metadata)
    if value is None:return (False if not metadata else None),reason,checks
    return value and metadata,reason if metadata else'durable Window candidate or boundary mismatch',checks


def grade_identity_windows(trial,request_ids,*,recent_turns,evict_turns,enabled,max_source_bytes=4000000):
    if not enabled:
        from .fixed35_window import grade_small_windows
        return grade_small_windows(trial,request_ids,recent_turns=recent_turns,
            enabled=False,max_source_bytes=max_source_bytes)
    events,locations=case_events(trial)
    ready={e['request_id']:e for e in events if e['event']=='request_ready'and e.get('request_id')in request_ids}
    projections={}
    for e in events:
        if e['event']=='memory_projection_boundary':
            projections[e['boundary_id']]=json.loads(read_object(locations[(e['producer_id'],e['sequence'])],e['metadata_ref']))
    items=[]
    for identity in sorted(request_ids):
        event=ready.get(identity);boundary=(event or{}).get('prepared_boundary')or{}
        if not event or not event.get('payload_ref')or not isinstance(boundary.get('source_messages'),list):
            items.append(_item(identity,reason='independent request content boundary missing'));continue
        store=locations[(event['producer_id'],event['sequence'])]
        descriptors=boundary['source_messages']
        source=[json.loads(read_object(store,m['source_ref']))for m in descriptors]
        projection=projections.get(boundary.get('boundary_id'),{}).get('memweave.window.v1',{}).get('data')
        value,reason,checks=identity_window_checkpoint(boundary.get('native_shape'),descriptors,source,
            json.loads(read_object(store,event['payload_ref'])),projection,
            recent_turns=recent_turns,evict_turns=evict_turns,max_source_bytes=max_source_bytes)
        items.append(dict(_item(identity,value,reason),assertions=checks))
    return dict(summarize(items),version='native-identity-plain-text-v1',
        scope='Independent native-entry range, complete tool events, exact plain-text HTTP projection and durable candidate metadata. '
            'Not a token-allocation, compaction, resume/restart or multimodal oracle; unsupported evidence is unknown.')
