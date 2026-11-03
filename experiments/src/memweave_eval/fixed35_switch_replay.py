"""Replay selected Switch actions and real Task routing, never actor self-grades."""
from __future__ import annotations

import json
from pathlib import Path

from .behavior_metrics import evaluate_behavior
from .evidence_replay import read_object
from .fixed35 import checkpoint_verdict
from .fixed35_business import case_events, execution_boundaries
from .fixed35_switch import grade_switch_final
from .fixed35_switch_probes import VERSION, grade_probe, route_marker
from .fixed35_task_behavior import (
    extract_task_opportunity,
    load_task_records,
    task_observation_complete,
)
from .storage import file_digest

REPLAY_VERSION='fixed35-switch-replay-20261103-v4'


def source_targets(registry,route_id):
    if not isinstance(registry,dict)or registry.get('complete')is not True or not isinstance(registry.get('tasks'),list):
        return None
    result=[]
    for task in registry['tasks']:
        if not isinstance(task,dict)or not isinstance(task.get('task_id'),str):return None
        projection=task.get('_projection')
        if not isinstance(projection,dict)or not isinstance(projection.get('Goal'),str):return None
        if route_marker(projection['Goal'])==route_id:result.append(task['task_id'])
    return sorted(result)


def mutation_deadline(records,stage,slot):
    rows=[r for r in records if r.get('stage_id')==stage]
    frames=[r for r in rows if isinstance(r.get('workspace'),dict)]
    starts=[r for r in frames if r.get('phase')=='agent_start'];ends=[r for r in frames if r.get('phase')=='agent_end']
    if not starts or not ends:return None,'initial or terminal worktree boundary missing'
    initial=starts[0]['workspace'].get('git_worktrees',{}).get(slot,{})
    if initial.get('status')!='complete' or not isinstance(initial.get('projection_sha256'),str):
        return None,'initial selected worktree capture incomplete'
    for frame in frames:
        current=frame['workspace'].get('git_worktrees',{}).get(slot,{})
        if current.get('status')!='complete':return None,'worktree boundary capture incomplete before creation deadline'
        if current.get('projection_sha256')==initial['projection_sha256']:continue
        call=next((r for r in rows if r['event']=='tool_call'and r.get('call_id')==frame.get('call_id')
            and r['producer_id']==frame['producer_id']),None)
        if frame.get('phase')not in {'tool_end','tool_result'}or not call:
            return None,'source mutation observed outside a linked tool completion'
        return call['_order'],None
    return ends[-1]['_order'],None


def binding_at_deadline(records,stage,deadline,targets):
    rows=[r for r in records if r.get('stage_id')==stage]
    call=next((r for r in rows if r['_order']==deadline and r['event']=='tool_call'),None)
    candidates=[r for r in rows if r['event']=='task_registry_checkpoint'and(
        call is not None and r.get('phase')=='before_tool'and r.get('call_id')==call.get('call_id')
        and r['producer_id']==call['producer_id'] or call is None and r.get('phase')=='agent_end')]
    record=candidates[-1]if candidates and deadline is not None else None
    binding=(record or{}).get('binding',{})
    known=record and binding.get('status')in {'NO_BOUND_TASK','CAPTURED'}and targets is not None
    return {'passed':binding.get('task_id')in targets if known else None,
        'evidence_ids':[record['event_sha256']]if record and record.get('event_sha256')else[]}


def unchanged_until_probe(rows,first,slots):
    frames=[e for e in rows if isinstance(e.get('workspace'),dict)]
    start=next((e for e in frames if e.get('phase')=='agent_start'),None)
    if not start or not slots:return None
    initial=start['workspace'].get('git_worktrees',{})
    if any(initial.get(slot,{}).get('status')!='complete'or not isinstance(
        initial.get(slot,{}).get('projection_sha256'),str)for slot in slots):return None
    changed=False;missing=False
    for e in frames:
        current=e['workspace'].get('git_worktrees',{})
        for slot in slots:
            item=current.get(slot,{})
            if item.get('status')!='complete':missing=True
            elif item.get('projection_sha256')!=initial[slot]['projection_sha256']:changed=True
        if e is first:break
    return False if changed else None if missing else True


