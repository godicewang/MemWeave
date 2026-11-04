"""Package capability evidence is separate from per-case collection and scores."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .long_qualification import CASES, VERSION, _formal_attempt
from .storage import file_digest

GROUPS=tuple([f'Q{i}'for i in range(1,9)]+[f'S{i}'for i in range(1,5)]+
    [f'C{i}'for i in range(1,9)]+[f'T{i}'for i in range(1,5)])


def _groups(identity):
    if identity.startswith('Q4_8.'):
        return ('Q4','Q8')if identity in {'Q4_8.window_integrity','Q4_8.reference_integrity'}else('Q8',)
    code=identity.split('.')[1].split('-')[0]if identity.startswith('F35.')else identity.split('.')[0]
    if code.startswith('C8'):code='C8'
    return (code,)if code in GROUPS else()


def capability_coverage(rows):
    """A known failure supplies an observation; missing/zero-opportunity never does.

    Callers supply only hash-bound formal report rows. Multiple aliases and
    subassertions cannot inflate the number of distinct capability groups.
    """
    groups={key:{'observed_cases':[],'metric_ids':[]}for key in GROUPS}
    for row in rows:
        if row.get('arm')!='pi-memweave'or row.get('collection_complete')is not True \
                or row.get('status')not in {'SCORED','DIAGNOSTIC'}:continue
        value=row.get('score')if row.get('status')=='SCORED'else row.get('raw')
        if value is None:continue
        if row.get('status')=='SCORED'and (type(value)not in (int,float)or
                not math.isfinite(value)or not 0<=value<=100):
            raise ValueError('capability observation has an invalid score')
        identity=row.get('metric_id');case=row.get('case_id')
        if not isinstance(identity,str)or not isinstance(case,str)or not case:
            raise ValueError('capability observation requires case and metric identities')
        for group in _groups(identity):
            groups[group]['observed_cases'].append(case)
            groups[group]['metric_ids'].append(identity)
    for evidence in groups.values():
        for key in evidence:evidence[key]=sorted(set(evidence[key]))
    missing=[key for key,evidence in groups.items()if not evidence['observed_cases']]
    return {'version':'fixed35-capability-coverage-20261104-v1','groups':groups,
        'required_group_count':len(GROUPS),'observed_group_count':len(GROUPS)-len(missing),
        'unobserved_groups':missing,'complete':not missing,
        'interpretation':'Formal observed capability coverage, not passed behavior. Known scores of zero count as observed; fixtures, missing evidence and zero opportunities do not.'}


def long_qualification_proof(proof):
    """Recheck actual frozen attempts instead of trusting a hand-written count."""
    if proof is None:
        return {'status':'MISSING_EVIDENCE','qualified_cases':None,'required_cases':5,'complete':False}
    path=Path(proof['path'])
    if file_digest(path)!=proof.get('sha256'):raise ValueError('long qualification proof changed')
    table=json.loads(path.read_text());rows=table.get('cases')
    if table.get('version')!=VERSION or table.get('reference_variant')not in {'pi-native','pi-memweave'} \
            or not isinstance(rows,list)or len(rows)!=5 or {r.get('case_id')for r in rows}!=set(CASES):
        raise ValueError('fixed five-case long qualification profile required')
    if not all(isinstance(table.get(k),str)and table[k]for k in ('model','model_version')):
        raise ValueError('long qualification model identity required')
    count=0
    for row in rows:
        attempts=row.get('formal_attempts')
        if not isinstance(attempts,list):raise TypeError('explicit formal qualification attempts required')
        roots=[a.get('run_root')for a in attempts]
        if any(not isinstance(r,str)or not r for r in roots)or len(set(roots))!=len(roots):
            raise ValueError('qualified attempts require unique formal roots')
        verified=[]
        for prior in attempts:
            actual=_formal_attempt(Path(prior['run_root']),row['case_id'],
                table['reference_variant'],table['model'],table['model_version'])
            if actual!=prior:raise ValueError('qualified attempt evidence differs from formal originals')
            verified.append(actual['qualified'])
        qualified=any(verified)
        if type(row.get('qualified'))is not bool or row['qualified']!=qualified:
            raise ValueError('qualified flag is not supported by real formal attempts')
        count+=qualified
    if 'qualified_distinct_cases'in table and table['qualified_distinct_cases']!=count:
        raise ValueError('qualified distinct case count differs')
    return {'status':'VERIFIED','qualified_cases':count,'required_cases':5,'complete':count==5,
        'path':str(path),'sha256':file_digest(path)}
