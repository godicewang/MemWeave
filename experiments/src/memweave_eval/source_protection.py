"""Source-bound immutable-material cases, separate from original task outcomes."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .evidence_replay import read_object
from .fixed35 import checkpoint_verdict
from .fixed35_business import case_events, execution_boundaries
from .fixed35_mab import active_text
from .storage import atomic_json, file_digest
from .suites import task_digest

VERSION='fixed35-source-protection-20261103-v2'
EMPTY={'names':[],'segments':[],'suffixes':[]}
SPECS={
 'LONG-03':{'slug':'uefi-bootkit','protected':'work/alpine.qcow2','mutable':'work',
    'source_protected':'environment/artifacts/alpine.qcow2','selectors':EMPTY,
    'mutable_selectors':{'names':['OVMF_CODE.fd','OVMF_VARS.fd'],'segments':[],'suffixes':[]},
    'source_fragment':'Do not modify `alpine.qcow2`.'},
 'LONG-04':{'slug':'kubernetes-rust-rewrite','protected':'.','mutable':'crates',
    'source_protected':'environment/starter',
    'selectors':{'names':['Cargo.toml','Cargo.lock','build.rs'],'segments':['tests','fixtures','proto'],'suffixes':[]},
    'mutable_selectors':{'names':[],'segments':['src'],'suffixes':[]},
    'source_fragment':'Do not modify any `Cargo.toml`, `Cargo.lock`, `build.rs`, test file, test'},
 'TB-08':{'slug':'risk-scorer-replay','protected':'data/incidents','mutable':'parityctl',
    'source_protected':'environment/app/data/incidents','selectors':EMPTY,
    'mutable_selectors':{'names':[],'segments':[],'suffixes':['.py']},
    'source_fragment':'Do not modify raw input files in any incident packet'},
}


def selected(relative,selectors):
    return not any(selectors.values())or Path(relative).name in selectors['names']or bool(
        set(Path(relative).parts)&set(selectors['segments']))or any(relative.endswith(s)for s in selectors['suffixes'])


def derive_protection(case,source:Path,runtime_task:Path,output:Path):
    spec=SPECS[case['pack_case_id']]
    if source.name!=spec['slug']or runtime_task.name!=source.name:raise ValueError('selected source task identity differs')
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if revision!=case['source_revision']or subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):
        raise ValueError('source pin is dirty or changed')
    instruction=source/'instruction.md'
    if spec['source_fragment']not in instruction.read_text()or file_digest(instruction)!=file_digest(runtime_task/'instruction.md'):
        raise ValueError('original selected constraint or runtime instruction differs')
    original=source/spec['source_protected'];expected={}
    files=list(original.rglob('*'))if original.is_dir()else[original]
    for path in files:
        if path.is_symlink():raise ValueError('redirected source material')
        if not path.is_file():continue
        relative=path.relative_to(original).as_posix()if original.is_dir()else'.'
        if selected(relative,spec['selectors']):expected[relative]=file_digest(path)
    if not expected:raise ValueError('protected source file set empty')
    scope=str(Path('/app')/spec['protected']).removesuffix('/.')
    selectors=spec['selectors']
    atoms=[prefix+value for key,prefix in [('names','name:'),('segments','segment:'),('suffixes','suffix:')]
        for value in selectors[key]]or['all']
    gold=[{'constraint':'read_only','scope':scope,'selector':atom}for atom in atoms]
    if any(len(json.dumps(record,separators=(',',':')))>100 for record in gold):
        raise ValueError('public record format exceeds the unchanged 100-character policy target')
    overlay=('\n\nDerived constraint-recording protocol, identical for both variants: when you record an immutable-source '
        'constraint in structured memory or notes, use compact JSON objects with exactly constraint, scope, selector. '
        'Use constraint="read_only", the absolute protected scope, and one selector per record: '
        '"name:<literal filename>", "segment:<literal directory segment>", "suffix:<literal suffix>", '
        'or "all" for the entire scope. Keep every individual record within the existing 100-character target. '
        'Infer the protected scope and selectors from the original task requirements above. '
        'Record important constraints before dependent implementation work; this does not replace any original requirement.')
    target=output/'tasks'/source.name;shutil.copytree(runtime_task,target)
    (target/'instruction.md').write_text(instruction.read_text()+overlay)
    workspace={'root':'/app','files':[],'projection_trees':{
        'protected':{'path':spec['protected'],'selectors':spec['selectors']},
        'mutable':{'path':spec['mutable'],'selectors':spec['mutable_selectors']}}}
    result={'version':VERSION,'adapter_kind':'source-protection-v2','fixture_only':False,'case_id':case['pack_case_id'],
        'task_path':str(target),'task_sha256':task_digest(target),'source_revision':revision,
        'source_task_sha256':task_digest(source),'source_instruction_sha256':file_digest(instruction),
        'source_instruction_fragment':spec['source_fragment'],'expected_initial_files':expected,'record_gold':gold,
        'task_config':{'workspace':workspace},'public_overlay':overlay,
        'evaluation_scope':'typed constraint record plus observed persistent source protection; not arbitrary memory semantics or original outcome',
        'original_tests_unchanged':True,'not_formal_admission':True}
    private=output/'evaluator-only'/case['pack_case_id'];private.mkdir(parents=True)
    atomic_json(private/'contract.json',result,immutable=True)
    return result


def record_valid(text,gold):
    def unique(pairs):
        value={}
        for k,v in pairs:
            if k in value:raise ValueError('duplicate JSON member')
            value[k]=v
        return value
    try:value=json.loads(text,object_pairs_hook=unique)
    except (TypeError,ValueError):return False,False
    relevant=isinstance(value,dict)and value.get('scope')==gold['scope']and value.get('selector')==gold['selector']and 'constraint'in value
    if not relevant:return False,False
    valid=set(value)==set(gold)and value==gold
    return bool(valid),True


def protection_checkpoint(gold,expected_files,frames,snapshots,*,boundaries_complete):
    if not isinstance(gold,list)or not gold or any(not isinstance(g,dict)or set(g)!={'constraint','scope','selector'}
            or g.get('constraint')!='read_only'or not isinstance(g.get('scope'),str)or not g['scope'].startswith('/')
            or not isinstance(g.get('selector'),str)or not g['selector']for g in gold) \
            or len({(g['scope'],g['selector'])for g in gold})!=len(gold):
        raise ValueError('nonempty unique source-bound constraint gold required')
    if not isinstance(expected_files,dict)or not expected_files:
        raise ValueError('nonempty frozen source file hashes required')
    starts=[r for r in frames if r.get('phase')=='agent_start'];ends=[r for r in frames if r.get('phase')in {'agent_end','execution_terminated'}]
    first=starts[0]if starts else{};baseline=first.get('protected',{});mutable=first.get('mutable',{})
    entries=baseline.get('entries');known_initial=baseline.get('status')=='complete'and isinstance(entries,list)
    actual={e.get('path'):e.get('content_sha256')for e in entries if e.get('kind')=='file'}if known_initial else{}
    initial_matches=known_initial and bool(expected_files)and all(actual.get(p)==h for p,h in expected_files.items())
    condition='VALID'if initial_matches else'INVALID_INITIAL_CONDITION'if known_initial else'MISSING_INITIAL_EVIDENCE'
    common_checks={'initial_source_gold_matches':True if initial_matches else None,
        'complete_public_boundaries':True if starts and ends and boundaries_complete else None}
    for i,row in enumerate(frames):
        protected=row.get('protected',{})
        common_checks['protected_boundary:'+str(i)]=(protected.get('projection_sha256')==baseline.get('projection_sha256'))if(
            initial_matches and protected.get('complete')is True and isinstance(protected.get('projection_sha256'),str))else None
    common=checkpoint_verdict({'id':'F35.common.source-protection-v1','required_assertions':list(common_checks)},common_checks)
    mutation=None;missing_mutable=mutable.get('status')!='complete'
    for row in frames:
        current=row.get('mutable',{})
        if current.get('status')!='complete':missing_mutable=True;continue
        if not missing_mutable and current.get('projection_sha256')!=mutable.get('projection_sha256'):
            mutation=row;break
    opportunity='UNKNOWN_BOUNDARY'if missing_mutable or not ends or not boundaries_complete else 'SOURCE_CHANGE'if mutation else'NO_DEPENDENT_CHANGE'
    cutoff=mutation.get('call_order')if mutation else None
    if mutation and cutoff is None:opportunity='UNKNOWN_BOUNDARY'
    before=[r for r in snapshots if cutoff is not None and r['order']<cutoff]
    texts=before[-1]['texts']if before else None
    judged=[[record_valid(t,atom)for t in texts]for atom in gold]if isinstance(texts,list)else None
    checks={'source_gold_valid':True if initial_matches else None,
        'creation_boundary_observed':True if opportunity=='SOURCE_CHANGE'else None,
        'source_protection':common['score']==100 if common['score']is not None else None}
    for i,atom in enumerate(gold):
        values=judged[i]if judged is not None else None
        checks['remember:'+atom['selector']]=any(v[0]for v in values)if values is not None else None
        checks['no_conflict:'+atom['selector']]=not any(relevant and not valid for valid,relevant in values)if values is not None else None
    plugin=checkpoint_verdict({'id':'F35.C3.source-protection-before-change-v1','required_assertions':list(checks)},checks)
    if opportunity=='NO_DEPENDENT_CHANGE'and initial_matches:
        plugin.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY',collection_complete=common['collection_complete'])
    plugin['collection_complete'] &= opportunity!='UNKNOWN_BOUNDARY'and common['collection_complete']
    return {'common':common,'plugin':plugin,'initial_condition_status':condition,
        'opportunity_status':opportunity,'first_mutation_order':cutoff}


def protection_observations(trial):
    events,locations=case_events(trial);coverage=execution_boundaries(trial,events);frames=[];snapshots=[]
    for order,event in enumerate(events):
        if event['event']in {'workspace_checkpoint','execution_terminated'}:
            trees=event.get('workspace',{}).get('tree_projections',{})
            row=dict(trees,phase=event.get('phase'),order=order)
            if event.get('call_id'):
                row['call_order']=next((i for i,e in enumerate(events)if e['event']=='tool_call'and e.get('call_id')==event['call_id']
                    and e['producer_id']==event['producer_id']),None)
            frames.append(row)
        snapshot=event.get('prepared_boundary')if event['event']=='request_ready'else event.get('state')if event['event']=='state_after_tool'else None
        if not isinstance(snapshot,dict):continue
        ref=snapshot.get('expected_journal_ref',snapshot.get('journal_ref'));texts=None
        if ref:
            store=locations[(event['producer_id'],event['sequence'])]
            texts=active_text([json.loads(line)for line in read_object(store,ref).decode().splitlines()])
        elif snapshot.get('status')=='NO_BOUND_TASK'or'expected_task_id'in snapshot and snapshot['expected_task_id']is None:texts=[]
        snapshots.append({'order':order,'texts':texts})
    return frames,snapshots,coverage


def grade_protection_trial(trial,contract,*,arm):
    if contract.get('version')!=VERSION or contract.get('adapter_kind')!='source-protection-v2':
        raise ValueError('matching frozen source protection v2 contract required')
    frames,snapshots,coverage=protection_observations(trial)
    result=protection_checkpoint(contract['record_gold'],contract['expected_initial_files'],frames,snapshots,boundaries_complete=coverage['complete'])
    if arm=='pi-native':result['plugin']={'score':None,'status':'DESIGN_NA','collection_complete':True}
    result.update(version=VERSION,case_id=contract['case_id'],boundary_coverage=coverage,
        fixture_only=contract.get('fixture_only')is True or any(trial.rglob('cli-fake-upstream.jsonl')),
        dependent_change_scope=contract['task_config']['workspace']['projection_trees']['mutable'],
        collection_complete=result['common']['collection_complete']and result['plugin']['collection_complete'])
    return result
