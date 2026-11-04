"""Explicit per-case design masks. Omission and absent evidence are never NA."""
from __future__ import annotations

import json
from pathlib import Path

from .normalized_scores import catalogue
from .storage import file_digest

VERSION='fixed35-authored-applicability-20261104-v3'
ABSENCE_BASES={'no_designed_event','tool_not_exposed','original_metric_not_reported','legacy_case_mismatch'}


def _proof(proof):
    if not isinstance(proof,dict)or set(proof)!={'path','sha256'}:
        raise ValueError('explicit file/hash proof required')
    path=Path(proof['path'])
    if path.is_symlink()or not path.is_file()or file_digest(path)!=proof['sha256']:
        raise ValueError('frozen protocol or gold source changed')


def _strings(value):
    return isinstance(value,list)and bool(value)and all(isinstance(v,str)and v.strip()for v in value)and len(set(value))==len(value)


def compile_scope(path):
    """Compile all explicit decisions; never guess absence from a research list."""
    scope=json.loads(Path(path).read_text());registry={m['id']:m for m in catalogue()['metrics']}
    if scope.get('version')!=VERSION or not isinstance(scope.get('case_id'),str)or not scope['case_id']:
        raise ValueError('explicit case-scope identity/version required')
    protocol=scope.get('protocol_inputs')
    if not isinstance(protocol,list)or not protocol:raise ValueError('frozen actual actor protocol inputs required')
    for proof in protocol:_proof(proof)
    decisions=scope.get('decisions')
    if not isinstance(decisions,list)or any(not isinstance(d,dict)for d in decisions):
        raise ValueError('complete explicit case metric decisions required')
    if len(decisions)!=len(registry)or {d.get('metric_id')for d in decisions}!=set(registry):
        raise ValueError('case scope must decide the complete registry exactly once')
    rows=[];digest=file_digest(Path(path))
    for decision in decisions:
        identity=decision['metric_id'];status=decision.get('design_status');reason=decision.get('reason')
        trigger=decision.get('designed_trigger');ids=decision.get('opportunity_ids')
        if status=='PLANNED':
            if trigger is not True or not _strings(ids)or not _strings(decision.get('evidence_fields')):
                raise ValueError('designed opportunity needs explicit trigger, IDs and evidence schema')
            _proof(decision.get('gold'))
        elif status=='DESIGN_NA':
            if trigger is not False or decision.get('absence_basis')not in ABSENCE_BASES or ids!=[] \
                    or not isinstance(reason,str)or not reason.strip():
                raise ValueError('NA requires reviewed absence, frozen reason and no designed trigger')
        elif status=='DESIGN_UNRESOLVED':
            if not isinstance(reason,str)or not reason.strip():raise ValueError('unresolved case design requires reason')
        else:raise ValueError('unknown case scope decision')
        rows.append({'case_id':scope['case_id'],'benchmark':scope.get('benchmark'),'metric_id':identity,
            'design_status':status,'opportunity_ids':ids or[],'reason':reason,
            'applicability_version':VERSION,'scope_sha256':digest,
            'assignment_basis':'explicit_authored_case_protocol',
            'measurement_role':'raw_diagnostic'if registry[identity]['mapping']=='diagnostic'else'capability_score',
            'conditional_na':'Only complete evidence of zero eligible opportunities may establish mathematical NA; missing capture never does.'})
    return rows


def validate_scope_contract(contract):
    proof=contract.get('applicability_scope');_proof(proof)
    rows=compile_scope(Path(proof['path']))
    if rows!=contract['metric_matrix']or any(r['case_id']!=contract.get('case_id')for r in rows):
        raise ValueError('case matrix differs from its frozen authored decisions')
