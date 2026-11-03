"""Task opportunity extraction from real evaluator CAS, with frozen case oracles.

This does not seed Tasks, decide semantic relevance, or infer successful business
actions from binding receipts. Those are explicit evaluator-owned case inputs.
"""
from __future__ import annotations

import json
import re

from .behavior_metrics import evaluate_behavior
from .evidence_replay import read_object
from .fixed35_business import case_events

VERSION='fixed35-task-checkpoints-20261102-v2'


def delivered_state_blocks(payload):
    blocks=[]
    for message in payload.get('messages',[]):
        raw=message.get('content')
        text=raw if isinstance(raw,str)else'\n'.join(p['text']for p in raw
            if isinstance(p,dict)and p.get('type')=='text'and isinstance(p.get('text'),str))if isinstance(raw,list)else''
        if text.startswith('# Symbolic State'):
            task=re.search(r'^task_id: (\S+)$',text,re.MULTILINE)
            version=re.search(r'^state_version: (\d+)$',text,re.MULTILINE)
            blocks.append({'task_id':task[1]if task else None,'version':int(version[1])if version else None})
    return blocks


def journal_projection(rows):
    entries={};counts={'F':0,'D':0};seen=set();goal=None
    for position,row in enumerate(rows,1):
        if row['op_id']in seen:raise ValueError('duplicate State operation')
        seen.add(row['op_id']);op=row['op']
        if op=='update_goal':goal=row['goal']
        elif op in {'append_fact','append_decision','modify_fact'}:
            if op=='modify_fact':
                for identity in row['archive']:entries[identity]['active']=False
            kind='D'if op=='append_decision'else'F';counts[kind]+=1
            identity=kind+str(counts[kind])
            if op!='modify_fact'and row['id']!=identity:raise ValueError('noncontiguous State ID')
            entries[identity]={'text':row['append_fact']['content']if op=='modify_fact'else row['decision'if kind=='D'else'fact'],
                'position':position,'active':True}
        elif op=='slide_window':
            for identity,entry in entries.items():
                if row['evicted_range']['from']<=entry['position']<=row['evicted_range']['to']and identity not in row['retained_ids']:entry['active']=False
        else:raise ValueError('unsupported State operation')
    return {'Goal':goal,**{identity:entry['text']for identity,entry in entries.items()if entry['active']}}


def _answer(records):
    last=None
    for row in records:
        if row['event']=='assistant_return':
            parts=row['_value'].get('content')
            if isinstance(parts,list):
                texts=[p['text']for p in parts if p.get('type')=='text'and isinstance(p.get('text'),str)]
                # An observed assistant message with no text is an empty
                # answer, distinct from a missing assistant-return record.
                last='\n'.join(texts)
    return last


def _program_action(record,contract):
    """Every registered independent checker must match this first action ID."""
    required=contract.get('required_checkers')
    if not isinstance(record.get('first_action_call_id'),str)or not record['first_action_call_id']:return None
    if not isinstance(required,list)or not required or len(set(required))!=len(required):return None
    results=record.get('program_checks')
    if not isinstance(results,list):return None
    by_id={r.get('checker_id'):r for r in results if isinstance(r,dict)}
    if len(by_id)!=len(results)or set(by_id)!=set(required):return None
    values=[]
    for identity in required:
        result=by_id[identity]
        if type(result.get('passed'))is not bool or result.get('call_id')!=record.get('first_action_call_id') \
            or not re.fullmatch(r'[a-f0-9]{64}',result.get('evidence_sha256','')):return None
        values.append(result['passed'])
    return all(values)


