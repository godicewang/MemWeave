"""Recover final query text from existing originals; absent logs are not answers."""
from __future__ import annotations

import json
import math

from .stage_execution import stage_execution
from .storage import file_digest


def answer_text(path,*,require_terminal=False):
    try:
        if path.is_symlink():return None
        rows=[json.loads(line)for line in path.read_text().splitlines()]
        if not rows or any(not isinstance(r,dict)for r in rows):return None
        if require_terminal and not any(r.get('type')=='agent_end'for r in rows):return None
        answer='';seen=False
        for row in rows:
            message=row.get('message')or{}
            if row.get('type')!='message_end'or not isinstance(message,dict)or message.get('role')!='assistant':continue
            content=message.get('content')
            if not isinstance(content,list)or any(not isinstance(p,dict)for p in content):return None
            text='\n'.join(p['text']for p in content if p.get('type')=='text'and isinstance(p.get('text'),str))
            if text:answer=text
            seen=True
        return answer if seen or any(r.get('type')=='agent_end'for r in rows)else None
    except (OSError,ValueError,UnicodeError):return None


def query_answer(trial,agent,contract,*,events=None):
    primary=answer_text(agent/'pi.txt');proof={'source':'missing_final_query_evidence','complete':False}
    manifests={};invalid=False
    for path in agent.rglob('execution-invocations/*.json'):
        try:
            if path.is_symlink()or not path.resolve().is_relative_to(agent.resolve()):raise ValueError('redirected native evidence')
            value=json.loads(path.read_text())
            if value.get('stage_id')!=str(contract.get('query_stage_id')):continue
            identity=value['invocation_id'];name=value['stdout_file'];target=path.parent/name
            if path.stem!=identity or name!=identity+'.stdout.jsonl'or target.is_symlink()or not target.resolve().is_relative_to(agent.resolve()):
                raise ValueError('native invocation identity differs')
            if value.get('schema_version')!=1 or value.get('capture_status')!='CAPTURED'or value.get('status')!='RETURNED' \
                    or type(value.get('return_code'))is not int or value['return_code']!=0 \
                    or target.stat().st_size!=value['stdout_bytes']or file_digest(target)!=value['stdout_sha256']:
                raise ValueError('native stdout is incomplete or changed')
            text=answer_text(target,require_terminal=True)
            if text is None:raise ValueError('native answer or terminal missing')
            order=value.get('started_monotonic_ns')
            if order is not None:
                if not isinstance(order,str)or not order.isdigit():raise ValueError('invalid native monotonic order')
                order=('monotonic',int(order))
            else:
                order=value.get('started_at')
                if type(order)not in (int,float)or not math.isfinite(order):raise ValueError('native invocation order unavailable')
                order=('wall',order)
            item=(order,text,value['stdout_sha256'])
            if identity in manifests and manifests[identity]!=item:raise ValueError('conflicting native stdout copies')
            manifests[identity]=item
        except (ValueError,KeyError,OSError,TypeError):invalid=True
    if manifests and not invalid:
        items=list(manifests.values());orders=[v[0]for v in items]
        if len({o[0]for o in orders})==1 and len(set(orders))==len(orders):
            _,text,digest=max(items,key=lambda v:v[0])
            if primary is not None and primary!=text:return None,dict(proof,reason='derived and original query output disagree')
            return text,{'source':'independent_native_invocation','complete':True,'stdout_sha256':digest,
                'ordering':orders[0][0],'derived_pi_log_available':primary is not None}
        invalid=True
    if primary is not None and not invalid and not manifests:
        return primary,{'source':'original_pi_log','complete':True,'sha256':file_digest(agent/'pi.txt')}
    if not agent.exists():
        if events is None:
            from .fixed35_business import case_events
            events,_=case_events(trial)
        protocol=stage_execution(trial,events)
        query=[s for s in protocol.get('stages',[])if s['source_step_name']=='query']
        if len(query)==1 and query[0]['status']in {'NOT_STARTED_AFTER_ABORT','FAILED_BEFORE_PI'}:
            return '',{'source':'known_source_stage_abort','complete':True,'query_stage':query[0]}
    return None,dict(proof,reason='missing, malformed, conflicting or incomplete original query output')