def probe_action(trial,probe,events,locations,records,*,worktrees):
    rows=[e for e in events if e.get('stage_id')==probe['stage_id']]
    frames=[e for e in rows if e['event']=='workspace_checkpoint']
    starts=[e for e in frames if e.get('phase')=='agent_start'];ends=[e for e in frames if e.get('phase')=='agent_end']
    coverage=execution_boundaries(trial/'steps'/probe['step'],rows,stage_id=probe['stage_id'])
    initial=starts[0].get('workspace',{})if starts else None;filename=probe['filename']
    initial_status=(initial or{}).get('file_status',{}).get(filename,{})
    initial_absent=(initial_status.get('status')=='absent')if initial_status else None
    first=None
    if initial_absent:
        first=next((e for e in frames if e.get('phase')in {'tool_end','tool_result'}and
            isinstance(e.get('workspace',{}).get('files',{}).get(filename),str)),None)
    text=None;ref=None;reason=None
    if first:
        workspace=first['workspace'];ref=workspace.get('file_refs',{}).get(filename)
        if ref:
            if workspace['files'][filename]!=ref.get('sha256'):
                raise ValueError('observed probe file hash and captured content differ')
            raw=read_object(locations[(first['producer_id'],first['sequence'])],ref)
            try:text=raw.decode('utf8')if len(raw)<=4096 else ''
            except UnicodeError:text=''
        elif workspace.get('file_status',{}).get(filename,{}).get('content_status')=='unsupported_link_or_size':
            text='';reason='observed output violates regular/size protocol'
    elif ends and coverage['complete']:
        text='';reason='complete checkpoint did not deliver the required new probe file'
    point=grade_probe(text,probe)
    point['assertions']['file_absent_at_checkpoint_start']={'value':initial_absent,
        'status':'missing'if initial_absent is None else'pass'if initial_absent else'fail'}
    clean=unchanged_until_probe(rows,first,worktrees)
    point['assertions']['no_observed_code_change_before_probe']={'value':clean,
        'status':'missing'if clean is None else'pass'if clean else'fail'}
    checks={k:v['value']for k,v in point['assertions'].items()}
    point=checkpoint_verdict({'id':point['checkpoint_id'],'required_assertions':list(checks)},checks)
    if not coverage['complete']:point['collection_complete']=False
    before=next((r for r in records if first and r.get('stage_id')==probe['stage_id']and
        r['event']=='task_registry_checkpoint'and r.get('phase')=='before_tool'and
        r['producer_id']==first['producer_id']and r.get('call_id')==first.get('call_id')),None)
    binding=(before or{}).get('binding',{})
    registry=(before or{}).get('registry',{})
    current=next((t.get('_projection')for t in registry.get('tasks',[])if t['task_id']==binding.get('task_id')),None)
    marker=route_marker(current.get('Goal'))if isinstance(current,dict)else None
    assertion_values={k:v['value']for k,v in point['assertions'].items()}
    def conjunction(names):
        values=[assertion_values.get(name)for name in names]
        return False if False in values else True if all(v is True for v in values)else None
    semantic=['source_constraint:'+k for k in probe['expected']if k not in {'checkout','audit_tag'}]
    values={'schema':assertion_values.get('exact_probe_schema'),
        'source_scope':assertion_values.get('source_constraint:checkout'),
        'source_contract':conjunction(semantic),'audit_tag':assertion_values.get('source_constraint:audit_tag'),
        'before_code_change':clean,
        'current_goal_identity':marker==probe['route_id']if before and binding.get('status')in {'CAPTURED','NO_BOUND_TASK'}else None}
    action={'first_action_call_id':first.get('call_id')if first else None,'program_checks':[
        {'checker_id':name,'passed':value,'call_id':first.get('call_id')if first else None,
            'evidence_sha256':ref['sha256']if ref else first.get('event_sha256')if first else None}for name,value in values.items()]}
    return {'probe':probe['id'],'checkpoint':point,'action_evidence':action,
        'first_action_call_id':action['first_action_call_id'],'payload_ref':ref,'reason':reason,
        'boundary_coverage':coverage,'step':probe['step'],'stage_id':probe['stage_id']}