def extract_task_opportunity(gold,records,*,action_evidence=None):
    rows=[r for r in records if r.get('stage_id')==gold['stage_id']]
    boundaries=[r for r in rows if r['event']=='task_registry_checkpoint']
    starts=[r for r in boundaries if r.get('phase')=='agent_start']
    ends=[r for r in boundaries if r.get('phase')=='agent_end']
    complete=bool(starts and ends)and all(r.get('registry',{}).get('complete')is True
        and isinstance(r.get('registry',{}).get('tasks'),list)for r in boundaries)
    initial=starts[0].get('registry',{}).get('tasks')if starts else None
    final=ends[-1].get('registry',{}).get('tasks')if ends else None
    calls=[r for r in rows if r['event']=='tool_call']
    replies={}
    for row in rows:
        if row['event']=='tool_execution_end'or row['event']=='tool_result'and row.get('call_id')not in replies:
            replies[row.get('call_id')]=row
    if any(c.get('call_id')not in replies for c in calls):complete=False
    for phase in ('before_tool','after_tool'):
        ids={r.get('call_id')for r in boundaries if r.get('phase')==phase}
        if ids!={r.get('call_id')for r in calls}:complete=False
    obs={'complete':complete,'reason':None if complete else 'initial/terminal registry, complete tools or durable inventory missing'}
    if gold['kind']=='retrieval':
        queries=[r for r in calls if r.get('tool')=='task_find']
        if not queries:
            # Only an explicitly registered query-required opportunity can count
            # absence of search as a miss. Legal direct-ID restore is a T2 case.
            if complete and gold.get('requires_query')is True:
                return dict(obs,limit=gold['k'],candidates=[],reason='registered query was not executed')
            return dict(obs,complete=False,reason='search opportunity or query evidence absent')
        query=queries[0]; reply=replies.get(query['call_id'])
        args=query['_value'].get('input')
        if not isinstance(args,dict)or not isinstance(args.get('query'),str)or not reply:
            return dict(obs,complete=False,reason='actual query arguments/result missing')
        result=reply['_value']
        effective=args.get('limit',gold.get('frozen_default_limit'))
        candidates=[]
        if result.get('isError')is True:
            return dict(obs,limit=effective,candidates=[],query=args['query'],query_failed=True)
        try:
            data=json.loads('\n'.join(p['text']for p in result.get('result',result)['content']if p.get('type')=='text'))
        except (ValueError,KeyError,TypeError):
            return dict(obs,complete=False,reason='candidate result cannot be parsed')
        if result.get('isError')is not False or not isinstance(data,list)or any(not isinstance(c,dict)
            or not isinstance(c.get('task_id'),str)for c in data):
            return dict(obs,complete=False,reason='candidate IDs or result status missing')
        candidates=[c['task_id']for c in data]
        query_registry=next((r['registry']for r in boundaries if r.get('phase')=='before_tool'and r.get('call_id')==query['call_id']),None)
        available={t['task_id']for t in query_registry['tasks']}if query_registry and query_registry.get('complete')is True else None
        if available is not None and not set(gold['relevant'])<=available:
            raise ValueError('retrieval gold includes a Task absent from the query-time durable corpus')
        return dict(obs,limit=effective,candidates=candidates,query=args['query'],
            first_query_call_id=query['call_id'],raw_candidates=data,
            corpus_task_ids=sorted(available)if available is not None else None,
            query_index=(query_registry or{}).get('index'),
            legal_candidate_count=sum(c in available and c not in candidates[:i]for i,c in enumerate(candidates))if available is not None else None)
    if gold['kind']=='restore':
        action=action_evidence or{}
        critical=next((r for r in calls if r.get('tool')in gold['critical_tools']and
            (gold.get('critical_boundary')!='program_action_call_id'or
             r.get('call_id')==action.get('first_action_call_id'))),None)
        before=next((r for r in boundaries if critical and r.get('phase')=='before_tool'and r.get('call_id')==critical['call_id']),None)
        bound=(before or{}).get('binding',{}).get('task_id')
        if before and before.get('binding',{}).get('status')in {'NO_BOUND_TASK','CAPTURED'}:obs['bound']=bound
        if critical and action.get('first_action_call_id')==critical['call_id']:
            obs['action_passed']=_program_action(action,gold)
        else:obs['action_passed']=None
        obs['request_current']=None
        prepared=[r for r in rows if critical and r['event']=='request_ready'and r['_order']<critical['_order']]
        if prepared and before:
            b=prepared[-1].get('prepared_boundary')or{}
            binding=before.get('binding')or{}
            # Exact observed prepare version/scope, not inferred global freshness.
            delivered=prepared[-1].get('_delivered_state')
            if b.get('expected_task_id')is not None and type(b.get('expected_version_at_prepare'))is int \
                and binding.get('status')=='CAPTURED'and isinstance(delivered,list):
                obs['request_current']=len(delivered)==1 and delivered[0]=={
                    'task_id':bound,'version':b['expected_version_at_prepare']}and b['expected_task_id']==bound
        if complete and critical is None:obs.update(bound=None,request_current=False,action_passed=False)
        if gold.get('critical_boundary')=='program_action_call_id'and action.get('first_action_call_id')and critical is None:
            obs.update(complete=False,reason='program action is not linked to an observed permitted tool call')
        return obs
    if gold['kind']!='route':raise ValueError('unsupported Task opportunity kind')
    if complete and initial is not None and final is not None:
        before_ids={r['task_id']for r in initial}
        # Deleted/reverted objects still count as having existed during the opportunity.
        created={t['task_id']for r in boundaries for t in r['registry']['tasks']}-before_ids
        obs['created_ids']=sorted(created)
        obs['create_attempts']=sum(c.get('tool')=='task_create'for c in calls)
        binding=ends[-1].get('binding',{})
        if binding.get('status')in {'NO_BOUND_TASK','CAPTURED'}:obs['bound']=binding.get('task_id')
        obs['route']='create'if created else'resume'if any(c.get('tool')=='task_resume'for c in calls)else \
            'clarify'if any(c.get('tool')=='task_clarify'for c in calls)else'continue'if obs.get('bound')else'no-persistent-task'
        if gold.get('must_create'):
            target=[t for t in final if t['task_id']in created]
            obs['goal_scope_correct']=len(target)==1 and target[0].get('goal_sha256')==gold.get('goal_sha256') \
                and target[0].get('workspace')==gold.get('workspace')if all(k in gold for k in ('goal_sha256','workspace'))else None
            if gold.get('closed_set_route_id'):
                from .fixed35_switch_probes import route_marker
                projections=[t.get('_projection')for t in target]
                obs['goal_scope_correct']=(len(target)==1 and route_marker(projections[0].get('Goal'))==gold['closed_set_route_id']) \
                    if all(isinstance(p,dict)for p in projections)else None
                obs['goal_scope_oracle']='explicit closed-set source route identity; not a general free-text Goal judgment'
            action=action_evidence or{}
            obs['before_deadline']=action.get('creation_before_dependency')if type(action.get('creation_before_dependency'))is bool else None
            if gold.get('creation_deadline')=='first_critical_action_or_episode_end'and isinstance(gold.get('critical_tools'),list):
                critical=next((r for r in calls if r.get('tool')in gold['critical_tools']),None)
                deadline=critical['_order']if critical else ends[-1]['_order']
                commits={identity:next((r['_order']for r in boundaries if any(t['task_id']==identity for t in r['registry']['tasks'])),None)for identity in created}
                obs['before_deadline']=bool(created)and all(position is not None and position<deadline for position in commits.values())
        if gold.get('simple'):
            answer=_answer(rows)
            obs['answer_passed']=None if answer is None or not isinstance(gold.get('accepted_answers'),list)else answer.strip()in gold['accepted_answers']
            protected=gold.get('protected_fields')
            if isinstance(protected,dict)and protected and all(isinstance(fields,list)and fields for fields in protected.values()):
                def projection(tasks):
                    by_id={t['task_id']:t for t in tasks};out={}
                    for identity,fields in protected.items():
                        source=by_id.get(identity,{}).get('_projection')
                        if not isinstance(source,dict):return None
                        out[identity]={field:source.get(field)for field in fields}
                    return out
                before=projection(initial);observed=[projection(r['registry']['tasks'])for r in boundaries]
                obs['protected_unchanged']=None if before is None or any(p is None for p in observed)or any(v is None for fields in before.values()for v in fields.values())else all(p==before for p in observed)
    return obs


