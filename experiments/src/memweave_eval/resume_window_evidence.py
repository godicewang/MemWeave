"""Independent declared-resume projection from raw native metadata/originals.

This checks the declared frozen source, not whether the chosen Session was best.
No product reducer/projection code is imported.
"""
from __future__ import annotations


class MissingResumeEvidence(ValueError):
    pass


def validated_branch(shape):
    ledger=shape.get('branch_ledger');messages=shape['messages']
    if not isinstance(ledger,list)or not ledger:raise MissingResumeEvidence('raw native branch ledger missing')
    by_id={}
    for position,entry in enumerate(ledger):
        if not isinstance(entry,dict)or not isinstance(entry.get('id'),str)or 'parent_id'not in entry:
            raise MissingResumeEvidence('native branch entry identity missing')
        if entry['id']in by_id:raise ValueError('duplicate native branch identity')
        if entry['parent_id']!=(ledger[position-1]['id']if position else None):
            raise MissingResumeEvidence('native branch ancestry incomplete')
        by_id[entry['id']]=position
        if entry.get('type')in {'compaction','context_edit'}:
            raise MissingResumeEvidence('native effective projection edits require a separate oracle')
    if [e['id']for e in ledger if e.get('type')=='message']!=[m['id']for m in messages]:
        raise MissingResumeEvidence('native message ledger and branch ledger differ')
    return ledger,messages,by_id


def same_session_resume(shape,index_events,recent_turns):
    # Historical entry name retained; foreign data is accepted only after the
    # independent original-file enrichment and validation above this oracle.
    ledger,messages,by_id=validated_branch(shape);session=shape['session_id']
    resumes=[i for i,e in enumerate(ledger)if e.get('custom_type')=='memweave.resume.v1']
    restarts=[i for i,e in enumerate(ledger)if e.get('custom_type')=='memweave.restart.v1']
    if not resumes or restarts and restarts[-1]>resumes[-1]:
        raise MissingResumeEvidence('latest lifecycle boundary is not a supported Task resume')
    position=resumes[-1];data=ledger[position].get('data')
    if not isinstance(data,dict)or not {'task_id','source_session_id','source_anchor_entry_id',
            'seed_event_ids','target_anchor_entry_id','recent_turns','evict_turns'}<=set(data):
        raise MissingResumeEvidence('complete frozen resume receipt missing')
    if not isinstance(data['task_id'],str)or not data['task_id']:
        raise ValueError('invalid declared resume Task identity')
    if type(data['recent_turns'])is not int or type(data['evict_turns'])is not int \
            or not 0<data['evict_turns']<=data['recent_turns']or not isinstance(data['seed_event_ids'],list):
        raise ValueError('invalid frozen resume limits or seed list')
    foreign=data['source_session_id']!=session;source_ledger=ledger;source_messages=messages;source_by_id=by_id
    if foreign:
        evidence=shape.get('foreign_source')
        if not isinstance(evidence,dict)or evidence.get('version')!='trial-original-prefix-v1'or not isinstance(evidence.get('shape'),dict):
            raise MissingResumeEvidence('foreign Session seed requires independent source branch evidence')
        if evidence['shape'].get('session_id')!=data['source_session_id']:raise ValueError('foreign original Session identity differs')
        source_ledger,source_messages,source_by_id=validated_branch(evidence['shape'])
    source_anchor=source_by_id.get(data['source_anchor_entry_id'])
    target_anchor=by_id.get(data['target_anchor_entry_id'])if data['target_anchor_entry_id']is not None else -1
    if source_anchor is None or target_anchor is None:
        raise MissingResumeEvidence('declared source or target anchor not on captured branch')
    if not foreign and source_anchor>=position or target_anchor>=position:
        raise ValueError('resume anchors must precede their receipt')
    source_branch=source_ledger[:source_anchor+1];source_ids={e['id']for e in source_branch}
    by_message={m['id']:m for m in source_messages};known={};owners={};scope=None;assistant_scope=None
    for entry in source_branch:
        if entry.get('custom_type')!='memweave.references.v1':continue
        record=entry.get('data')
        if not isinstance(record,dict)or not isinstance(record.get('task_id'),str)or not isinstance(record.get('bindings'),list):
            raise MissingResumeEvidence('source ownership reference record missing')
        for binding in record['bindings']:
            if not isinstance(binding,dict)or not isinstance(binding.get('entry_id'),str):
                raise MissingResumeEvidence('source ownership binding missing')
            known[binding['entry_id']]=record['task_id']
    for entry in source_branch:
        kind=entry.get('custom_type')
        if kind=='memweave.restart.v1':scope=None
        if kind=='memweave.scope.v1':
            if not isinstance(entry.get('data'),dict)or 'task_id'not in entry['data']:
                raise MissingResumeEvidence('source Task scope missing')
            scope=entry['data']['task_id']
        message=by_message.get(entry['id'])
        if message is None:continue
        if message['role']=='user':owners[entry['id']]=known.get(entry['id'],scope)
        elif message['role']=='assistant':
            assistant_scope=known.get(entry['id'],scope);owners[entry['id']]=assistant_scope
        elif message['role']=='toolResult':owners[entry['id']]=known.get(entry['id'],assistant_scope)
    source_events,_=index_events([m for m in source_messages if m['id']in source_ids])
    owned=[e for e in source_events if all(owners.get(identity)==data['task_id']for identity in e['messages'])]
    if not owned:raise ValueError('declared resume source has no complete Task-owned events')
    if [e['id']for e in owned[-data['recent_turns']:]]!=data['seed_event_ids']:
        raise ValueError('declared resume seed differs from frozen Task-owned complete events')
    seeds=owned[-recent_turns:]
    if foreign:seeds=[{'id':data['source_session_id']+':'+e['id'],
        'messages':[data['source_session_id']+':'+identity for identity in e['messages']]}for e in seeds]
    seen={e['id']for e in seeds}
    after_ids={e['id']for e in ledger[target_anchor+1:]}
    after,_=index_events([m for m in messages if m['id']in after_ids])
    events=seeds+[e for e in after if e['id']not in seen]
    prior=next((e['data']for e in reversed(ledger[position+1:])if e.get('custom_type')=='memweave.window.v1'),None)
    if shape['previous_window']!=prior:
        raise MissingResumeEvidence('collector prior Window not scoped after latest resume')
    return events,prior
