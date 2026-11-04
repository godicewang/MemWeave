"""Validated existing global inventories; never guesses commits from tool input."""
from __future__ import annotations

import hashlib
import json

from .evidence_replay import read_object


def registry_journals(events,locations,*,complete):
    unavailable={'complete':False,'journals':None,'baseline':None}
    if not complete:return dict(unavailable,reason='independent execution or stage coverage incomplete')
    frames=[e for e in events if e['event']in {'task_registry_checkpoint','execution_terminated','execution_deadline_snapshot'}]
    if not frames or frames[0].get('phase')!='agent_start'or frames[-1].get('phase')not in {'agent_end','execution_terminated','execution_deadline_snapshot'}:
        return dict(unavailable,reason='initial or terminal global Task inventory missing')
    histories={};baseline=None;proof=[]
    try:
        for frame in frames:
            registry=frame['registry'];tasks=registry.get('tasks')
            if registry.get('complete')is not True or not isinstance(tasks,list):raise ValueError('incomplete global Task inventory')
            current={};hashes={}
            for task in tasks:
                identity=task['task_id'];version=task['version']
                if not isinstance(identity,str)or not identity or identity in current or type(version)is not int or version<1:
                    raise ValueError('invalid or duplicate journal identity')
                raw=read_object(locations[(frame['producer_id'],frame['sequence'])],task['journal_ref'])
                if not raw.endswith(b'\n')or hashlib.sha256(raw).hexdigest()!=task['journal_sha256']:
                    raise ValueError('journal bytes differ from captured inventory')
                rows=[json.loads(line)for line in raw.decode().splitlines()]
                if len(rows)!=version:raise ValueError('journal version differs from captured inventory')
                previous=histories.get(identity,[])
                if rows[:len(previous)]!=previous:raise ValueError('State history is not append-only')
                current[identity]=rows;hashes[identity]={'version':version,'sha256':task['journal_sha256']}
            if set(histories)-set(current):raise ValueError('previously observed Task absent from later complete inventory')
            if baseline is None:baseline=current
            histories=current
            proof.append({'producer_id':frame['producer_id'],'sequence':frame['sequence'],
                'stage_id':frame.get('stage_id'),'phase':frame['phase'],'tasks':hashes})
        return {'complete':True,'journals':histories,'baseline':baseline,'inventory_proof':proof,
            'reason':'complete actual global Task inventories, verified CAS bytes and append-only prefix'}
    except (KeyError,TypeError,ValueError,OSError,EOFError,AttributeError)as error:
        return dict(unavailable,reason=str(error))
