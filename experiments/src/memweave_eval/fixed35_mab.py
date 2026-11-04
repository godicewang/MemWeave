"""Frozen MAB action and finite-literal memory predicates, never an LLM judge.

Literal retention is deliberately a controlled parser score, not a claim that all
free-form paraphrases have been understood. Gold and future facts remain host-only.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .evidence_replay import read_object, replay_content
from .fixed35 import checkpoint_verdict
from .fixed35_adapters import normalize_mab, score_mab
from .storage import atomic_json, file_digest

MAB_RELATIONS={
    'MAB-01':{'required_relation_sets':[[['Microsoft','Steve Jobs']]],
        'forbidden_relations':[['Microsoft','Satya Nadella']]},
    'MAB-02':{'required_relation_sets':[[['Bagratuni','Taipei']],
        [['Bagratuni','Christianity'],['Christianity','Taipei']]],
        'forbidden_relations':[['Christianity','Jerusalem']]},
    'MAB-03':{'required_relation_sets':[[['Christian Abbiati','Philippines']],
        [['Christian Abbiati','cornerback'],['cornerback','field hockey'],['field hockey','Philippines']]],
        'forbidden_relations':[['Christian Abbiati','goalkeeper'],['cornerback','American football'],['field hockey','England']]},
    'MAB-05':{'required_relation_sets':[[['New York Times','Ancient Greek']]],
        'forbidden_relations':[['New York Times','English']]},
}


def prepare_mab_components(adapter:Path,output:Path):
    """Freeze evaluator components, not admissions or claims of C1/C4 coverage."""
    output.mkdir(parents=True,exist_ok=False);records=[]
    for number in range(1,9):
        identity=f'MAB-{number:02d}';task=adapter/'actor-tasks'/identity
        config=tomllib.loads((task/'task.toml').read_text());steps=config['steps']
        if not steps or steps[-1]['name']!='query':raise ValueError('fixed final query step missing')
        gold_path=adapter/'evaluator-only'/identity/'gold.json';gold=json.loads(gold_path.read_text())
        instructions=[task/'steps'/s['name']/'instruction.md'for s in steps]
        contract={'version':'fixed35-mab-business-20261102-v2','case_id':identity,
            'answers':gold['answers'],'selector':gold['selector'],'gold_sha256':file_digest(gold_path),
            'action_observation':'workspace-content-v2','query_stage_id':str(len(steps)),
            'source_instruction_path':str(instructions[0]),'source_instruction_sha256':file_digest(instructions[0]),
            'instruction_sha256':{s['name']:file_digest(p)for s,p in zip(steps,instructions,strict=True)},
            'literal_memory':MAB_RELATIONS.get(identity),
            'task_config':{'workspace':{'root':'/app','files':['answer.json'],'content_files':['answer.json']}},
            'model_visible_changes':[],
            'component_status':'IMPLEMENTED_SOURCE_FROZEN_NOT_ADMITTED',
            'remaining':['complete case metric matrix and paid runtime canary',
                'three actual eviction checkpoints where assigned; no filler or assumed eviction',
                'book-specific valuable-evidence retention oracle where assigned']}
        atomic_json(output/(identity+'.json'),contract,immutable=True)
        records.append({'case_id':identity,'contract_sha256':file_digest(output/(identity+'.json')),
            'literal_correction_component':identity in MAB_RELATIONS,'query_stage_id':contract['query_stage_id']})
    atomic_json(output/'manifest.json',{'components':records,'real_model_calls':0,
        'not_formal_admission':True},immutable=True)
    return {'components':8,'correction_components':len(MAB_RELATIONS),'paid_requests':0,'output':str(output)}


def state_text_projection(journal):
    """Window visibility and semantic retirement are separate State contracts."""
    entries={};counts={'F':0,'D':0};seen=set()
    for row in journal:
        if row['op_id']in seen:
            raise ValueError('duplicate committed operation')
        seen.add(row['op_id']);op=row['op']
        if op=='modify_fact':
            for identity in row['archive']:
                entries[identity].update(visible=False,archived=True)
            counts['F']+=1
            entries['F'+str(counts['F'])]={'text':row['append_fact']['content'],'visible':True,'archived':False,'position':len(seen)}
        elif op in {'append_fact','append_decision'}:
            kind='F'if op=='append_fact'else'D';counts[kind]+=1
            if row['id']!=kind+str(counts[kind]):
                raise ValueError('non-contiguous State identifier')
            entries[row['id']]={'text':row['fact'if kind=='F'else'decision'],'visible':True,'archived':False,'position':len(seen)}
        elif op=='slide_window':
            for identity,entry in entries.items():
                if row['evicted_range']['from']<=entry['position']<=row['evicted_range']['to'] and identity not in row['retained_ids']:
                    entry['visible']=False
        elif op!='update_goal':
            raise ValueError('unsupported State operation')
    return {'visible':[e['text']for e in entries.values()if e['visible']and not e['archived']],
        'unarchived':[e['text']for e in entries.values()if not e['archived']]}


def active_text(journal):
    """Historical API for the currently visible, unarchived State display."""
    return state_text_projection(journal)['visible']


def literal_snapshot(texts, contract):
    if texts is None:
        return {'required_relations':None,'obsolete_relations_absent':None}
    # Explicit literal, same-entry matching prevents an unrelated occurrence of an
    # answer name from satisfying an entity/relation checkpoint.
    values=[normalize_mab(t)for t in texts]
    def has(parts):
        return any(all(re.search(r'(?<!\w)'+re.escape(normalize_mab(p))+r'(?!\w)',v)for p in parts)for v in values)
    alternatives=contract.get('required_relation_sets',[contract.get('required_relations')])
    if not isinstance(alternatives,list)or not alternatives or any(not isinstance(group,list)or not group
            or any(not isinstance(parts,list)or not parts or any(not isinstance(p,str)or not p.strip()for p in parts)for parts in group)for group in alternatives):
        raise ValueError('nonempty finite relation alternatives required')
    return {'required_relations':any(all(has(parts)for parts in group)for group in alternatives),
            'obsolete_relations_absent':not any(has(p)for p in contract.get('forbidden_relations',[]))}


def grade_action(prediction, answers, action, *, action_observation_complete):
    score=score_mab(prediction,answers,action if action is not None else {} if action_observation_complete else None)
    # File-value evidence is independent of whether the final text was captured.
    file_score=score_mab('',answers,action if action is not None else {} if action_observation_complete else None)
    score['typed_action']=file_score['typed_action']
    checks={'answer_correct':None if prediction is None else bool(score['strict_answer']),
            'file_schema':None if not action_observation_complete else isinstance(action,dict)and set(action)=={'value'}and isinstance(action['value'],str),
            'file_value':None if not action_observation_complete else bool(file_score['typed_action'])}
    point=checkpoint_verdict({'id':'F35.MAB.typed-action-v1','required_assertions':list(checks)},checks)
    return {'native':score,'derived_action':point}


_UNSPECIFIED=object()


def grade_correction(texts, contract, *, correct_action, snapshot_before_action,unarchived_texts=_UNSPECIFIED):
    checks=literal_snapshot(texts,contract)
    checks['obsolete_relations_absent']=literal_snapshot(
        texts if unarchived_texts is _UNSPECIFIED else unarchived_texts,contract)['obsolete_relations_absent']
    checks.update(action_uses_current_value=correct_action,snapshot_precedes_action=snapshot_before_action)
    return checkpoint_verdict({'id':'F35.C5.current-memory-before-action-v2','required_assertions':list(checks)},checks)


def grade_three_evictions(snapshots, *, observation_complete, require_identity=False):
    required=['eviction_1','eviction_2','eviction_3']
    checks={};points=[]
    boundaries=set()
    for index,name in enumerate(required):
        item=snapshots[index]if snapshots is not None and index<len(snapshots)else{}
        boundary=item.get('boundary_id')
        independent=boundary not in boundaries if isinstance(boundary,str)and boundary else None
        if isinstance(boundary,str)and boundary:boundaries.add(boundary)
        values={field:item.get(field)for field in ['original_source_absent','current_facts_retained','delivered_version_correct']}
        values['independent_boundary_id']=independent
        if require_identity:values['window_projection_correct']=item.get('window_projection_correct')
        points.append(checkpoint_verdict({'id':name,'required_assertions':list(values)},values))
        checks.update({name+':'+field:value for field,value in values.items()})
    if require_identity:checks['whole_boundary_sequence_complete']=True if observation_complete else None
    point=checkpoint_verdict({'id':'F35.C4.three-actual-evictions-v2','required_assertions':list(checks)},checks)
    point['checkpoints']=points
    point['independent_window_required']=require_identity
    if observation_complete and (snapshots is None or len(snapshots)<3):
        point.update(reason='PLANNED_OPPORTUNITY_NOT_TRIGGERED: fewer than three actual evictions',
                     opportunity_status='UNFILLED_PLANNED_SLOT')
    elif not observation_complete:
        point.update(reason='Whole episode boundary evidence incomplete; planned-slot fulfillment cannot be inferred',
            opportunity_status='UNKNOWN_INCOMPLETE_CAPTURE')
    return point


def source_visible(messages,originals,supports=()):
    """A remaining literal source excerpt is still visible even without its whole chunk."""
    needles=[*originals,*supports]
    if not needles or any(not isinstance(s,str)or not s for s in needles):raise ValueError('nonempty original source support required')
    return any(needle in message for message in messages if not message.startswith('# Symbolic State')for needle in needles)


def counterevidence_visible(messages,old_control,*,all_current_exposed):
    proof=old_control.get('counterevidence_source')
    if proof is None:return all_current_exposed
    support=proof.get('support')if isinstance(proof,dict)else None
    if not isinstance(support,str)or not support:raise ValueError('explicit counterevidence source support required')
    return source_visible(messages,[],[support])


def normalization_points(behavior,case_id):
    """Bind actual source-specific points; no generic fixture label becomes evidence."""
    memory=behavior.get('memory')or{}
    points={'S.case_v2.C5-correct-before-action':memory.get('correction'),
        'S.case_v2.C4-three-window-checkpoints':memory.get('three_evictions')}
    if 'prior_active_record_seen'in memory and memory['prior_active_record_seen']is not True:
        known=memory['prior_active_record_seen']is False
        points['S.case_v2.C5-correct-before-action']={'checkpoint_id':'F35.C5.actual-prior-card-v2','score':None,
            'status':'CONDITIONAL_NO_OPPORTUNITY'if known else'MISSING_EVIDENCE','collection_complete':known,
            'reason':'Complete source-boundary State proves no previously active canonical old card; current validity is separate, not a successful correction'if known else
                'Prior active-record eligibility at current-source exposure cannot be determined',
            'eligibility_evidence':memory.get('prior_record_boundary_evidence')}
    if case_id=='MAB-05':points['S.case_v2.C1-transient-baseline']=memory.get('correction')
    if case_id in {'MAB-06','MAB-07','MAB-08'}or case_id=='MAB-04'and \
            (behavior.get('semantic_rates')or{}).get('version')=='fixed35-mab-target-book-rates-20261104-v1':
        points['S.case_v2.C1-transient-baseline']=behavior.get('typed_book_memory')
    return points


def eviction_eligible(*,protocol,stage,valid_after,source_seen,source_visible):
    """Eligibility uses evidence exposure, never the observed memory outcome."""
    if protocol!='eligible-after-current-source-v3':return True
    return stage>=valid_after and source_seen and not source_visible


def delivered_memory(messages,boundary):
    blocks=[value for value in messages if value.startswith('# Symbolic State')]
    if 'expected_task_id'not in boundary:return None,None
    if boundary['expected_task_id']is None:return ([],not blocks)
    if len(blocks)!=1:return [],False
    task=re.search(r'^task_id: (\S+)$',blocks[0],re.MULTILINE)
    if not task or task[1]!=boundary['expected_task_id']:return [],False
    entries=re.findall(r'(?ms)^[FD]\d+ (.*?)\ne: \[',blocks[0])
    expected=boundary.get('expected_version_at_prepare');version=re.search(r'^state_version: (\d+)$',blocks[0],re.MULTILINE)
    return entries,(bool(version)and int(version[1])==expected)if type(expected)is int else None


def grade_mab_trial(trial:Path,contract,*,arm):
    from .mab_answer_evidence import query_answer
    # Only final query artifacts count; an ingestion acknowledgement is not an answer.
    agent=trial/'steps/query/agent'
    prediction,answer_proof=query_answer(trial,agent,contract)
    artifacts=agent/'fixed35-artifacts'
    presence=artifacts/'answer-presence.json'
    exists=json.loads(presence.read_text())['exists']if presence.exists()else None
    action=None
    if exists:
        try:action=json.loads((artifacts/'answer.json').read_text())
        except (ValueError,FileNotFoundError):action={}
    result=grade_action(prediction,contract['answers'],action,action_observation_complete=type(exists)is bool)
    # A source-stage terminal proof, not a missing directory, establishes failure.
    if answer_proof['source']=='known_source_stage_abort':
        result=grade_action('',contract['answers'],None,action_observation_complete=True)
    result['answer_evidence']=answer_proof
    if arm=='pi-native':
        result['memory']={'status':'DESIGN_NA','reason':'native Pi has no State'}
        return result
    records={};locations={}
    for store in trial.rglob('request-content'):
        for event in replay_content(store)['events']:
            key=event['producer_id'],event['sequence'];records[key]=event;locations[key]=store
    events=sorted(records.values(),key=lambda e:(e['timestamp'],e['producer_id'],e['sequence']))
    from .fixed35_business import execution_boundaries
    complete=execution_boundaries(trial,events)['complete']
    texts=None;semantic_texts=None;before=None;action_seen=False;evictions=[];boundaries=set();first_action_correct=None
    source=Path(contract['source_instruction_path'])
    if contract.get('source_instruction_sha256')and file_digest(source)!=contract['source_instruction_sha256']:
        raise ValueError('frozen original MAB source instruction changed')
    original=source.read_text()
    sources=contract.get('source_instruction_paths')
    originals=[original]
    if sources:
        originals=[]
        for support in sources:
            path=Path(support['path'])
            if file_digest(path)!=support['sha256']:raise ValueError('frozen current-source instruction changed')
            originals.append(path.read_text())
    support_text=[s['support']for s in sources]if sources else[]
    for support,item in zip(support_text,sources or[],strict=True):
        if support not in Path(item['path']).read_text():raise ValueError('frozen critical support missing from source instruction')
    counterproof=(contract.get('old_fact_control')or{}).get('counterevidence_source')
    if counterproof is not None:
        path=Path(counterproof['path'])
        if file_digest(path)!=counterproof['sha256']or counterproof['support']not in path.read_text():
            raise ValueError('frozen counterevidence source changed')
    source_seen=False;seen_sources=set();window_proof=None
    rate_contract=contract.get('semantic_rate_contract')
    fact_rates=rate_contract in {'target-fact-cards-v1','target-fact-cards-v2'}
    book_rates=rate_contract=='target-book-cards-v1'
    rate_enabled=fact_rates or book_rates
    if fact_rates and not contract.get('typed_fact_memory'):
        raise ValueError('target-fact semantic rates require independent typed source gold')
    if book_rates and not contract.get('typed_book_memory'):
        raise ValueError('target-book semantic rates require independent typed source gold')
    seen_changes=set();post_source_changes=[];precision_source_seen=False;prior_record_seen=None;prior_evidence=None
    def observe_changes(rows):
        if not rate_enabled:return
        for row in rows:
            identity=row['op_id']
            if identity in seen_changes:continue
            seen_changes.add(identity)
            if not precision_source_seen:continue
            if row['op']=='append_fact':post_source_changes.append(row['fact'])
            elif row['op']=='append_decision':post_source_changes.append(row['decision'])
            elif row['op']=='modify_fact':post_source_changes.append(row['append_fact']['content'])
    projection={};before_calls={};workspace_v2=contract.get('action_observation')=='workspace-content-v2'
    previous_action_hash=None;initial_action_observed=False
    for event in events:
        key=event['producer_id'],event['sequence'];store=locations[key]
        if event['event']=='memory_projection_boundary':
            projection[event['boundary_id']]=json.loads(read_object(store,event['metadata_ref']))
        if workspace_v2 and event['event']=='task_registry_checkpoint'and event.get('phase')=='before_tool':
            state=event.get('binding')or{}
            if state.get('journal_ref'):
                rows=[json.loads(line)for line in read_object(store,state['journal_ref']).decode().splitlines()]
                observe_changes(rows)
                views=state_text_projection(rows)
                before_calls[(event['producer_id'],event['call_id'])]=(views['visible'],views['unarchived'],True)
            elif state.get('status')=='NO_BOUND_TASK':before_calls[(event['producer_id'],event['call_id'])]=([],[],True)
            else:before_calls[(event['producer_id'],event['call_id'])]=(None,None,None)
        if workspace_v2 and event['event']=='workspace_checkpoint'and event.get('stage_id')==contract.get('query_stage_id'):
            workspace=event.get('workspace')or{};files=workspace.get('files')or{}
            if 'answer.json'in files:
                current_hash=files['answer.json']
                status=workspace.get('file_status',{}).get('answer.json',{})
                if event.get('phase')=='agent_start'and not initial_action_observed:
                    initial_action_observed=status.get('status')=='absent'and current_hash is None
                if event.get('phase')in {'tool_end','tool_result'}and initial_action_observed and current_hash!=previous_action_hash:
                    action_seen=True;texts,semantic_texts,before=before_calls.get((event['producer_id'],event.get('call_id')),(None,None,None))
                    ref=workspace.get('file_refs',{}).get('answer.json')
                    if ref and ref.get('sha256')==current_hash:
                        try:first_action_correct=bool(score_mab('',contract['answers'],json.loads(read_object(store,ref)))['typed_action'])
                        except ValueError:first_action_correct=False
                    else:first_action_correct=None
                    break
                previous_action_hash=current_hash
        if event['event']=='request_ready':
            boundary=event.get('prepared_boundary')or{}
            ref=boundary.get('expected_journal_ref')
            texts=None;semantic_texts=None;before=None
            if ref:
                rows=[json.loads(line)for line in read_object(store,ref).decode().splitlines()]
                observe_changes(rows)
                views=state_text_projection(rows);texts=views['visible'];semantic_texts=views['unarchived'];before=True
            elif boundary.get('expected_task_id')is None and 'expected_task_id'in boundary:
                texts=[];semantic_texts=[];before=True
            window=projection.get(boundary.get('boundary_id'),{}).get('memweave.window.v1',{}).get('data',{})
            cut=window.get('boundary_entry_id')
            payload=json.loads(read_object(store,event['payload_ref']))
            def content(message):
                raw=message.get('content')
                return raw if isinstance(raw,str)else '\n'.join(p.get('text','')for p in raw or []if isinstance(p,dict))
            messages=[content(m)for m in payload.get('messages',[])]
            visible=source_visible(messages,originals,support_text)
            for index,text in enumerate(originals):
                if any(text in value for value in messages):seen_sources.add(index)
            now_exposed=len(seen_sources)==len(originals)
            old_control=contract.get('old_fact_control')or{}
            if fact_rates and old_control and prior_evidence is None and counterevidence_visible(
                    messages,old_control,all_current_exposed=now_exposed):
                from .fixed35_fact_cards import fact_snapshot
                old=contract['old_fact_control']['card']
                aliases=next((f['relation_aliases']for f in contract['typed_fact_memory']['facts']if f['card']['s']==old['s']),[])
                prior_record_seen=fact_snapshot(semantic_texts,{'facts':[{'card':old,'relation_aliases':aliases}]})['all_current_relations']
                prior_evidence={'request_id':event['request_id'],'producer_id':event['producer_id'],'sequence':event['sequence'],
                    'payload_ref':event.get('payload_ref'),'expected_task_id':boundary.get('expected_task_id'),
                    'expected_state_version':boundary.get('expected_version_at_prepare'),'journal_ref':boundary.get('expected_journal_ref')}
            precision_source_seen=now_exposed
            stage=int(event.get('stage_id')or 0)
            eligible=eviction_eligible(protocol=contract.get('eviction_protocol'),stage=stage,
                valid_after=contract.get('literal_valid_after_stage',1),
                source_seen=len(seen_sources)==len(originals),source_visible=visible)
            if cut and cut not in boundaries and eligible:
                boundaries.add(cut)
                literal=contract.get('literal_memory')
                valid=stage>=contract.get('literal_valid_after_stage',1)
                blocks=[value for value in messages if value.startswith('# Symbolic State')]
                delivered_entries=re.findall(r'(?ms)^[FD]\d+ (.*?)\ne: \[',blocks[0])if len(blocks)==1 else None
                if contract.get('eviction_protocol')=='eligible-after-current-source-v3':
                    delivered_entries,_=delivered_memory(messages,boundary)
                keep=literal_snapshot(delivered_entries,literal)['required_relations']if literal and valid else None
                if contract.get('typed_book_memory')and valid:
                    from .fixed35_mab_cards import card_snapshot
                    checks=card_snapshot(delivered_entries,contract['typed_book_memory'])
                    keep=all(checks.values())if all(type(v)is bool for v in checks.values())else None
                if contract.get('typed_fact_memory')and valid:
                    from .fixed35_fact_cards import fact_snapshot
                    checks=fact_snapshot(delivered_entries,contract['typed_fact_memory'])
                    keep=all(checks.values())if all(type(v)is bool for v in checks.values())else None
                expected=boundary.get('expected_version_at_prepare')
                versions=[int(m.group(1))for value in blocks if (m:=re.search(r'state_version: (\d+)',value))]
                delivered=(len(versions)==1 and versions[0]==expected)if type(expected)is int else None
                if contract.get('eviction_protocol')=='eligible-after-current-source-v3':
                    _,delivered=delivered_memory(messages,boundary)
                evictions.append({'boundary_id':cut,'stage_id':stage,
                    'original_source_absent':(len(seen_sources)==len(originals)if sources else source_seen)and not visible,
                    'current_facts_retained':keep,'delivered_version_correct':delivered,
                    'request_id':event['request_id'],'expected_state_version':expected,
                    'payload_ref':event.get('payload_ref'),'journal_ref':boundary.get('expected_journal_ref'),
                    'event_identity':[event['producer_id'],event['sequence']]})
                if fact_rates:
                    from .fixed35_fact_cards import fact_snapshot
                    evictions[-1]['semantic_unarchived_checks']=fact_snapshot(semantic_texts,contract['typed_fact_memory'])
                elif book_rates:
                    from .fixed35_mab_cards import card_snapshot
                    evictions[-1]['semantic_unarchived_checks']=card_snapshot(semantic_texts,contract['typed_book_memory'])
                config=contract.get('window_contract')or{}
                if config.get('kind')in {'native-identity-plain-text-v1','native-identity-plain-text-v2'}:
                    if window_proof is None:
                        from .fixed35_identity_window import grade_identity_windows
                        try:
                            metric=grade_identity_windows(trial,[e['request_id']for e in events if e['event']=='request_ready'],
                                recent_turns=config['recent_turns'],evict_turns=config['evict_turns'],enabled=True,
                                max_source_bytes=config.get('max_source_bytes',4000000))
                            window_proof={i['id']:i for i in metric['items']}
                        except (ValueError,KeyError,OSError):window_proof={}
                    proof=window_proof.get(event['request_id'],{})
                    evictions[-1].update(window_projection_correct=proof.get('value'),independent_window_proof=proof)
            source_seen|=visible
        elif event['event']=='state_after_tool':
            snapshot=event.get('state',{});texts=None;semantic_texts=None;before=None
            if snapshot.get('journal_ref'):
                rows=[json.loads(line)for line in read_object(store,snapshot['journal_ref']).decode().splitlines()]
                observe_changes(rows)
                views=state_text_projection(rows);texts=views['visible'];semantic_texts=views['unarchived'];before=True
            elif snapshot.get('status')=='NO_BOUND_TASK':texts=[];semantic_texts=[];before=True
        elif event['event']=='tool_call':
            value=json.loads(read_object(store,event['record_ref']))
            path=(value.get('input')or{}).get('path')
            if not workspace_v2 and event['tool']in {'write','edit'} and path in {'/app/answer.json','answer.json'}:
                action_seen=True
                if event['tool']=='write':
                    try:
                        first=json.loads(value['input']['content'])
                        first_action_correct=bool(score_mab('',contract['answers'],first)['typed_action'])
                    except (ValueError,KeyError):first_action_correct=False
                break
    literal=contract.get('literal_memory')
    if contract.get('typed_book_memory'):
        from .fixed35_mab_cards import grade_book_card
        result['typed_book_memory']=grade_book_card(texts,contract['typed_book_memory'],
            unarchived_texts=semantic_texts,
            before_dependency=before if action_seen else False if complete else None,
            business_action_correct=first_action_correct if action_seen else False if complete else None)
    correction=grade_correction(texts,literal,
        unarchived_texts=semantic_texts,
        correct_action=first_action_correct,
        snapshot_before_action=before if action_seen else None)if literal else None
    if contract.get('typed_fact_memory'):
        from .fixed35_fact_cards import grade_fact_cards
        correction=grade_fact_cards(texts,contract['typed_fact_memory'],
            unarchived_texts=semantic_texts,
            correct_action=first_action_correct if action_seen else False if complete else None,
            before=before if action_seen else False if complete else None)
    if fact_rates:
        checks={key:value['value']for key,value in correction['assertions'].items()}
        checks['source_exposed_before_dependency']=precision_source_seen if complete else None
        correction=checkpoint_verdict({'id':correction['checkpoint_id']+'-source-exposed-v1',
            'required_assertions':list(checks)},checks)
    result['memory']={'correction':correction,
        'three_evictions':grade_three_evictions(evictions,observation_complete=complete,
            require_identity=(contract.get('window_contract')or{}).get('kind')in {'native-identity-plain-text-v1','native-identity-plain-text-v2'}),
        'eviction_snapshots':evictions[:3],
        'parser_scope':'finite canonical entity/value literal predicates; not general free-text semantics',
        'literal_contract':literal,'dependent_write_observed':action_seen}
    result['memory']['semantic_invalidation_policy']='unarchived-conflicts-v2; display-window eviction alone does not retire a fact'
    if fact_rates:
        from .mab_semantic_rates import semantic_rates
        from .stage_execution import stage_execution
        rate_complete=complete and stage_execution(trial,events)['evidence_complete']is True
        prior=prior_record_seen if rate_complete and contract.get('old_fact_control')else None
        result['memory']['prior_active_record_seen']=prior
        result['memory']['prior_record_boundary_evidence']=prior_evidence
        result['memory']['current_validity_before_action']=correction
        result['memory']['current_validity_is_not_proof_of_an_update_operation']=True
        result['memory']['correction']=normalization_points(result,contract.get('case_id'))['S.case_v2.C5-correct-before-action']
        result['semantic_rates']=semantic_rates(contract['typed_fact_memory'],evictions,correction,
            post_source_changes,complete=rate_complete,prior_active_record=prior)
    elif book_rates:
        from .book_semantic_rates import book_semantic_rates
        from .stage_execution import stage_execution
        rate_complete=complete and stage_execution(trial,events)['evidence_complete']is True
        result['semantic_rates']=book_semantic_rates(contract['typed_book_memory'],evictions,
            result['typed_book_memory'],post_source_changes,complete=rate_complete,
            source_exposed=precision_source_seen if rate_complete else None)
    return result
