"""Conditional write-tool receipt opportunities, independently reconciled."""
from __future__ import annotations

import math

from .state_metrics import WRITE_TOOLS

VERSION='fixed35-state-write-receipts-20261104-v1'
METRICS={f'Q2.write.{tool}.success':tool for tool in WRITE_TOOLS}


def _empty(reason,status='unknown'):
    return {'value':None,'numerator':None,'denominator':None,'unknown':None,
        'status':status,'reason':reason,'complete':False,'receipt_version':VERSION}


def receipt_evidence(collection):
    if not isinstance(collection,dict):return {t:_empty('collection_object_missing')for t in WRITE_TOOLS}
    state=collection.get('state_metrics')or{}
    if not isinstance(state,dict):return {t:_empty('state_receipt_source_missing')for t in WRITE_TOOLS}
    boundary=collection.get('execution_boundary_collection');stages=collection.get('stage_execution')
    ready=state.get('session_counts_status')=='complete'and state.get('episode_return_scope_consistent')is True \
        and isinstance(boundary,dict)and boundary.get('complete')is True \
        and isinstance(stages,dict)and stages.get('evidence_complete')is True
    writes=state.get('writes');tools=collection.get('tools');result={}
    for tool in WRITE_TOOLS:
        if not ready or not isinstance(writes,dict)or not isinstance(tools,dict):
            result[tool]=_empty('complete_session_and_independent_execution_scope_required');continue
        session=writes.get(tool)
        if not isinstance(session,dict):result[tool]=_empty('native_session_tool_counts_missing');continue
        trace=tools.get(tool,{'attempts':0,'successes':0,'errors':0,'unknown_results':0})
        if not isinstance(trace,dict):result[tool]=_empty('independent_tool_counts_missing');continue
        first=[session.get(k)for k in ['attempts','successes','failures','unknown']]
        second=[trace.get(k)for k in ['attempts','successes','errors','unknown_results']]
        if any(v is None for v in [*first,*second]):result[tool]=_empty('receipt_count_field_missing');continue
        if any(type(v)is not int or v<0 for v in [*first,*second])or any(v[0]!=sum(v[1:])for v in [first,second]):
            result[tool]=_empty('invalid_or_inconsistent_receipt_counts','invalid');continue
        if first!=second:
            result[tool]=dict(_empty('native_session_and_independent_tool_counts_disagree'),
                observed_session_counts=first,observed_independent_counts=second);continue
        executions=trace.get('executions')
        if executions is not None and(type(executions)is not int or executions<0):
            result[tool]=_empty('invalid_independent_execution_count','invalid');continue
        if executions is not None and executions>first[0]:
            result[tool]=_empty('replayed_native_call_executions_require_individual_attempt_receipts');continue
        a,s,f,u=first;expected=s/a if a and not u else None;rate=session.get('success_rate')
        if rate is not None and(type(rate)not in (int,float)or not math.isfinite(rate)or expected is None or
                not math.isclose(rate,expected,rel_tol=1e-9,abs_tol=1e-12)):
            result[tool]=_empty('native_receipt_scalar_disagrees_with_counts','invalid');continue
        result[tool]={'value':expected,'numerator':s,'denominator':a-u,'unknown':u,
            'status':'not_applicable'if not a else'partial'if u else'scored',
            'reason':'Complete dual-source evidence proves zero attempts; no success claim'if not a else
                'Actual isError receipts, reconciled Session and execution logs; unknown results retained; no State commit or semantic inference',
            'complete':not u,'receipt_version':VERSION,'attempts':a,'successes':s,'failures':f,
            'raw_formula':'s/(s+f); opportunities a=s+f+u; coverage (s+f)/a; bounds [100s/a,100(s+u)/a]',
            'observed_session_counts':first,'observed_independent_counts':second}
    return result


def qualify_receipt(item,proof):
    if item['status']in {'DESIGN_NA','DESIGN_UNRESOLVED'}:return
    item['receipt_evidence']=proof
    item['raw_formula']='a=s+f+u; original s/a defined when u=0; observed s/(s+f); Session/execution count agreement required'
    item['score_formula']='100*s/(s+f); coverage=(s+f)/a; interval=[100*s/a,100*(s+u)/a]; zero a is mathematically undefined'
    if proof['status']in {'unknown','invalid'}:
        item.update(score=None,status=proof['status'],reason=proof['reason'],collection_status='REPAIR_REQUIRED')
    elif not proof['complete']:
        item.update(collection_status='REPAIR_REQUIRED',reason=proof['reason'])
    elif proof['status']=='not_applicable':
        item.update(reason=proof['reason'],statistical_denominator={'attempts':0,'successes':0,'failures':0,'unknown':0})
