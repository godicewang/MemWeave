"""Frozen MAB action and finite-literal memory predicates, never an LLM judge.

Literal retention is deliberately a controlled parser score, not a claim that all
free-form paraphrases have been understood. Gold and future facts remain host-only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .evidence_replay import read_object, replay_content
from .fixed35 import checkpoint_verdict
from .fixed35_adapters import normalize_mab, score_mab


def active_text(journal):
    entries={};counts={'F':0,'D':0};seen=set()
    for row in journal:
        if row['op_id']in seen:
            raise ValueError('duplicate committed operation')
        seen.add(row['op_id']);op=row['op']
        if op=='modify_fact':
            for identity in row['archive']:
                entries[identity]['active']=False
            counts['F']+=1
            entries['F'+str(counts['F'])]={'text':row['append_fact']['content'],'active':True,'position':len(seen)}
        elif op in {'append_fact','append_decision'}:
            kind='F'if op=='append_fact'else'D';counts[kind]+=1
            if row['id']!=kind+str(counts[kind]):
                raise ValueError('non-contiguous State identifier')
            entries[row['id']]={'text':row['fact'if kind=='F'else'decision'],'active':True,'position':len(seen)}
        elif op=='slide_window':
            for identity,entry in entries.items():
                if row['evicted_range']['from']<=entry['position']<=row['evicted_range']['to'] and identity not in row['retained_ids']:
                    entry['active']=False
        elif op!='update_goal':
            raise ValueError('unsupported State operation')
    return [e['text']for e in entries.values()if e['active']]


def literal_snapshot(texts, contract):
    if texts is None:
        return {'required_relations':None,'obsolete_relations_absent':None}
    # Explicit literal, same-entry matching prevents an unrelated occurrence of an
    # answer name from satisfying an entity/relation checkpoint.
    values=[normalize_mab(t)for t in texts]
    def has(parts):
        return any(all(re.search(r'(?<!\w)'+re.escape(normalize_mab(p))+r'(?!\w)',v)for p in parts)for v in values)
    return {'required_relations':all(has(p)for p in contract['required_relations']),
            'obsolete_relations_absent':not any(has(p)for p in contract.get('forbidden_relations',[]))}


def grade_action(prediction, answers, action, *, action_observation_complete):
    score=score_mab(prediction,answers,action if action is not None else {} if action_observation_complete else None)
    checks={'answer_correct':None if prediction is None else bool(score['strict_answer']),
            'file_schema':None if not action_observation_complete else isinstance(action,dict)and set(action)=={'value'}and isinstance(action['value'],str),
            'file_value':None if not action_observation_complete else bool(score['typed_action'])}
    point=checkpoint_verdict({'id':'F35.MAB.typed-action-v1','required_assertions':list(checks)},checks)
    return {'native':score,'derived_action':point}


def grade_correction(texts, contract, *, correct_action, snapshot_before_action):
    checks=literal_snapshot(texts,contract)
    checks.update(action_uses_current_value=correct_action,snapshot_precedes_action=snapshot_before_action)
    return checkpoint_verdict({'id':'F35.C5.current-memory-before-action-v1','required_assertions':list(checks)},checks)


def grade_three_evictions(snapshots, *, observation_complete):
    required=['eviction_1','eviction_2','eviction_3']
    checks={}
    boundaries=set()
    for index,name in enumerate(required):
        if snapshots is None or index>=len(snapshots):
            checks[name]=None
            continue
        item=snapshots[index]
        boundary=item.get('boundary_id')
        independent=isinstance(boundary,str)and boundary not in boundaries
        boundaries.add(boundary)
        values=[item.get('original_source_absent'),item.get('current_facts_retained'),item.get('delivered_version_correct')]
        checks[name]=independent and all(values)if all(type(v)is bool for v in values)else None
    point=checkpoint_verdict({'id':'F35.C4.three-actual-evictions-v1','required_assertions':required},checks)
    if observation_complete and (snapshots is None or len(snapshots)<3):
        point.update(reason='PLANNED_OPPORTUNITY_NOT_TRIGGERED: fewer than three actual evictions',
                     opportunity_status='UNFILLED_PLANNED_SLOT')
    return point


def grade_mab_trial(trial:Path,contract,*,arm):
    from .state_pi import final_pi_text
    # Only final query artifacts count; an ingestion acknowledgement is not an answer.
    agent=trial/'steps/query/agent'
    prediction=final_pi_text(agent/'pi.txt')if (agent/'pi.txt').exists()else ''
    artifacts=agent/'fixed35-artifacts'
    presence=artifacts/'answer-presence.json'
    exists=json.loads(presence.read_text())['exists']if presence.exists()else None
    action=None
    if exists:
        try:action=json.loads((artifacts/'answer.json').read_text())
        except (ValueError,FileNotFoundError):action={}
    result=grade_action(prediction,contract['answers'],action,action_observation_complete=type(exists)is bool)
    # Complete observed episode never reached its query => a real business failure.
    if not agent.exists():
        result=grade_action('',contract['answers'],None,action_observation_complete=True)
    if arm=='pi-native':
        result['memory']={'status':'DESIGN_NA','reason':'native Pi has no State'}
        return result
    records={};locations={}
    for store in trial.rglob('request-content'):
        for event in replay_content(store)['events']:
            key=event['producer_id'],event['sequence'];records[key]=event;locations[key]=store
    events=sorted(records.values(),key=lambda e:(e['timestamp'],e['producer_id'],e['sequence']))
    texts=None;before=None;action_seen=False;evictions=[];boundaries=set();first_action_correct=None
    original=Path(contract['source_instruction_path']).read_text()
    source_seen=False
    projection={}
    for event in events:
        key=event['producer_id'],event['sequence'];store=locations[key]
        if event['event']=='memory_projection_boundary':
            projection[event['boundary_id']]=json.loads(read_object(store,event['metadata_ref']))
        if event['event']=='request_ready':
            boundary=event.get('prepared_boundary')or{}
            ref=boundary.get('expected_journal_ref')
            texts=None;before=None
            if ref:
                rows=[json.loads(line)for line in read_object(store,ref).decode().splitlines()]
                texts=active_text(rows);before=True
            elif boundary.get('expected_task_id')is None and 'expected_task_id'in boundary:
                texts=[];before=True
            window=projection.get(boundary.get('boundary_id'),{}).get('memweave.window.v1',{}).get('data',{})
            cut=window.get('boundary_entry_id')
            payload=json.loads(read_object(store,event['payload_ref']))
            def content(message):
                raw=message.get('content')
                return raw if isinstance(raw,str)else '\n'.join(p.get('text','')for p in raw or []if isinstance(p,dict))
            messages=[content(m)for m in payload.get('messages',[])]
            source_visible=any(original in value for value in messages)
            if cut and cut not in boundaries:
                boundaries.add(cut)
                literal=contract.get('literal_memory')
                valid=int(event.get('stage_id')or 0)>=contract.get('literal_valid_after_stage',1)
                blocks=[value for value in messages if value.startswith('# Symbolic State')]
                delivered_entries=re.findall(r'(?ms)^[FD]\d+ (.*?)\ne: \[',blocks[0])if len(blocks)==1 else None
                keep=literal_snapshot(delivered_entries,literal)['required_relations']if literal and valid else None
                expected=boundary.get('expected_version_at_prepare')
                versions=[int(m.group(1))for value in blocks if (m:=re.search(r'state_version: (\d+)',value))]
                delivered=(len(versions)==1 and versions[0]==expected)if type(expected)is int else None
                evictions.append({'boundary_id':cut,'original_source_absent':source_seen and not source_visible,
                    'current_facts_retained':keep,'delivered_version_correct':delivered})
            source_seen|=source_visible
        elif event['event']=='state_after_tool':
            snapshot=event.get('state',{});texts=None;before=None
            if snapshot.get('journal_ref'):
                rows=[json.loads(line)for line in read_object(store,snapshot['journal_ref']).decode().splitlines()]
                texts=active_text(rows);before=True
            elif snapshot.get('status')=='NO_BOUND_TASK':texts=[];before=True
        elif event['event']=='tool_call':
            value=json.loads(read_object(store,event['record_ref']))
            path=(value.get('input')or{}).get('path')
            if event['tool']in {'write','edit'} and path in {'/app/answer.json','answer.json'}:
                action_seen=True
                if event['tool']=='write':
                    try:
                        first=json.loads(value['input']['content'])
                        first_action_correct=bool(score_mab('',contract['answers'],first)['typed_action'])
                    except (ValueError,KeyError):first_action_correct=False
                break
    literal=contract.get('literal_memory')
    result['memory']={'correction':grade_correction(texts,literal,
        correct_action=first_action_correct,
        snapshot_before_action=before if action_seen else None)if literal else None,
        'three_evictions':grade_three_evictions(evictions,observation_complete=True),
        'parser_scope':'finite canonical entity/value literal predicates; not general free-text semantics',
        'literal_contract':literal,'dependent_write_observed':action_seen}
    return result
