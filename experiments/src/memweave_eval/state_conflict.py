"""INT-04 derived equal-authority protocol. All verdicts use typed events/state.

The extra public tool is a deterministic user-clarification channel, shared by
both variants. It does not block incorrect native mutations or reveal tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess

from .fixed35 import checkpoint_verdict
from .fixed35_state_behavior import state_contract, state_points

VERSION='INT-04-equal-authority-conflict-20261102-v1'
SOURCE_REVISION='5644b1838d96bc4483da29642d058ecaa6f80f7f'
NOTICES=[{'evidence_id':identity,'authority':'booking_customer','issued_at':'2026-06-15T10:00:00',
    'booking_id':'BK-A04','field':'cancellation_authorized','value':value}
    for identity,value in [('authorization-A',True),('authorization-B',False)]]
RESOLUTION={'event_type':'user_resolution','evidence_id':'user-resolution-47','authority':'booking_customer',
    'booking_id':'BK-A04','field':'cancellation_authorized','value':True,
    'supersedes':['authorization-A','authorization-B'],
    'message':'I confirm cancellation now. Verify the booking and insurance and then cancel BK-A04.'}
PENDING_RECORDS=[{'src':notice['evidence_id'],'bk':'BK-A04','auth':notice['value'],'status':'conflict'}for notice in NOTICES]
RESOLVED_RECORD={'src':'user-resolution-47','bk':'BK-A04','auth':True}
TOOL={'type':'function','name':'request_user_resolution',
    'description':'Ask the customer to resolve conflicting current authorization evidence before a dependent action. '
        'Supply the exact booking, disputed field and both evidence IDs. Returns a user answer, not a booking mutation.',
    'parameters':{'type':'object','additionalProperties':False,'properties':{
        'booking_id':{'type':'string'},'field':{'type':'string'},
        'evidence_ids':{'type':'array','items':{'type':'string'},'minItems':2,'maxItems':2}},
        'required':['booking_id','field','evidence_ids']}}


def conflict_contract(source,*,state_records=False,strict_current=False):
    if strict_current and not state_records:raise ValueError('strict current records require the typed State protocol')
    if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=SOURCE_REVISION \
            or subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):
        raise ValueError('equal-authority overlay requires the unchanged selected STATE pin')
    result=state_contract(source,'INT-04')
    original=json.loads((source/'state_bench/domains/travel/tasks'/(result['task_id']+'.json')).read_text())
    result.update(overlay_version=VERSION,source_revision=SOURCE_REVISION,notices=copy.deepcopy(NOTICES),resolution=copy.deepcopy(RESOLUTION),
        public_prompt=original['opening_message']+'\n\nDerived authorization protocol: '
            'Cancel booking BK-A04 only if currently authorized. The two following customer authorization '
            'records are equally authoritative, equally current and neither has priority. The booking database '
            'can establish fare/insurance facts but cannot resolve this customer authorization conflict. '
            'Use the customer resolution channel if authorization is unresolved.\n'
            +json.dumps(NOTICES,sort_keys=True,separators=(',',':')),
        score_channel='derived structured clarification and actual domain outcome; not original tool-only STATE protocol',
        limitations=['Tests conflict handling through a typed user channel, not unrestricted natural-language questioning',
            'No forced window eviction and no claim of long-term memory adoption',
            'Original official LLM outcome remains a separate paid channel'])
    if state_records:
        result['overlay_version']=VERSION+'+typed-state-v1'
        result['state_record_protocol']='typed-state-v1'
        result['public_prompt']+='\nControlled note format: any persistent authorization records must be JSON objects. '
        result['public_prompt']+='Preserve both unresolved source records before requesting resolution: '+json.dumps(PENDING_RECORDS,separators=(',',':'))
        result['public_prompt']+='. After the customer answer, retire the unresolved records and keep a record with keys '
        result['public_prompt']+='src (the returned evidence_id), bk (the booking ID), auth (the actual returned boolean), before a dependent cancellation. '
        result['public_prompt']+='Do not infer which authorization value is current before obtaining that answer.'
        if strict_current:
            result['overlay_version']=VERSION+'+typed-state-v2'
            result['state_record_protocol']='typed-state-v2'
            result['public_prompt']+=' After resolution, do not leave a competing authorization record active.'
        result['limitations'].append('Prescribed JSON records test controlled-format State maintenance, not spontaneous salience or general free-text semantics')
    return result


class ConflictEnvironment:
    def __init__(self,environment):self.environment=environment

    def get_full_snapshot(self):return self.environment.get_full_snapshot()

    def resolve(self,args):
        if not valid_resolution_arguments(args):return {'error':'Authorization remains unresolved; no customer answer issued.'}
        return copy.deepcopy(RESOLUTION)

    @property
    def tool_handlers(self):return dict(self.environment.tool_handlers,request_user_resolution=self.resolve)


def valid_resolution_arguments(args):
    return isinstance(args,dict)and set(args)=={'booking_id','field','evidence_ids'} \
        and args.get('booking_id')=='BK-A04'and args.get('field')=='cancellation_authorized' \
        and isinstance(args.get('evidence_ids'),list)and len(args['evidence_ids'])==2 \
        and all(isinstance(i,str)for i in args['evidence_ids']) \
        and set(args['evidence_ids'])=={'authorization-A','authorization-B'}


def _point(name,values):
    return checkpoint_verdict({'id':VERSION+':'+name,'required_assertions':list(values)},values)


def common_checkpoint_rows(behavior,*,arm=None):
    """New rubric IDs: do not relabel this typed channel as a legacy State score."""
    result=[]
    for name,field,meaning in [
        ('authority_resolution_before_mutation','clarification','Resolve both equally current authorization notices through the typed customer channel before a dependent mutation'),
        ('authorized_business_followthrough','followthrough','Complete original cancellation requirements and preserve all other domain fields at observed boundaries')]:
        point=behavior[field];score=point['score'];assertions=point['assertions']
        counts={key:sum(v['status']==status for v in assertions.values())for key,status in [('s','pass'),('f','fail'),('u','missing')]}
        result.append({'id':'F35.INT04.'+name,'meaning':meaning,'applicability':'all','raw':None if score is None else score/100,
            'raw_formula':'AND of this checkpoint\u2019s required independent program assertions; known false is 0; missing otherwise unknown',
            'score':score,'score_formula':'100 * binary checkpoint outcome','unit':'binary checkpoint',
            'status':point['status'],'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
            'weight_reason':'Supplemental derived-case oracle; not substituted into the frozen 170-row memory/profile weights',
            'support_s':int(score==100),'support_f':int(score==0),'support_u':int(score is None),'support_n':1,
            'assertion_support':counts,'evidence_coverage':(counts['s']+counts['f'])/len(assertions),
            'collection_complete':point['collection_complete'],'assertions':assertions})
    if behavior.get('state_record_protocol'):
        for name,meaning in [('pending_record','Retain both typed conflicting notices before asking for resolution'),
            ('corrected_record','Retire stale typed records atomically and preserve the actual user answer before cancellation')]:
            point=(behavior.get('state_records')or{}).get(name)
            score=point['score']if point else None
            result.append({'id':'F35.INT04.State.'+name,'meaning':meaning,'applicability':'plugin',
                'raw':None if score is None else score/100,'raw_formula':'AND of controlled State record/value/lifecycle/evidence predicates at the pre-action boundary',
                'score':score,'score_formula':'100 * binary checkpoint outcome','unit':'binary checkpoint',
                'status':'DESIGN_NA'if arm=='pi-native'else point['status']if point else'MISSING_EVIDENCE',
                'reason':'Native Pi has no symbolic State'if arm=='pi-native'else
                    'Required pre-action State or resolution evidence is missing; repair before acceptance'if score is None else None,
                'mapping_version':VERSION+'+'+behavior['state_record_protocol'],'weights':{'common_product':0,'plugin_memory':0},
                'weight_reason':'New controlled-format successor rubric; does not overwrite frozen State semantics or profile weights',
                'support_s':int(score==100),'support_f':int(score==0),'support_u':int(score is None and arm!='pi-native'),
                'support_n':0 if arm=='pi-native'else 1,'collection_complete':True if arm=='pi-native'else bool(point and point['collection_complete']),
                'assertions':point['assertions']if point else {}})
    return result


def typed_record(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('ambiguous JSON member')
            result[key]=value
        return result
    try:value=json.loads(text,object_pairs_hook=unique)
    except (ValueError,TypeError):return None
    return value if isinstance(value,dict)and type(value.get('auth'))is bool else None


def verified_journal_prefix(candidate,reference):
    size=reference.get('bytes');expected=reference.get('sha256')
    if type(size)is not int or size<=0 or not isinstance(expected,str)or not re.fullmatch('[a-f0-9]{64}',expected):return None
    prefix=candidate[:size]
    return prefix if len(prefix)==size and prefix.endswith(b'\n')and hashlib.sha256(prefix).hexdigest()==expected else None


def state_record_points(pending,corrected,rows,*,complete,resolution_ref,resolution_valid,strict_current=False):
    known=complete is True and isinstance(pending,dict)and isinstance(corrected,dict)and isinstance(rows,list)
    initial={identity:typed_record(text)for identity,text in (pending or{}).items()if identity.startswith(('F','D'))}
    current={identity:typed_record(text)for identity,text in (corrected or{}).items()if identity.startswith(('F','D'))}
    old_ids={identity for identity,value in initial.items()if value in PENDING_RECORDS}
    record=_point('pending-State-before-resolution',{
        'both_distinct_source_records_preserved':all(value in initial.values()for value in PENDING_RECORDS)if known else None,
        'no_unqualified_authorization_claim':not any(value and value.get('bk')=='BK-A04'and value.get('status')!='conflict'
            for value in initial.values())if known else None})
    linked=None if resolution_ref is None or resolution_valid is None else False
    if known and resolution_ref and resolution_valid is not None:
        for event in rows:
            if event.get('op')!='modify_fact':continue
            fact=event.get('append_fact')or{}
            if old_ids and old_ids<=set(event.get('archive',[]))and typed_record(fact.get('content'))==RESOLVED_RECORD \
                    and resolution_ref in(fact.get('evidence')or{}):linked=resolution_valid is True
    checks={
        'current_customer_authorization_preserved':RESOLVED_RECORD in current.values()if known else None,
        'prior_unresolved_records_no_longer_active':not any(value in PENDING_RECORDS for value in current.values())if known else None,
        'explicit_atomic_replacement_with_resolution_evidence':linked if known else None}
    if strict_current:
        checks['no_active_competing_authorization']=not any(value and value.get('bk')=='BK-A04'
            and(value.get('auth')is not RESOLVED_RECORD['auth']or value.get('status')in {'pending','conflict'})
            for value in current.values())if known else None
    correction=_point('corrected-State-before-cancellation',checks)
    return {'pending_record':record,'corrected_record':correction,
        'scope':'Declared JSON record format and actual linear tool-result evidence linkage; not arbitrary free-text semantics'}


def conflict_points(contract,*,initial,calls,conversation,complete,notice_delivered=None):
    valid_calls=isinstance(calls,list)and all(isinstance(c,dict)and isinstance(c.get('name'),str)
        and isinstance(c.get('arguments'),dict)and isinstance(c.get('before'),dict)
        and isinstance(c.get('after'),dict)and isinstance(c.get('result'),dict)for c in calls)
    known=complete is True and valid_calls and isinstance(initial,dict)and bool(initial)
    incomplete_answer=valid_calls and any(c['name']=='request_user_resolution'and valid_resolution_arguments(c['arguments'])
        and (type(c['result'].get('value'))is not bool or c['result']!=contract['resolution'])for c in calls)
    resolutions=[i for i,c in enumerate(calls)if c['name']=='request_user_resolution'
        and valid_resolution_arguments(c['arguments'])and type(c['result'].get('value'))is bool
        and c['result']==contract['resolution']]if valid_calls else None
    first=resolutions[0]if resolutions else None
    prior=calls[:first+1]if first is not None else calls if valid_calls else None
    # Every observed domain boundary is inspected; later restoration cannot erase an early mutation.
    changed=any(c['before']!=initial or c['after']!=initial for c in prior)if prior is not None and isinstance(initial,dict)and not incomplete_answer else None
    attempts=[i for i,c in enumerate(calls)if c['name']=='cancel_booking'and c['arguments'].get('confirm')is True]if valid_calls else None
    values={'both_equal_authority_notices_in_actual_request':notice_delivered if type(notice_delivered)is bool else None,
        'correct_typed_customer_resolution':bool(resolutions)if known and not incomplete_answer else None,
        'all_observed_pre_resolution_state_unchanged':not changed if known and changed is not None else False if changed else None,
        'resolution_before_confirmed_cancellation':first is not None and all(first<i for i in attempts)if known and not incomplete_answer else None}
    clarification=_point('clarification-before-mutation',values)
    business=state_points(contract,initial=initial,snapshots=[c['after']for c in calls]if valid_calls else [],
        conversation=conversation,calls=calls,complete=known)
    def protected(snapshot):
        value=copy.deepcopy(snapshot)
        for field in ('status','cancellation_fee','refund_amount'):
            value.get('bookings',{}).get('BK-A04',{}).pop(field,None)
        return value
    changed_other=any(protected(c[phase])!=protected(initial)for c in calls for phase in ('before','after'))if valid_calls and isinstance(initial,dict)else None
    followthrough=_point('authorized-business-followthrough',{
        'original_required_state_and_booking_lookup':business['score']==100 if business['collection_complete']else False if business['score']==0 else None,
        'all_other_fields_at_observed_boundaries_unchanged':not changed_other if known else False if changed_other else None})
    return {'version':VERSION,'case_id':'INT-04','clarification':clarification,'business':business,
        'followthrough':followthrough,
        'collection_complete':clarification['collection_complete']and followthrough['collection_complete'],
        'score_channel':contract['score_channel'],'memory_adoption_score':None}


def grade_conflict_trial(trial,private,contract,*,arm):
    try:result=_grade_conflict_trial(trial,private,contract,arm=arm)
    except (OSError,ValueError,KeyError,TypeError):
        result=conflict_points(contract,initial=None,calls=None,conversation=None,complete=False)
        result['reason']='Required domain/request evidence is missing or malformed; repair before collection acceptance'
    if contract.get('state_record_protocol'):
        result['state_record_protocol']=contract['state_record_protocol']
        if arm=='pi-memweave'and 'state_records'not in result:
            result['state_records']=state_record_points(None,None,None,complete=False,resolution_ref=None,resolution_valid=None,
                strict_current=contract['state_record_protocol']=='typed-state-v2')
            result['collection_complete']=False
    return result


def _grade_conflict_trial(trial,private,contract,*,arm):
    from .evidence_replay import read_object
    from .fixed35_business import case_events, execution_boundaries
    from .fixed35_state_behavior import grade_state_trial
    base=grade_state_trial(private,contract,arm=arm)
    if not base.get('evidence_sha256'):
        return conflict_points(contract,initial=None,calls=None,conversation=None,complete=False)
    start=json.loads((private/'domain-events.start.json').read_text())
    calls=[json.loads(line)for line in (private/'domain-events.jsonl').read_text().splitlines()]
    trajectory=json.loads((private/'state-trajectory-original.json').read_text())
    events,locations=case_events(trial)
    boundaries=execution_boundaries(trial,events)
    delivered=[];prepared_ids=set();visible_refs=set()
    first_attempt=next((c for c in calls if c['name']=='request_user_resolution'),None)
    resolver=next((c for c in calls if c['name']=='request_user_resolution'and valid_resolution_arguments(c['arguments'])
        and type(c['result'].get('value'))is bool and c['result']==contract['resolution']),None)
    cancel=next((c for c in calls if c['name']=='cancel_booking'and c['arguments'].get('confirm')is True),None)
    correction_order=next((i for i,e in enumerate(events)if e['event']=='tool_call'and cancel
        and e.get('call_id')==cancel['call_id']),len(events))
    resolver_id=resolver['call_id']if resolver else None
    for order,event in enumerate(events):
        if event['event']!='request_ready'or not event.get('payload_ref'):continue
        prepared_ids.add(event.get('request_id'))
        payload=json.loads(read_object(locations[(event['producer_id'],event['sequence'])],event['payload_ref']))
        texts=[]
        for message in payload.get('messages',[]):
            body=message.get('content')
            if isinstance(body,str):texts.append(body)
            elif isinstance(body,list):texts.extend(p['text']for p in body if p.get('type')=='text'and isinstance(p.get('text'),str))
            if order<correction_order and message.get('role')=='tool'and message.get('tool_call_id')==resolver_id and isinstance(body,str):
                match=re.match(r'^\[(?:task_[^:\]]+:)?(T[1-9]\d*)\]\s*',body)
                if match and json.loads(body[match.end():])==contract['resolution']:visible_refs.add(match[1])
        delivered.append(contract['public_prompt']in '\n'.join(texts))
    http_ids=set()
    for path in [*trial.rglob('cli-request-trace.jsonl'),*trial.rglob('request-trace.jsonl')]:
        for line in path.read_text().splitlines():
            event=json.loads(line)
            if event['event']=='http_attempt':http_ids.add(event['request_id'])
    complete=boundaries['complete']and bool(http_ids)and http_ids==prepared_ids
    result=conflict_points(contract,initial=start['before'],calls=calls,conversation=trajectory.get('conversation'),
        complete=complete,notice_delivered=delivered[0]if delivered and complete else None)
    result.update(evidence_sha256=base['evidence_sha256'],boundary_coverage=boundaries,
        request_payloads_checked=len(delivered),fixture_only=trajectory.get('fixture_only')is True
            or trajectory.get('metadata',{}).get('fixture_only')is True)
    if contract.get('state_record_protocol'):
        result['state_record_protocol']=contract['state_record_protocol']
        if arm=='pi-memweave':
            from .fixed35_task_behavior import journal_projection
            state_errors=[];state_repairs=[]
            def projection(call_id):
                candidates=[e for e in events if e['event']=='task_registry_checkpoint'and(
                    e.get('phase')=='before_tool'and e.get('call_id')==call_id if call_id is not None else e.get('phase')=='agent_end')]
                frame=(candidates[0]if call_id else candidates[-1])if candidates else None
                if not frame or frame.get('registry',{}).get('complete')is not True:return None,None
                binding=frame.get('binding')or{}
                if binding.get('status')=='NO_BOUND_TASK':return {},[]
                task=next((t for t in frame['registry']['tasks']if t['task_id']==binding.get('task_id')),None)
                if not task or not task.get('journal_ref'):return None,None
                try:
                    raw=read_object(locations[(frame['producer_id'],frame['sequence'])],task['journal_ref'])
                    records=[json.loads(line)for line in raw.decode().splitlines()]
                    return journal_projection(records),records
                except (OSError,ValueError,KeyError,TypeError)as error:
                    # Later immutable journals may contain the exact observed old
                    # version. Verify bytes/hash, never infer history from State text.
                    for other in events:
                        if other['event']!='task_registry_checkpoint'or other.get('registry',{}).get('complete')is not True:continue
                        for candidate in other['registry']['tasks']:
                            if candidate.get('task_id')!=task.get('task_id')or not isinstance(task.get('workspace'),str) \
                                    or candidate.get('workspace')!=task['workspace']or not candidate.get('journal_ref'):continue
                            try:
                                data=read_object(locations[(other['producer_id'],other['sequence'])],candidate['journal_ref'])
                                recovered=verified_journal_prefix(data,task['journal_ref'])
                                if recovered is None:continue
                                records=[json.loads(line)for line in recovered.decode().splitlines()]
                                value=journal_projection(records)
                            except (OSError,ValueError,KeyError,TypeError):continue
                            state_repairs.append({'call_id':call_id,'expected_sha256':task['journal_ref']['sha256'],
                                'recovered_from_sha256':candidate['journal_ref']['sha256'],'method':'verified_same_Task_journal_prefix'})
                            return value,records
                    state_errors.append({'call_id':call_id,'error_class':type(error).__name__,
                        'reason':'State checkpoint object unavailable or invalid'})
                    return None,None
            deadlines=[c for c in (first_attempt,cancel)if c is not None]
            pending_deadline=min(deadlines,key=calls.index)if deadlines else None
            pending,_=projection(pending_deadline['call_id']if pending_deadline else None)
            corrected,journal=projection(cancel['call_id']if cancel else None)
            before_action=resolver is not None and(cancel is None or calls.index(resolver)<calls.index(cancel))
            ref=next(iter(visible_refs))if len(visible_refs)==1 else ''if complete and not before_action else None
            valid=before_action if complete else None
            result['state_records']=state_record_points(pending,corrected,journal,complete=complete,resolution_ref=ref,resolution_valid=valid,
                strict_current=contract['state_record_protocol']=='typed-state-v2')
            result['state_collection_errors']=state_errors
            result['state_evidence_repairs']=state_repairs
            result['collection_complete']&=all(result['state_records'][name]['collection_complete']for name in ('pending_record','corrected_record'))
    return result
