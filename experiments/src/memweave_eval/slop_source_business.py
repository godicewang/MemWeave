"""Pinned SCB-01/03 current-feature and retained-regression source cases."""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from .fixed35 import checkpoint_verdict
from .fixed35_slop import checkpoint_outcome
from .storage import atomic_json, file_digest

VERSION='fixed35-slop-source-business-20261104-v2'
CASES={'SCB-01':('circuit_eval',8),'SCB-03':('trajectory_api',5)}


def inventory(raw):
    groups=raw.get('tests')if isinstance(raw,dict)else None
    if not isinstance(groups,dict)or not groups:raise ValueError('source test identity groups missing')
    identities={};observed={};passes=Counter();totals=Counter()
    for group,states in groups.items():
        if not isinstance(group,str)or not isinstance(states,dict)or set(states)!={'passed','failed','skipped'}:
            raise ValueError('invalid source test group schema')
        if any(not isinstance(ids,list)or any(not isinstance(i,str)or not i for i in ids)for ids in states.values()):
            raise ValueError('source test identities must be lists of nonempty strings')
        all_ids=[i for ids in states.values()for i in ids]
        if len(all_ids)!=len(set(all_ids))or not all_ids:raise ValueError('duplicate or empty source test identity group')
        category=group.rsplit('-',1)[-1]
        if category not in {'Core','Functionality','Regression','Error'}:raise ValueError('unknown source test category')
        identities[group]=sorted(all_ids)
        # These two fixed source suites declare no conditional skip. A captured
        # mandatory test skipped is known noncompletion, not lost telemetry.
        observed[group]={i:state=='passed'for state,ids in states.items()for i in ids}
        passes[category]+=len(states['passed']);totals[category]+=len(all_ids)
    return identities,observed,passes,totals


