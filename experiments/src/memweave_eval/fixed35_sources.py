"""Pinned source resolution. Hidden gold never enters an actor task directory."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path

from .fixed35 import VERSION, validate_selection
from .storage import atomic_json, file_digest
from .suites import task_digest

DESIGN_SHA256 = '1782a457cf58a9c9facb76b633d1f668c0bf5a36dcd461ced0a19792256e70b8'
FAMILIES = {'Terminal-Bench 4.0': 'tb4', 'SlopCodeBench': 'slop',
            'STATE-Bench 0.8.1': 'state', 'Switch-SWE current main': 'switch',
            'InterruptBench current main': 'interrupt', 'MemoryAgentBench': 'mab',
            'SWE-Marathon': 'marathon'}
PROTOCOL_OPPORTUNITIES={'tool_execution','cost_resource','density','rule_template','projection_window','native_outcome'}


def author_write_receipt_opportunities(rows):
    from .state_write_receipts import METRICS, VERSION
    result=deepcopy(rows)
    for row in result:
        tool=METRICS.get(row['metric_id'])
        if tool and row['design_status']in {'PLANNED','DESIGN_UNRESOLVED'}:
            row.update(design_status='PLANNED',opportunity_ids=sorted({
                *row.get('opportunity_ids',[]),'actual-plugin-write-receipts:'+tool}),
                reason='Each actual declared plugin write-tool call; complete dual-source proof required for zero denominator; native remains structurally NA',
                assignment_basis='authored_conditional_write_receipt_opportunity',opportunity_version=VERSION)
    return result


def read_design(path: Path):
    if file_digest(path) != DESIGN_SHA256:
        raise ValueError('approved design content changed')
    design = json.loads(path.read_text())
    validate_selection(design['selection'])
    return design


def mab_selector(case):
    match = re.fullmatch(r'(Conflict_Resolution|Accurate_Retrieval)/row=(\d+)/context_sha256=([a-f0-9]{64})/qa_pair_id=(.+)', case['upstream_case_id'])
    if not match or match[3] != case['context_sha256'] or match[4] != case['short_qa_id']:
        raise ValueError('ambiguous or mismatched MAB compound selector')
    return {'split': match[1], 'row': int(match[2]), 'context_sha256': match[3], 'qa_id': match[4],
            'data_revision': case['data_revision']}


def resolve_case(case, sources: Path):
    family = FAMILIES[case['benchmark']]
    source = sources/family
    actual = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    dirty = subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True)
    if actual != case['source_revision'] or dirty:
        raise ValueError('upstream checkout is dirty or not pinned')
    identity = case['upstream_case_id']
    if family in {'tb4','marathon'}:
        task = source/'tasks'/identity.rsplit('/',1)[-1]
    elif family == 'switch':
        task = source/'tasks'/('near/sf101' if identity == 'sf101_switched' else 'far/sf001')
    elif family == 'slop':
        task = source/identity
    else:
        task = None
    result = {k: case[k] for k in ('pack_case_id','benchmark','upstream_case_id','source_revision','title_cn')}
    result.update(family=family, source=str(source), source_status='PIN_VERIFIED',
                  adapter_status='NOT_PREFLIGHTED', execution_status='NOT_RUN')
    if task:
        if not task.is_dir():
            raise ValueError('selected task missing from pinned source')
        result.update(task_path=str(task), task_sha256=task_digest(task))
    if family == 'mab':
        result['selector'] = mab_selector(case)
    return result


def load_mab_row(case, data: Path):
    """Return public history/question separately from evaluator-only answers."""
    from pyarrow import parquet
    selector = mab_selector(case)
    path = data/(selector['split']+'-00000-of-00001.parquet')
    row = parquet.read_table(path).slice(selector['row'],1).to_pylist()[0]
    digest = hashlib.sha256(row['context'].encode()).hexdigest()
    if digest != selector['context_sha256']:
        raise ValueError('selected MAB history differs from frozen bytes')
    ids = row['metadata']['qa_pair_ids']
    indices = [i for i,value in enumerate(ids) if value == selector['qa_id']]
    if len(indices) != 1 or len(row['questions']) != len(ids) or len(row['answers']) != len(ids):
        raise ValueError('MAB QA alignment is ambiguous')
    i = indices[0]
    public = {'context': row['context'], 'question': row['questions'][i], 'selector': selector}
    private = {'answers': row['answers'][i], 'qa_index': i, 'selector': selector,
               'parquet_sha256': file_digest(path)}
    return public, private


def prepare_source_manifest(design_path, sources, output):
    design = read_design(design_path)
    cases = [resolve_case(case,sources) for case in design['selection']['cases']]
    result = {'schema_version': 1, 'evaluator_version': VERSION,
              'design_sha256': DESIGN_SHA256, 'cases': cases,
              'source_case_count': len(cases), 'long_qualified': 0}
    atomic_json(output, result, immutable=True)
    return result


def applicability_matrix(design):
    """Research suggestions are positive assignments, never an exhaustive NA list.

    Only the design's explicit legacy-task disposition establishes structural NA.
    Original outcomes are retained for every selected source case. Unassigned
    capabilities require an authored case contract before collection acceptance.
    """
    cases=design['selection']['cases']
    opportunities={o['id']:o for o in design['coverage_plan']['opportunities']}
    rows=[]
    for metric in design['coverage_plan']['metrics']:
        for case in cases:
            aliases={case['pack_case_id'],case['upstream_case_id']}
            if case['benchmark']=='MemoryAgentBench':
                aliases.add('MemoryAgentBench/'+case['upstream_case_id'])
            ids=[i for i in metric['opportunity_ids']
                 if aliases.intersection(opportunities[i]['proposed_case_ids'])]
            legacy_na=metric.get('disposition')=='legacy_task_specific_NA'
            protocol=[i for i in metric['opportunity_ids']if i in PROTOCOL_OPPORTUNITIES]
            ids=sorted(set(ids+protocol))
            status='DESIGN_NA'if legacy_na else'PLANNED'if ids else'DESIGN_UNRESOLVED'
            reason=('Explicit legacy task-specific metric; a separately named selected-case successor is required'
                if legacy_na else None if ids else
                'Research proposed_case_ids has no assignment; this is not evidence of structural inapplicability. '
                'Author and freeze the case opportunity or an independently justified structural NA before admission.')
            rows.append({'case_id':case['pack_case_id'],'metric_id':metric['metric_id'],
                         'benchmark':case['benchmark'],'opportunity_ids':ids,
                         'design_status':status,'reason':reason,
                         'applicability_version':'fixed35-research-assignments-20261102-v2',
                         'measurement_role':'legacy_task_specific'if legacy_na else
                            'raw_diagnostic'if metric.get('score_mapping_preserved')=='diagnostic'else'capability_score',
                         'assignment_basis':'explicit_legacy_disposition'if legacy_na else
                            'protocol_wide_telemetry'if protocol else'research_positive_assignment'if ids else'not_authored',
                         'conditional_na':'An explicitly observed zero denominator/operation opportunity may be mathematical NA; '
                            'missing instrumentation or an unimplemented checker is not zero or design NA',
                         'implementation_status':'NOT_ACCEPTED',
                         'design_sha256':DESIGN_SHA256})
    return author_write_receipt_opportunities(rows)


def freeze_draft_contracts(source_manifest,matrix,output:Path):
    """Make a reproducible unrun package view without pretending drafts are admitted."""
    contracts=output/'draft-contracts';contracts.mkdir(exist_ok=False)
    cases=[]
    for source in source_manifest['cases']:
        identity=source['pack_case_id'];path=contracts/(identity+'.json')
        rows=[r for r in matrix if r['case_id']==identity]
        if not rows or len({r['metric_id']for r in rows})!=len(rows):
            raise ValueError('draft case metric matrix is absent or duplicated')
        contract={'version':'fixed35-source-draft-20261102-v2','contract_status':'DRAFT_NOT_ADMITTED',
            'case_id':identity,'source_revision':source['source_revision'],
            'source_task_sha256':source.get('task_sha256'),'metric_matrix':rows,
            'warning':'Source assignments are not an executable opportunity ledger or collection preflight. '
                'Do not run this contract or replace missing actual results with fixtures.'}
        atomic_json(path,contract,immutable=True)
        cases.append({'case_id':identity,'benchmark':source['benchmark'],
            'contract_path':str(path.resolve()),'contract_sha256':file_digest(path)})
    manifest=output/'pack-draft.json'
    atomic_json(manifest,{'version':'fixed35-source-draft-20261102-v2','cases':cases,
        'design_sha256':source_manifest['design_sha256'],'admission_status':'NOT_ADMITTED'},immutable=True)
    return manifest