def grade_switch_probe_trial(trial:Path,contract,*,arm):
    for probe in contract['probes']:
        if file_digest(Path(probe['source_path']))!=probe['source_sha256']:
            raise ValueError('selected Switch source support changed')
        for extra in probe.get('additional_source_paths',[]):
            if file_digest(Path(extra['source_path']))!=extra['source_sha256']:
                raise ValueError('selected latest Switch source update changed')
    events,locations=case_events(trial);_,records=load_task_records(trial)
    points=[probe_action(trial,p,events,locations,records,
        worktrees=contract['task_config']['workspace']['worktrees'])for p in contract['probes']]
    fixture=contract.get('fixture_only')is True or any(trial.rglob('cli-fake-upstream.jsonl'))
    result={'version':REPLAY_VERSION,'source_protocol_version':VERSION,'case_id':contract['case_id'],'common_probes':points,
        'scope':contract['scope'],'fixture_only':fixture,
        'collection_complete':all(p['checkpoint']['collection_complete']for p in points)}
    result['common_checkpoint_metric']=checkpoint_metric(points)
    result['source_final']=source_final(trial,contract,records)
    if arm=='pi-native':
        result['task_behavior']={'status':'DESIGN_NA','reason':'native Pi has no Task tools or symbolic State'}
        return result
    specs=[];observations={};unavailable=[]
    for probe,point in zip(contract['probes'],points,strict=True):
        stage=probe['stage_id'];stage_rows=[r for r in records if r.get('stage_id')==stage]
        query=next((r for r in stage_rows if r['event']=='tool_call'and r.get('tool')=='task_find'),None)
        initial=next((r for r in stage_rows if r['event']=='task_registry_checkpoint'and r.get('phase')=='agent_start'),None)
        corpus=next((r['registry']for r in stage_rows if query and r['event']=='task_registry_checkpoint'and
            r.get('phase')=='before_tool'and r.get('call_id')==query['call_id']),None)
        targets=source_targets(corpus if corpus is not None else(initial or{}).get('registry'),probe['route_id'])
        if not targets:
            unavailable.append({'probe':probe['id'],'status':'MISSING_EVIDENCE'if targets is None else'UPSTREAM_RECORD_NOT_CREATED',
                'reason':'query-time target corpus unknown'if targets is None else'complete corpus has no saved record bearing the original source identity',
                'retrieval_rates':None,'not_design_na':True,'retrieval_applicable':probe.get('search_requested',True)})
        if targets and probe.get('search_requested',True)and query:
            retrieve={'id':'T1:'+probe['id'],'kind':'retrieval','stage_id':stage,'k':3,
                'relevant':targets,'best':targets,'frozen_default_limit':5,'requires_query':True}
            obs=extract_task_opportunity(retrieve,records)
            obs['complete'] &= point['boundary_coverage']['complete']
            specs.append(retrieve);observations[retrieve['id']]=obs
        elif targets and probe.get('search_requested',True):
            unavailable.append({'probe':probe['id'],'status':'CONDITIONAL_NO_QUERY',
                'reason':'no search result was requested; legal known-ID restore is evaluated by end-to-end T2, not forced search',
                'retrieval_rates':None,'not_design_na':True,'retrieval_applicable':True})
        restore={'id':'T2:'+probe['id'],'kind':'restore','stage_id':stage,'targets':targets or[],
            'critical_tools':['write','edit','bash'],'critical_boundary':'program_action_call_id',
            'required_checkers':['schema','source_scope','source_contract','audit_tag','current_goal_identity','before_code_change']}
        obs=extract_task_opportunity(restore,records,action_evidence=point['action_evidence'])
        if targets is None:obs.update(complete=False,reason='source target corpus evidence missing')
        obs['complete'] &= point['boundary_coverage']['complete']
        specs.append(restore);observations[restore['id']]=obs
    for label in contract['route_labels']:
        stage=label['stage_id'];stage_rows=[r for r in records if r.get('stage_id')==stage]
        start=next((r for r in stage_rows if r['event']=='task_registry_checkpoint'and r.get('phase')=='agent_start'),None)
        prior=source_targets((start or{}).get('registry'),label['route_id'])
        spec={'id':'T3:'+label['route_id'],'kind':'route','stage_id':stage,
            'allowed':['create']if prior==[]else['resume','continue'],
            'must_create':prior==[],'closed_set_route_id':label['route_id'],
            'should_restore':bool(prior),'same_goal':bool(prior),
            'required_route_checks':['source_binding_before_dependency']}
        deadline,reason=mutation_deadline(records,stage,label['slot'])
        boundaries=[r for r in stage_rows if r['event']=='task_registry_checkpoint']
        initial_ids={t['task_id']for t in (start or{}).get('registry',{}).get('tasks',[])}
        commits={}
        for r in boundaries:
            for task in r['registry'].get('tasks',[]):
                if task['task_id']not in initial_ids:commits.setdefault(task['task_id'],r['_order'])
        before=(bool(commits)and all(position<deadline for position in commits.values()))if deadline is not None else None
        obs=extract_task_opportunity(spec,records,action_evidence={'creation_before_dependency':before})
        last_registry=boundaries[-1]['registry']if boundaries else None
        goal_targets=source_targets(last_registry,label['route_id'])
        target_ids=([identity for identity in goal_targets if identity in commits]if goal_targets is not None else None)if prior==[]else prior
        obs['program_route_checks']={'source_binding_before_dependency':binding_at_deadline(records,stage,deadline,target_ids)}
        coverage=execution_boundaries(trial/'steps'/label['first_source_step'],[r for r in events if r.get('stage_id')==stage],stage_id=stage)
        obs['complete'] &= coverage['complete']and prior is not None and deadline is not None
        obs.update(creation_boundary_reason=reason,source_identity=label['route_id'],deadline_order=deadline)
        specs.append(spec);observations[spec['id']]=obs
    first={label['first_source_step']for label in contract['route_labels']};previous=None
    for route in contract['source_component']['route_ledger']:
        step=route['source_step'];slot=route['goal_slot'];same=slot==previous;previous=slot
        if step in first:continue
        stage=contract['original_stage_ids'][step]
        label=next(label for label in contract['route_labels']if label['slot']==slot)
        initial=next((r for r in records if r.get('stage_id')==stage and r['event']=='task_registry_checkpoint'
            and r.get('phase')=='agent_start'),None)
        targets=source_targets((initial or{}).get('registry'),label['route_id'])
        spec={'id':'T3-followup:'+step,'kind':'route','stage_id':stage,'allowed':['continue','resume'],
            'must_create':False,'same_goal':same,'should_restore':not same,
            'required_route_checks':['source_binding_before_dependency']}
        deadline,reason=mutation_deadline(records,stage,slot)
        obs=extract_task_opportunity(spec,records)
        obs['program_route_checks']={'source_binding_before_dependency':binding_at_deadline(records,stage,deadline,targets)}
        coverage=execution_boundaries(trial/'steps'/step,[r for r in events if r.get('stage_id')==stage],stage_id=stage)
        obs['complete'] &= coverage['complete']and targets is not None and deadline is not None
        obs.update(creation_boundary_reason=reason,upstream_record_missing=targets==[])
        specs.append(spec);observations[spec['id']]=obs
    stage=contract['ephemeral_stage_id'];stage_rows=[r for r in records if r.get('stage_id')==stage]
    start=next((r for r in stage_rows if r['event']=='task_registry_checkpoint'and r.get('phase')=='agent_start'),None)
    inventory=(start or{}).get('registry',{}).get('tasks')
    protected={t['task_id']:list(t['_projection'])for t in inventory if isinstance(t.get('_projection'),dict)}if isinstance(inventory,list)else None
    simple={'id':'T4:temporary-conversion','kind':'route','stage_id':stage,'allowed':['continue','no-persistent-task'],
        'simple':True,'accepted_answers':['42'],'protected_fields':protected,
        'return_opportunity_id':'T2:ephemeral-return'}
    obs=extract_task_opportunity(simple,records)
    if inventory==[]:obs['protected_unchanged']=True
    coverage=execution_boundaries(trial/'steps'/contract['ephemeral_step'],[r for r in events if r.get('stage_id')==stage],stage_id=stage)
    restored=observations.get('T2:ephemeral-return',{})
    values=[restored.get('bound')in next(s['targets']for s in specs if s['id']=='T2:ephemeral-return'),
        restored.get('request_current'),restored.get('action_passed')]
    obs['return_action_passed']=(False if False in values else True if all(v is True for v in values)else None)if restored.get('complete')else None
    obs['complete'] &= coverage['complete']and protected is not None
    specs.append(simple);observations[simple['id']]=obs
    result['task_behavior']=evaluate_behavior({'version':REPLAY_VERSION,'cases':specs},observations)
    for name in ['hit_at_k','recall_at_k','best_top1','top1_given_best_hit']:
        metric=result['task_behavior']['metrics'].setdefault(name,{'value':None,'numerator':0,'denominator':0,'unknown':0,'not_applicable':0})
        for item in unavailable:
            if item.get('retrieval_applicable'):
                metric['unknown'if item['status']=='MISSING_EVIDENCE'else'not_applicable']+=1
        metric.update(value=metric['numerator']/metric['denominator']if metric['denominator']and not metric['unknown']else None,
            status='unknown'if metric['unknown']else'scored'if metric['denominator']else'not_applicable',
            reason='query corpus evidence missing'if metric['unknown']else
                'actual queries only; legal known-ID recovery is kept in the complete T2 intent denominator')
    result['task_behavior'].update(observations=observations,unavailable_target_opportunities=unavailable,
        interpretation='Closed-set source Goal IDs and first synchronous recalled-contract artifact; not arbitrary source-edit correctness.')
    result['task_checkpoint_metrics']=task_checkpoint_metrics(result['task_behavior'])
    result['collection_complete'] &= not any(u['status']=='MISSING_EVIDENCE'for u in unavailable)
    missing=[s['id']for s in specs if not task_observation_complete(s,observations[s['id']])]
    result['missing_task_observation_ids']=missing
    result['collection_complete'] &= not missing
    return result


