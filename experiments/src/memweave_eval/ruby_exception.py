"""Finite preregistered LONG-05 ban/exception, not general dependency semantics."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .evidence_replay import read_object
from .fixed35 import checkpoint_verdict
from .fixed35_business import case_events, execution_boundaries
from .slop_fk_gold import _state_at
from .storage import file_digest

VERSION='fixed35-ruby-literal-exception-20261104-v1'
EXCEPTION='libsqlite3-sys'
BAN=('magnus','rb-sys','rutie','helix','ruru','rubysys',EXCEPTION)


def lock_policy(artifact):
    checks={'complete_lock_delivery':None,'valid_lock_package_table':None,
        'no_forbidden_resolved_package':None,'allowed_sqlite_exception_selected':None}
    names=[]
    if isinstance(artifact,dict)and artifact.get('status')=='absent':
        checks={k:False for k in checks}
    elif isinstance(artifact,dict)and artifact.get('status')=='captured'and isinstance(artifact.get('text'),str):
        checks['complete_lock_delivery']=True
        try:
            packages=tomllib.loads(artifact['text']).get('package')
            valid=isinstance(packages,list)and bool(packages)and all(isinstance(p,dict)and
                isinstance(p.get('name'),str)and re.fullmatch('[A-Za-z0-9_-]+',p['name'])and
                isinstance(p.get('version'),str)and p['version']and
                ('source'not in p or isinstance(p['source'],str))for p in packages)
            if valid:
                keys=[(p['name'],p['version'],p.get('source'))for p in packages]
                valid=len(keys)==len(set(keys))
            checks['valid_lock_package_table']=bool(valid)
            names=[p['name']for p in packages]if valid else[]
        except tomllib.TOMLDecodeError:checks['valid_lock_package_table']=False
        valid=checks['valid_lock_package_table']
        checks['no_forbidden_resolved_package']=valid and not(set(names)&(set(BAN)-{EXCEPTION}))
        checks['allowed_sqlite_exception_selected']=valid and EXCEPTION in names
    point=checkpoint_verdict({'id':VERSION+':actual-lock-policy','required_assertions':list(checks)},checks)
    return dict(point,resolved_package_names=sorted(set(names)),dependency_scope='all delivered Cargo.lock packages, not platform/feature-active or runtime usage proof')


def _card(text):
    try:
        pairs=json.loads(text,object_pairs_hook=list)
        if not isinstance(pairs,list)or not all(isinstance(p,tuple)and len(p)==2 for p in pairs):return None
        relevant=any(k=='s'and v=='rj'for k,v in pairs)
        if not relevant:return None
        value=dict(pairs)
        if len(value)!=len(pairs)or value.get('s')!='rj'or not{'s'}<set(value)<= {'s','ban','except'}:
            return {'invalid':True}
        if 'ban'in value:
            names=value['ban']
            if not isinstance(names,list)or not all(isinstance(n,str)for n in names)or len(set(names))!=len(names)or set(names)!=set(BAN):
                return {'invalid':True}
        if 'except'in value and value['except']!=EXCEPTION:return {'invalid':True}
        return value
    except (ValueError,TypeError):return None


def exception_checkpoint(entries,dependency,*,before_dependency,boundaries_complete,opportunity):
    checks={'correct_visible_ban_set':None,'correct_visible_exception':None,'no_unarchived_conflicting_card':None,
        'recorded_before_dependency':before_dependency if type(before_dependency)is bool else None,
        'complete_execution_boundaries':True if boundaries_complete is True else None,
        'actual_lock_policy':dependency['score']==100 if dependency['score']is not None else None}
    if isinstance(entries,list)and all(isinstance(e,dict)and isinstance(e.get('text'),str)and
            type(e.get('archived'))is bool and type(e.get('visible'))is bool for e in entries):
        cards=[(_card(e['text']),e['visible'])for e in entries if not e['archived']]
        checks['correct_visible_ban_set']=any(c and not c.get('invalid')and'ban'in c and visible for c,visible in cards)
        checks['correct_visible_exception']=any(c and not c.get('invalid')and'except'in c and visible for c,visible in cards)
        checks['no_unarchived_conflicting_card']=not any(c and c.get('invalid')for c,_ in cards)
    point=checkpoint_verdict({'id':VERSION+':remember-and-apply-literal-exception','required_assertions':list(checks)},checks)
    if opportunity is False and boundaries_complete is True:
        point.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY',collection_complete=dependency['collection_complete'],
            reason='Complete boundaries prove no observable dependency/source change; never called perfect retention')
    elif opportunity is not True:point.update(score=None,status='MISSING_EVIDENCE',collection_complete=False,
        reason='Dependency boundary opportunity not observed reliably')
    return point


def exception_observations(trial):
    events,locations=case_events(trial)
    return events,locations,execution_boundaries(trial,events)


def grade_trial(trial,contract,*,arm):
    if contract.get('version')!=VERSION or contract.get('case_id')!='LONG-05'or \
            contract.get('ban')!=list(BAN)or contract.get('except')!=EXCEPTION:
        raise ValueError('matching frozen literal Ruby exception contract required')
    if file_digest(Path(contract['instruction_path']))!=contract['instruction_sha256']:
        raise ValueError('public exception protocol changed')
    events,locations,coverage=exception_observations(trial)
    frames=[(i,e)for i,e in enumerate(events)if e.get('event')=='workspace_checkpoint']
    starts=[(i,e)for i,e in frames if e.get('phase')=='agent_start']
    ends=[(i,e)for i,e in frames if e.get('phase')=='agent_end']
    def tree(event):return event.get('workspace',{}).get('tree_projections',{}).get('ruby-dependency',{})
    def valid(value):return value.get('complete')is True and isinstance(value.get('projection_sha256'),str)and \
        re.fullmatch('[a-f0-9]{64}',value['projection_sha256'])is not None
    complete=coverage.get('complete')is True and bool(starts)and bool(ends)and all(valid(tree(e))for _,e in frames)
    initial=tree(starts[0][1])if starts else{};mutation=None;cutoff=None
    if valid(initial):
        mutation=next(((i,e)for i,e in frames if valid(tree(e))and tree(e)['projection_sha256']!=initial['projection_sha256']),None)
        if mutation:
            _,frame=mutation
            call=next((i for i,e in enumerate(events)if e.get('event')=='tool_call'and
                e.get('producer_id')==frame.get('producer_id')and e.get('call_id')==frame.get('call_id')),None)
            if frame.get('phase')not in {'tool_end','tool_result'}or call is None:complete=False
            else:cutoff=call
    opportunity=True if mutation and cutoff is not None else False if complete and not mutation else None
    last=ends[-1]if ends else None;artifact=None
    if last:
        _,event=last;value=event.get('workspace',{}).get('artifacts',{}).get('rj-rust/Cargo.lock')
        if isinstance(value,dict)and value.get('status')=='absent':artifact={'status':'absent'}
        elif isinstance(value,dict)and value.get('status')=='captured'and isinstance(value.get('ref'),dict):
            ref=value['ref']
            if ref.get('sha256')!=value.get('sha256'):raise ValueError('lock artifact reference hash mismatch')
            raw=read_object(locations[(event['producer_id'],event['sequence'])],ref)
            try:text=raw.decode('utf8')
            except UnicodeError:text='\x00'  # Captured bytes cannot be a UTF-8 TOML lockfile: known format failure.
            artifact={'status':'captured','text':text}
    common=lock_policy(artifact)
    entries=_state_at(events,locations,cutoff)if cutoff is not None else None
    plugin=exception_checkpoint(entries,common,before_dependency=True if cutoff is not None else None,
        boundaries_complete=complete,opportunity=opportunity)
    if arm=='pi-native':plugin={'score':None,'status':'DESIGN_NA','collection_complete':True,
        'reason':'Native Pi has no symbolic State clause-preservation obligation'}
    if not complete:common['collection_complete']=False
    return {'version':VERSION,'case_id':'LONG-05','common':common,'plugin':plugin,
        'first_dependency_change_order':cutoff,'opportunity':opportunity,'boundary_coverage':coverage,
        'collection_complete':common['collection_complete']and plugin['collection_complete'],
        'fixture_only':contract.get('fixture_only')is True or any(Path(trial).rglob('cli-fake-upstream.jsonl')),
        'scope':'finite literal card + all delivered lock packages; no general free-text, active-feature or causal adoption claim'}


def checkpoint_rows(result):
    return [{'id':VERSION+':'+name,'score':point['score'],'status':point['status'],
        'raw':point['score']/100 if point['score']is not None else None,
        'meaning':('最终Cargo.lock集合满足禁用集减唯一SQLite例外，且包含该例外'if name=='common'else
            '首次可观察Rust／Cargo修改前保留完整禁用集合和例外，无未归档冲突，并满足最终锁包约束')+'; '+result['scope'],
        'raw_formula':'AND of every separately listed mandatory program assertion',
        'score_formula':'100 * binary checkpoint verdict','support':point,
        'weights':{'common_product':0,'plugin_memory':0},'mapping_version':VERSION,
        'collection_complete':point['collection_complete'],'applicability':'all'if name=='common'else'plugin'}
        for name,point in [('common',result['common']),('plugin',result['plugin'])]]
