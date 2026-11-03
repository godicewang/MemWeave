"""Pinned Interrupt final-value and shared-prefix components, never admission."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .fixed35 import checkpoint_verdict
from .storage import atomic_json, file_digest

VERSION='fixed35-interrupt-source-20261103-v1'
REVISION='17da111e4858b93c0cab1d88f85e1735fbd1d423'
CASES={
    'INT-08':{'kind':'1update','task_id':110,'selectors':['#order_status']},
    'INT-09':{'kind':'2modification','task_id':129,'selectors':[
        '.box.box-address-shipping > .box-content','.box.box-address-billing > .box-content']},
    'INT-10':{'kind':'1retraction','task_id':65,'selectors':[]},
}


def contract_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def contract_from_source(case,scenario,config,original,source_hashes,*,fixture_only):
    if type(fixture_only)is not bool:raise TypeError('explicit fixture designation required')
    identity=case['pack_case_id'];spec=CASES[identity]
    if case['source_revision']!=REVISION or case['upstream_case_id']!=f"{spec['kind']}:task_id={spec['task_id']}:60pct":
        raise ValueError('Interrupt selector/revision differs from approved source')
    if any(type(c.get('task_id'))is not int or c['task_id']!=spec['task_id']for c in [scenario,config,original]):
        raise ValueError('Interrupt source task identity mismatch')
    if not isinstance(scenario.get('updates'),list)or not scenario['updates']or any(not isinstance(s,str)or not s.strip()for s in scenario['updates']):
        raise ValueError('complete source intent updates required')
    if config['intent']!=scenario['transformed_initial_intent']or config['true_intent']!=scenario['intent']or original['intent']!=scenario['intent']:
        raise ValueError('source initial/true intent mismatch')
    evaluation=config['eval']
    if evaluation!=original['eval']or evaluation.get('eval_types')!=(['program_html']if spec['selectors']else['url_match']):
        raise ValueError('source final evaluator changed')
    if not source_hashes or any(not re.fullmatch('[a-f0-9]{64}',str(v))for v in source_hashes.values()):
        raise ValueError('all source hashes required')
    targets=evaluation.get('program_html')
    if not isinstance(targets,list)or len(targets)!=len(spec['selectors']):raise ValueError('source target count changed')
    queries=[]
    for i,(target,selector)in enumerate(zip(targets,spec['selectors'],strict=True)):
        expression='document.querySelector('+json.dumps(selector)+').outerText'
        if target.get('locator')!=expression or not isinstance(target.get('url'),str):
            raise ValueError('only pinned source DOM locators are supported')
        required=target['required_contents']
        if set(required)not in [{'exact_match'},{'must_include'}]:raise ValueError('unsupported source contents rule')
        values=[required['exact_match']]if'exact_match'in required else required['must_include']
        if not isinstance(values,list)or not values or any(not isinstance(v,str)or not v for v in values):
            raise ValueError('nonempty source target text required')
        queries.append({'id':f'target-{i}','url':target['url'],'locator':expression,
            'rule':'exact_match'if'exact_match'in required else'must_include','required':values,'forbidden':[]})
    if identity=='INT-09':
        street=re.fullmatch(r'The street is (.+), not (.+)\.',scenario['updates'][0])
        zipcode=re.fullmatch(r'And the zip code is (\d+), not (\d+)\.',scenario['updates'][1])if len(scenario['updates'])==2 else None
        if not street or not zipcode:raise ValueError('pinned two-field correction changed')
        for q in queries:
            if street[1]not in q['required']or not any(zipcode[1]in v for v in q['required']):
                raise ValueError('new source address differs from evaluator')
            q['forbidden']=[street[2]]+[v.replace(zipcode[1],zipcode[2])for v in q['required']if zipcode[1]in v]
    return {'version':VERSION,'case_id':identity,'source_revision':REVISION,'task_id':spec['task_id'],
        'source_selector':case['upstream_case_id'],'source_hashes':dict(source_hashes),
        'initial_intent':scenario['transformed_initial_intent'],'true_intent':scenario['intent'],
        'updates':list(scenario['updates']),'native_evaluation':json.loads(json.dumps(evaluation)),
        'queries':queries,'fixture_only':fixture_only,'contract_status':'SOURCE_COMPONENT_NOT_ADMITTED',
        'adapter_kind':'interrupt-final-source-v1','interruption_policy':{'numerator':3,'denominator':5,
            'formula':'floor(3*N/5) from the same frozen baseline for both arms','baseline_frozen':False},
        'pending':['official website images and isolated logged-in browser environment',
            'actual common baseline replay and opportunity-at-cut verification',
            'actual update delivery / first dependent browser action / State correction ordering']+
            (['calibrated active-rating-filter observation; source GOLD in PRED URL cannot prove retraction']if identity=='INT-10'else[])}


def freeze_contract(case,source:Path,output:Path,*,metric_matrix=None):
    actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True)
    if actual!=REVISION or dirty:raise ValueError('Interrupt checkout is dirty or not pinned')
    spec=CASES[case['pack_case_id']];base=source/'Eval'
    paths={'raw':base/'interrupt_config/raw'/(spec['kind']+'.json'),
        'config':base/'config_files/wa'/('test_webarena_lite_transformed_'+spec['kind'])/(str(spec['task_id'])+'.json'),
        'original':base/'config_files/wa/test_webarena_lite'/(str(spec['task_id'])+'.json'),
        'evaluator':base/'evaluation_harness/evaluators.py','replay_resolver':base/'run.py',
        'action_types':base/'browser_env/actions.py'}
    raw=json.loads(paths['raw'].read_text());matches=[r for r in raw if r.get('task_id')==spec['task_id']]
    if len(matches)!=1:raise ValueError('source scenario is not unique')
    contract=contract_from_source(case,matches[0],json.loads(paths['config'].read_text()),
        json.loads(paths['original'].read_text()),{k:file_digest(p)for k,p in paths.items()},fixture_only=False)
    contract['source_paths']={k:str(p)for k,p in paths.items()}
    if metric_matrix is not None:contract['metric_matrix']=metric_matrix
    atomic_json(output,contract,immutable=True);return contract


def _clean(value):return' '.join(value.split()).casefold()


def _url(value):
    value=value.replace('localhost','127.0.0.1')
    return value.removesuffix('/')


def capture_final(context,actor_page,contract,output:Path,*,fixture_control=False):
    if not fixture_control and not type(context).__module__.startswith('playwright.sync_api.'):
        raise TypeError('real synchronous Playwright context required outside fixture controls')
    if contract.get('fixture_only')is not False and not fixture_control:raise ValueError('fixture gold is not a real browser contract')
    if actor_page.context is not context:raise ValueError('actor page is outside the supplied isolated context')
    capture_errors=(RuntimeError,TypeError,OSError)
    if not fixture_control:
        from playwright.sync_api import Error
        capture_errors=(*capture_errors,Error)
    before=actor_page.url;records=[];page=None;close_error=None
    try:
        if contract['queries']:page=context.new_page()
        for query in contract['queries']:
            record={'id':query['id'],'url':query['url'],'locator':query['locator']}
            try:
                page.goto(query['url']);value=page.evaluate('() => '+query['locator'])
                if not isinstance(value,str):raise TypeError('source DOM query did not return text')
                record.update(status='captured',value=value,navigation_url=page.url)
            except capture_errors as error:
                record.update(status='capture_error',error_class=type(error).__name__)
            records.append(record)
    finally:
        if page is not None:
            try:page.close()
            except capture_errors as error:close_error=type(error).__name__
    result={'version':VERSION,'case_id':contract['case_id'],'contract_sha256':contract_hash(contract),
        'producer':'interrupt-final-source-observer-v1','actor_url':before,'actor_url_after_capture':actor_page.url,
        'actor_page_untouched':before==actor_page.url,'queries':records,'fixture_only':bool(fixture_control),
        'evaluation_page_close_error':close_error}
    atomic_json(output,result,immutable=True);return result


def grade_capture(contract,capture):
    if capture is not None and not isinstance(capture,dict):raise TypeError('capture must be an object or missing')
    if capture is not None and capture.get('contract_sha256')!=contract_hash(contract):raise ValueError('capture contract hash mismatch')
    capture=capture or{};known=capture.get('version')==VERSION and capture.get('case_id')==contract['case_id'] \
        and capture.get('producer')=='interrupt-final-source-observer-v1'and capture.get('actor_page_untouched')is True \
        and isinstance(capture.get('actor_url'),str)and capture.get('actor_url_after_capture')==capture['actor_url'] \
        and 'evaluation_page_close_error'in capture and capture['evaluation_page_close_error']is None \
        and type(capture.get('fixture_only'))is bool
    rows=capture.get('queries');rows=rows if isinstance(rows,list)else[]
    ids=[r.get('id')for r in rows if isinstance(r,dict)]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate final source query observation')
    checks={};endpoint=None
    for query in contract['queries']:
        record=next((r for r in rows if isinstance(r,dict)and r.get('id')==query['id']),{})
        valid=known and record.get('status')=='captured'and record.get('url')==query['url'] \
            and record.get('locator')==query['locator']and isinstance(record.get('value'),str) \
            and isinstance(record.get('navigation_url'),str)and _url(record['navigation_url'])==_url(query['url'])
        checks[query['id']+'.source_identity']=True if valid else None
        for i,value in enumerate(query['required']):
            checks[query['id']+'.required-'+str(i)]=( _clean(record['value'])==_clean(value)
                if query['rule']=='exact_match'else _clean(value)in _clean(record['value']))if valid else None
        for i,value in enumerate(query['forbidden']):
            checks[query['id']+'.old-value-absent-'+str(i)]=_clean(value)not in _clean(record['value'])if valid else None
    if contract['case_id']=='INT-10':
        url=capture.get('actor_url');valid=known and isinstance(url,str)and bool(url)
        native={'actor_url_observed':True if valid else None,'pinned_source_url_match':
            _url(contract['native_evaluation']['reference_url'])in _url(url)if valid else None}
        endpoint=checkpoint_verdict({'id':'F35.interrupt.native-url','required_assertions':list(native)},native)
        checks=dict(native,rating_filter_retracted=None)
    point=checkpoint_verdict({'id':'F35.interrupt.final-source-constraints','required_assertions':list(checks)},checks)
    return {'version':VERSION,'case_id':contract['case_id'],'goal_checkpoint':point,'native_endpoint_checkpoint':endpoint,
        'fixture_only':capture.get('fixture_only'),'collection_complete':point['collection_complete'],
        'rating_retraction_status':'BLOCKED_FILTER_OBSERVATION_NOT_IMPLEMENTED'if contract['case_id']=='INT-10'else'not_part_of_case',
        'temporal_correction_status':'NOT_VERIFIED_REQUIRES_ACTUAL_UPDATE_AND_BROWSER_ACTION_TRACE',
        'scope':'Final source-selected values only; not timely State correction, transient-action safety, adoption, or whole-case admission'}


def freeze_baseline(contract,replay:Path,output:Path,*,fixture_control=False):
    value=json.loads(replay.read_text());actions=value.get('actions')
    if type(value.get('version'))is not int or value['version']!=1 or type(value.get('task_id'))is not int or value['task_id']!=contract['task_id']:
        raise ValueError('baseline version/task identity mismatch')
    if not isinstance(actions,list)or not actions or type(value.get('num_actions'))is not int or value['num_actions']!=len(actions):
        raise ValueError('complete baseline actions/count required')
    if 'interrupt'not in value or value['interrupt']is not None or value.get('intent')not in {contract['initial_intent'],contract['true_intent']}:
        raise ValueError('baseline must be uninterrupted and use the selected source intent')
    if any(not isinstance(a,dict)or type(a.get('action_type'))is not int or not 0<=a['action_type']<=18 for a in actions):
        raise ValueError('unsupported baseline action shape/type')
    count=len(actions);cut=3*count//5
    if any(a['action_type']==17 for a in actions[:cut]):raise ValueError('baseline STOP before the fixed interrupt boundary')
    result={'version':VERSION,'case_id':contract['case_id'],'contract_sha256':contract_hash(contract),
        'baseline_path':str(replay),'baseline_sha256':file_digest(replay),'total_actions':count,'interrupt_at_action':cut,
        'prefix_sha256':contract_hash(actions[:cut]),'baseline_intent':value['intent'],
        'behavior_opportunity_verified':False,'fixture_only':contract['fixture_only']or bool(fixture_control),
        'reason':'Mechanical prefix only; website state and a remaining meaningful dependent action still require real environment evidence'}
    atomic_json(output,result,immutable=True);return result


def baseline_prefix(contract,frozen,*,fixture_control=False):
    if(frozen.get('fixture_only')is not False or contract.get('fixture_only')is not False)and not fixture_control:
        raise ValueError('fixture baseline cannot enter real replay')
    if frozen.get('contract_sha256')!=contract_hash(contract)or frozen.get('case_id')!=contract['case_id']:
        raise ValueError('baseline contract mismatch')
    path=Path(frozen['baseline_path'])
    if file_digest(path)!=frozen['baseline_sha256']:raise ValueError('baseline original changed')
    value=json.loads(path.read_text());actions=value['actions'];cut=frozen['interrupt_at_action']
    if type(cut)is not int or cut!=3*len(actions)//5 or len(actions)!=frozen['total_actions']or contract_hash(actions[:cut])!=frozen['prefix_sha256']:
        raise ValueError('baseline prefix differs from frozen common boundary')
    return actions[:cut]


def checkpoint_rows(behavior):
    points=[behavior['goal_checkpoint']]
    if behavior['native_endpoint_checkpoint']is not None:points.append(behavior['native_endpoint_checkpoint'])
    result=[]
    for point in points:
        score=point['score'];assertions=point['assertions'];known=sum(a['status']!='missing'for a in assertions.values())
        result.append({'id':point['checkpoint_id'],'meaning':'Source-selected final DOM values or URL predicate; excludes intermediate correction/adoption and requires a separate rating-filter observation for INT-10',
            'applicability':'all','raw':None if score is None else score/100,'raw_formula':'AND of every named source-bound assertion',
            'score':score,'score_formula':'100 * binary checkpoint outcome','unit':'binary checkpoint','status':point['status'],
            'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
            'weight_reason':'Supplementary source breakdown; any shared primary constraint is counted only once',
            'support_s':int(score==100),'support_f':int(score==0),'support_u':int(score is None),'support_n':1,
            'evidence_coverage':known/len(assertions),'collection_complete':point['collection_complete'],'assertions':assertions})
    return result