def source_final(trial,contract,records):
    final_stage=contract['original_stage_ids']['final'];answer=None
    for row in records:
        if row.get('stage_id')==final_stage and row['event']=='assistant_return':
            parts=row.get('_value',{}).get('content')
            if isinstance(parts,list):
                text=[p['text']for p in parts if p.get('type')=='text'and isinstance(p.get('text'),str)]
                if text:answer='\n'.join(text)
    folder=trial/'steps/final/verifier';files={};values={}
    for key,name in [('outcomes','candidate.outcomes.json'),('original_result','result.json')]:
        source=folder/name
        if source.is_symlink()or not source.resolve().is_relative_to(trial.resolve()):
            raise ValueError('redirected original Switch verifier artifact')
        values[key]=json.loads(source.read_text())if source.exists()else None
        if source.exists():files[name]=file_digest(source)
    result=grade_switch_final(contract['source_component'],answer=answer,**values)
    result['source_sha256']=files
    expected=list(dict.fromkeys(contract['source_component']['f2p']+contract['source_component']['p2p']))
    outcomes=values['outcomes'];graded=isinstance(values['original_result'],dict)and values['original_result'].get('status')=='graded'
    complete=graded and isinstance(outcomes,dict)and all(isinstance(outcomes.get(i),str)
        and outcomes[i]in {'pass','fail','error'}for i in expected)
    result['native_metrics']={'passed':sum(outcomes[i]=='pass'for i in expected)if complete else None,
        'total':len(expected),'status':'scored'if complete else'unknown',
        'reason':'original pinned F2P/P2P test IDs only; missing original verifier is not a derived probe failure'}
    return result


