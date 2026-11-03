"""Independent explicit-restart range from captured native metadata only."""
from __future__ import annotations


class MissingRestartEvidence(ValueError):
    pass


def restarted_history(shape,index_events,recent_turns,evict_turns):
    ledger=shape.get('branch_ledger');messages=shape['messages']
    if not isinstance(ledger,list)or not ledger:raise MissingRestartEvidence('raw restart branch ledger missing')
    positions={}
    for i,e in enumerate(ledger):
        if not isinstance(e,dict)or not isinstance(e.get('id'),str)or 'parent_id'not in e:
            raise MissingRestartEvidence('restart branch identity missing')
        if e['id']in positions:raise ValueError('duplicate native restart identity')
        if e['parent_id']!=(ledger[i-1]['id']if i else None):
            raise MissingRestartEvidence('restart branch ancestry incomplete')
        if e.get('type')in {'compaction','context_edit'}:
            raise MissingRestartEvidence('native effective projection edits require another oracle')
        positions[e['id']]=i
    if [e['id']for e in ledger if e.get('type')=='message']!=[m['id']for m in messages]:
        raise MissingRestartEvidence('restart message and branch identities differ')
    resets=[i for i,e in enumerate(ledger)if e.get('custom_type')in {'memweave.restart.v1','memweave.resume.v1'}]
    if not resets or ledger[resets[-1]].get('custom_type')!='memweave.restart.v1':
        raise MissingRestartEvidence('latest lifecycle boundary is not an explicit restart')
    position=resets[-1];data=ledger[position].get('data')
    if not isinstance(data,dict)or not {'restart_id','previous_task_id','anchor_entry_id','seed_event_ids',
            'recent_turns','evict_turns'}<=set(data):
        raise MissingRestartEvidence('complete raw restart receipt missing')
    n,b=data['recent_turns'],data['evict_turns'];ids=data['seed_event_ids']
    if type(n)is not int or type(b)is not int or not 0<b<=n or not isinstance(ids,list) \
            or any(not isinstance(i,str)or not i for i in ids)or len(set(ids))!=len(ids)or len(ids)>n:
        raise ValueError('invalid restart limits or seed identities')
    scope=None
    for e in ledger[:position]:
        if e.get('custom_type')=='memweave.restart.v1':scope=None
        if e.get('custom_type')=='memweave.scope.v1':
            if not isinstance(e.get('data'),dict)or 'task_id'not in e['data']:
                raise MissingRestartEvidence('pre-restart scope evidence missing')
            scope=e['data']['task_id']
    if scope!=data['previous_task_id']:raise ValueError('restart previous Task differs from raw binding')
    before_ids={e['id']for e in ledger[:position]}
    before,anchor=index_events([m for m in messages if m['id']in before_ids])
    if anchor!=data['anchor_entry_id']:raise ValueError('restart anchor differs from original message boundary')
    roles={m['id']:m['role']for m in messages};seed=before[-n:]
    if not any(roles[e['id']]=='user'for e in seed):
        user=next((e for e in reversed(before)if roles[e['id']]=='user'),None)
        if user is not None:seed=[user]+(before[-(n-1):]if n>1 else[])
    if [e['id']for e in seed]!=ids:raise ValueError('restart seed differs from frozen complete events and user fallback')
    windows=[e.get('data')for e in ledger[position+1:]if e.get('custom_type')=='memweave.window.v1']
    prior=windows[-1]if windows else None
    if shape['previous_window']!=prior:raise MissingRestartEvidence('prior Window is not scoped after latest restart')
    all_events,_=index_events(messages)
    if prior is not None and not isinstance(prior,dict):raise MissingRestartEvidence('raw post-restart Window missing')
    reset=any(isinstance(w,dict)and w.get('stage')=='reset'for w in windows)
    reset |= bool(prior and(prior.get('recent_turns'),prior.get('evict_turns'))!=(recent_turns,evict_turns))
    anchor_position=positions.get(anchor,-1)
    crossed=prior and prior.get('boundary_entry_id')is not None and positions.get(prior['boundary_entry_id'],-1)>=anchor_position
    if reset or crossed:return all_events,prior
    return seed+[e for e in all_events if positions[e['id']]>anchor_position],prior