def load_task_records(trial):
    events,locations=case_events(trial);records=[]
    for index,event in enumerate(events):
        row=dict(event,_order=index)
        if event['event']in {'tool_call','tool_execution_end','tool_result','assistant_return'}:
            row['_value']=json.loads(read_object(locations[(event['producer_id'],event['sequence'])],event['record_ref']))
        if event['event']=='request_ready'and event.get('payload_ref'):
            payload=json.loads(read_object(locations[(event['producer_id'],event['sequence'])],event['payload_ref']))
            row['_delivered_state']=delivered_state_blocks(payload)
        if event['event']=='task_registry_checkpoint':
            row['registry']=json.loads(json.dumps(event['registry']))
            for task in row['registry'].get('tasks',[]):
                if task.get('journal_ref'):
                    raw=read_object(locations[(event['producer_id'],event['sequence'])],task['journal_ref'])
                    task['_projection']=journal_projection([json.loads(line)for line in raw.decode().splitlines()])
        records.append(row)
    return events,records


def task_observation_complete(spec,observed):
    """A known failed verdict never waives required observation fields."""
    if observed.get('complete')is not True:return False
    if spec['kind']=='retrieval':return type(observed.get('limit'))is int and isinstance(observed.get('candidates'),list)
    if spec['kind']=='restore':return 'bound'in observed and all(type(observed.get(k))is bool
        for k in ['request_current','action_passed'])
    if not isinstance(observed.get('created_ids'),list):return False
    if spec.get('must_create')and any(type(observed.get(k))is not bool for k in ['goal_scope_correct','before_deadline']):return False
    if spec.get('simple')and any(type(observed.get(k))is not bool for k in ['answer_passed','protected_unchanged',
            *(['return_action_passed']if spec.get('return_opportunity_id')else[])]):return False
    for name in spec.get('required_route_checks',[]):
        program=observed.get('program_route_checks');check=program.get(name,{})if isinstance(program,dict)else{}
        if not isinstance(check,dict)or type(check.get('passed'))is not bool or not check.get('evidence_ids'):return False
    return True