def checkpoint_metric(points):
    """Each independent probe is one opportunity; assertions are ANDed inside it."""
    values=[p['checkpoint'].get('score')for p in points]
    known=[v for v in values if v in (0,100)]
    unknown=len(values)-len(known);success=sum(v==100 for v in known)
    return {'value':success/len(known)if known and not unknown else None,
        'numerator':success,'denominator':len(known),'unknown':unknown,
        'status':'unknown'if unknown else'scored'if known else'not_applicable',
        'reason':'AND of schema, every source constraint, source scope and early audit tag, '
            'then equal mean across preregistered distinct probe checkpoints; not an original code-test outcome'}


def task_checkpoint_metrics(behavior):
    groups={'T1-retrieval-ranking':lambda c:c['kind']=='retrieval',
        'T2-current-task-restore':lambda c:c['kind']=='restore',
        'T3-independent-goal-create':lambda c:c['case_id'].startswith('T3:'),
        'T4-ephemeral-interruption':lambda c:c['case_id']=='T4:temporary-conversion'}
    result={}
    for name,predicate in groups.items():
        cases=[c for c in behavior['cases']if predicate(c)]
        eligible=[c for c in cases if c.get('status')!='not_applicable']
        known=[c for c in eligible if c.get('status')=='scored'and c['value']in (0,1)]
        success=sum(c['value']==1 for c in known);unknown=len(eligible)-len(known)
        result['S.case_v2.'+name]={'value':success/len(known)if known and not unknown else None,
            'numerator':success,'denominator':len(known),'unknown':unknown,
            'status':'unknown'if unknown else'scored'if known else'not_applicable',
            'reason':'AND within each source-bound opportunity, equal mean across opportunities; '
                'legal direct-ID restore is not a retrieval opportunity; no duplicate child-assertion weighting'}
    return result