def inventory_hash(groups):
    data=[{'group':g,'ids':ids}for g,ids in sorted(groups.items())]
    return hashlib.sha256(json.dumps(data,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def freeze_contract(case,sources:Path,controls:Path,output:Path,*,metric_matrix=None):
    identity=case['pack_case_id'];problem,count=CASES[identity]
    pin=subprocess.check_output(['git','-C',str(sources),'rev-parse','HEAD'],text=True).strip()
    if case['upstream_case_id']!=problem or pin!=case['source_revision']or subprocess.check_output(['git','-C',str(sources),'status','--porcelain'],text=True):
        raise ValueError('clean pinned selected Slop source required')
    manifest=json.loads(controls.read_text());records=manifest['records'];stages={};proofs={}
    source_manifest=Path(manifest['source_manifest'])
    if file_digest(source_manifest)!=manifest['source_manifest_sha256']:raise ValueError('source control manifest changed')
    for n in range(1,count+1):
        stage='checkpoint_'+str(n);rows=[r for r in records if r['problem']==problem and r['stage']==stage and r['control']=='reference']
        if len(rows)!=1 or rows[0].get('fixture_only')is not True or rows[0].get('formal_score')is not None:
            raise ValueError('exact isolated source reference inventory required')
        row=rows[0];p=Path(row['source'])
        if file_digest(p)!=row['source_sha256']:raise ValueError('source collection control changed')
        raw=json.loads(p.read_text());point=checkpoint_outcome(raw)
        if raw.get('problem_name')!=problem or raw.get('checkpoint_name')!=stage or point.get('original_all_reported_tests_score')!=100:
            raise ValueError('reference must pass original strict source tests')
        groups,_,passes,totals=inventory(raw)
        if any(passes[k]!=v for k,v in totals.items()):raise ValueError('reference inventory contains unpassed source cases')
        if not any(g.startswith(stage+'-')and not g.endswith('-Regression')for g in groups)or n>1 and not any(g.endswith('-Regression')for g in groups):
            raise ValueError('source new-feature or retained-regression opportunity missing')
        stages[stage]={'groups':groups,'reported_inventory_sha256':inventory_hash(groups),
            'test_collection_hash':raw['test_collection_hash'],'pytest_collected':raw['pytest_collected'],
            'schema_version':raw['schema_version']}
        proofs[str(p)]=file_digest(p)
    task=sources/problem;paths=[task/'config.yaml',*task.glob('checkpoint_*.md'),*(task/'tests').rglob('*')]
    if any(p.is_symlink()for p in paths):raise ValueError('redirected Slop source')
    result={'case_id':identity,'version':VERSION,'adapter_kind':'slop-source-business-v1','problem':problem,
        'source_revision':pin,'source_hashes':{str(p):file_digest(p)for p in paths if p.is_file()},
        'reference_inventory_proofs':proofs,'stages':stages,'metric_matrix':metric_matrix or[],
        'control_manifest_proof':{'path':str(controls),'sha256':file_digest(controls),
            'source_manifest':str(source_manifest),'source_manifest_sha256':manifest['source_manifest_sha256']},
        'not_formal_admission':True,'fixture_only':False,'gold_actor_visible':False,
        'scope':'Exact original '+problem+' current-feature and retained regression assertions; no State/Task/Window adoption inference'}
    atomic_json(output,result,immutable=True);return result


def mean_point(points,identity):
    complete=bool(points)and all(p['collection_complete']for p in points)
    known=[p for p in points if p['score']is not None]
    score=sum(p['score']for p in points)/len(points)if points and len(known)==len(points)else None
    return {'checkpoint_id':identity,'score':score,'status':'SCORED'if score is not None else'MISSING_EVIDENCE',
        'collection_complete':complete,'numerator':sum(p['score']/100 for p in points if p['score']is not None),
        'denominator':len(points),'unknown':len(points)-len(known),
        'missing_collection_opportunities':sum(not p['collection_complete']for p in points),
        'formula':'equal mean across source checkpoints; AND of every required test identity within each checkpoint'}


def grade_reports(reports,contract,*,fixture_control=False):
    for p,d in contract['source_hashes'].items():
        if file_digest(Path(p))!=d:raise ValueError('selected Slop source changed')
    points={};issues=[];untriggered=[];counts={}
    if not isinstance(reports,dict):reports={};issues.append('source stage reports missing')
    if set(reports)-set(contract['stages']):issues.append('unexpected source stage')
    for stage,expected in contract['stages'].items():
        raw=reports.get(stage);errors=[];observed={};groups={};passes=Counter();totals=Counter()
        original=checkpoint_outcome(raw)
        required={'requirements.txt','circopt.py'if contract['problem']=='circuit_eval'else'trajectory_api.py'}
        missing=original.get('missing_required_files')
        delivery_failure=bool(isinstance(raw,dict)and raw.get('problem_name')==contract['problem']and raw.get('checkpoint_name')==stage
            and original.get('reason')=='required submitted file absent'and isinstance(missing,list)and
            len(missing)==len(set(missing))and set(missing)<=required)
        if delivery_failure:
            counts[stage]={'reported_occurrences':0,'skipped_occurrences':0,'initial_collected':0,
                'unexecuted_reported_occurrences':sum(len(v)for v in expected['groups'].values()),
                'mandatory_submission_missing':missing,'reported_inventory_sha256':None,'source_initial_collection_hash':None}
            for kind in ['current','regression']:
                if kind=='regression'and stage=='checkpoint_1':untriggered.append(stage+':'+kind);continue
                points[stage+':'+kind]=checkpoint_verdict({'id':'F35.SOURCE.'+contract['case_id']+'.'+stage+'.'+kind,
                    'required_assertions':['mandatory_source_submission_delivered']},{'mandatory_source_submission_delivered':False})
            continue
        try:groups,observed,passes,totals=inventory(raw)
        except ValueError as error:errors.append(str(error))
        if groups!=expected['groups']:errors.append('complete reported inventory mismatch')
        if not isinstance(raw,dict):raw={}
        if raw.get('problem_name')!=contract['problem']or raw.get('checkpoint_name')!=stage:errors.append('source stage identity mismatch')
        for key in ['schema_version','test_collection_hash','pytest_collected']:
            if type(raw.get(key))is not type(expected[key])or raw.get(key)!=expected[key]:errors.append('source protocol mismatch:'+key)
        if checkpoint_outcome(raw)['status']!='SCORED':errors.append('original source outcome not completely observed')
        for key,counter in [('pass_counts',passes),('total_counts',totals)]:
            value=raw.get(key)
            # Zero category counts are legitimate source output, never missing evidence.
            if not isinstance(value,dict)or any(type(n)is not int for n in value.values())or {k:n for k,n in counter.items()if n}!={k:n for k,n in value.items()if n}:
                errors.append('source category counts mismatch:'+key)
        counts[stage]={'reported_occurrences':sum(len(v)for v in groups.values())if groups else None,
            'unexecuted_reported_occurrences':0 if groups==expected['groups']else None,
            'skipped_occurrences':sum(len(v['skipped'])for v in raw['tests'].values())if groups else None,
            'initial_collected':raw.get('pytest_collected'),'reported_inventory_sha256':inventory_hash(groups)if groups else None,
            'source_initial_collection_hash':raw.get('test_collection_hash')}
        for kind in ['current','regression']:
            selected=[g for g in expected['groups']if(g.endswith('-Regression')if kind=='regression'else g.startswith(stage+'-')and not g.endswith('-Regression'))]
            if not selected:
                if kind=='regression'and stage=='checkpoint_1':untriggered.append(stage+':'+kind);continue
                errors.append('expected source opportunity missing:'+kind)
            checks={g+'::'+i:observed.get(g,{}).get(i)for g in selected for i in expected['groups'][g]}
            checks['complete_frozen_source_inventory']=True if not errors else None
            points[stage+':'+kind]=checkpoint_verdict({'id':'F35.SOURCE.'+contract['case_id']+'.'+stage+'.'+kind,
                'required_assertions':list(checks)},checks)
        issues.extend(stage+':'+e for e in errors)
    current=[p for k,p in points.items()if k.endswith(':current')];regression=[p for k,p in points.items()if k.endswith(':regression')]
    return {'version':VERSION,'case_id':contract['case_id'],'fixture_only':fixture_control,'evidence_issues':issues,
        'checkpoints':points,'untriggered_points':untriggered,'stage_inventory':counts,
        'common_checkpoint':mean_point(regression,'F35.SOURCE.'+contract['case_id']+'.regression-retention'),
        'process_checkpoint':mean_point(current,'F35.SOURCE.'+contract['case_id']+'.current-feature-validation'),
        'collection_complete':not issues and all(p['collection_complete']for p in points.values()),'scope':contract['scope']}


def grade_official(outcome,contract,*,fixture_control=False):
    if not isinstance(outcome,dict):outcome={}
    if outcome.get('fixture_scores_included')is True and not fixture_control:
        raise ValueError('Slop source controls require explicit fixture-control')
    evidence=outcome.get('source_evidence',{});reports={}
    for stage in contract['stages']:
        item=evidence.get(stage,{})if isinstance(evidence,dict)else{}
        try:
            path=Path(item['report'])
            if file_digest(path)!=item['sha256']:raise ValueError('captured raw source report changed')
            raw=json.loads(path.read_text())
            if isinstance(raw,dict)and raw.get('submission_contract'):
                if not isinstance(raw['submission_contract'],dict):raise TypeError('invalid source delivery contract')
                manifest=Path(item['manifest_path']);digest=file_digest(manifest)
                if item.get('status')!='KNOWN_SUBMISSION_CONTRACT_FAILURE'or digest!=item['manifest_sha256']or \
                        raw['submission_contract'].get('handoff_manifest_sha256')!=digest:
                    raise ValueError('source delivery failure lacks bound handoff evidence')
                receipt=json.loads(manifest.read_text())
                if not isinstance(receipt,list)or not any(isinstance(r,dict)and r.get('source')=='/workspace'and
                    r.get('destination')=='artifacts/submission'and r.get('status')in {'ok','empty'}for r in receipt):
                    raise ValueError('source handoff is not complete')
            reports[stage]=raw
        except (OSError,ValueError,KeyError,TypeError):reports[stage]=None
    if isinstance(evidence,dict):
        for stage in set(evidence)-set(contract['stages']):reports[stage]=None
    return grade_reports(reports,contract,fixture_control=fixture_control)


def checkpoint_rows(result):
    return [{'id':p['checkpoint_id'],'meaning':result['scope']+'; '+name,'applicability':'all',
        'raw':p['score']/100 if p['score']is not None else None,'score':p['score'],'status':p['status'],
        'raw_formula':'AND of every frozen source group and parameter test identity at this checkpoint',
        'score_formula':'100 when all required source cases pass; known assertion failure0; missing evidence explicit',
        'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
        'weight_reason':'Source subpoints explain existing common metrics; no duplicate weighting',
        'support_s':sum(a['value']is True for a in p['assertions'].values()),'support_f':len(p['failed_assertions']),
        'support_u':len(p['missing_assertions']),'support_n':len(p['assertions']),
        'collection_complete':p['collection_complete']}for name,p in result['checkpoints'].items()]