def grade_task_trial(trial,contract,*,action_evidence=None):
    events,records=load_task_records(trial)
    observations={g['id']:extract_task_opportunity(g,records,
        action_evidence=(action_evidence or{}).get(g['id']))for g in contract['opportunities']}
    specifications={g['id']:g for g in contract['opportunities']}
    for spec in contract['opportunities']:
        identity=spec.get('return_opportunity_id')
        if not identity:continue
        if identity not in specifications or specifications[identity]['kind']!='restore':
            raise ValueError('return dependency must refer to a fixed restore opportunity')
        restored=observations[identity];value=None
        if restored.get('complete')is True and 'bound'in restored:
            values=[restored['bound']in specifications[identity]['targets'],
                restored.get('request_current'),restored.get('action_passed')]
            value=False if False in values else True if all(type(v)is bool and v for v in values)else None
        observations[spec['id']]['return_action_passed']=value
    from .fixed35_business import execution_boundaries
    coverage=execution_boundaries(trial,events)
    if not coverage['complete']:
        for observed in observations.values():observed.update(complete=False,reason='independent Pi execution boundaries incomplete')
    result=evaluate_behavior({'version':contract['version'],'cases':contract['opportunities']},observations)
    result.update(extractor_version=VERSION,observations=observations,boundary_coverage=coverage,
        fixture_only=contract.get('fixture_only')is True,
        interpretation='real Task protocol evidence plus explicit evaluator program actions; fixtures never count as model behavior')
    result['collection_complete']=coverage['complete']and all(task_observation_complete(s,observations[s['id']])for s in contract['opportunities'])
    return result
