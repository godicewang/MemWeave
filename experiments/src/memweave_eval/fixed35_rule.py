"""Independent frozen Rule gold vs actual final provider requests, not adoption."""
from __future__ import annotations

import hashlib
import re

from .contract_metrics import _item, summarize
from .evidence_replay import read_object
from .fixed35_business import case_events

OPEN='<pi_long_task_rule>'
CLOSE='</pi_long_task_rule>'


def rendered_rule(template,variables):
    if not isinstance(template,str)or not template.strip()or OPEN in template or CLOSE in template:
        raise ValueError('nonempty unwrapped frozen Rule template required')
    keys=set(re.findall(r'\{\{\s*([a-z][a-z0-9_]*)\s*\}\}',template))
    if not isinstance(variables,dict)or set(variables)!=keys or any(
            type(v)is not int or v<1 for v in variables.values()):
        raise ValueError('every frozen Rule variable needs an independent positive integer value')
    body=re.sub(r'\{\{\s*([a-z][a-z0-9_]*)\s*\}\}',lambda m:str(variables[m[1]]),template)
    if '{{'in body or '}}'in body:raise ValueError('unsupported frozen Rule placeholder')
    return body


def rule_checkpoint(payload,template,variables,*,observed_template):
    expected=rendered_rule(template,variables)
    messages=payload.get('messages')if isinstance(payload,dict)else None
    if not isinstance(messages,list)or not all(isinstance(m,dict)for m in messages):
        return {'source_template_matches':None,'one_complete_rule':None,'exact_rendered_body':None,
            'system_before_history':None,'no_unresolved_placeholders':None}
    def text(m):
        value=m.get('content')
        return value if isinstance(value,str)else'\n'.join(p['text']for p in value
            if isinstance(p,dict)and p.get('type')=='text'and isinstance(p.get('text'),str))if isinstance(value,list)else''
    systems=[(i,text(m))for i,m in enumerate(messages)if m.get('role')=='system']
    all_text='\n'.join(s for _,s in systems)
    count_open=all_text.count(OPEN);count_close=all_text.count(CLOSE)
    matches=[(i,re.findall(re.escape(OPEN)+r'\n([\s\S]*?)\n'+re.escape(CLOSE),s))for i,s in systems]
    bodies=[(i,body)for i,group in matches for body in group]
    history=[i for i,m in enumerate(messages)if m.get('role')!='system']
    return {'source_template_matches':observed_template==template if isinstance(observed_template,str)else None,
        'one_complete_rule':count_open==count_close==len(bodies)==1,
        'exact_rendered_body':len(bodies)==1 and bodies[0][1]==expected,
        'system_before_history':len(bodies)==1 and (not history or bodies[0][0]<min(history)),
        'no_unresolved_placeholders':len(bodies)==1 and '{{'not in bodies[0][1]and '}}'not in bodies[0][1]}


def grade_rule_trial(trial,template,variables,request_ids,*,enabled):
    if not enabled:return summarize([_item('native',na=True,reason='native has no MemWeave Rule')])
    # Validate evaluator gold even with an empty episode; never silently accept it.
    rendered_rule(template,variables)
    events,locations=case_events(trial)
    ready={e['request_id']:e for e in events if e['event']=='request_ready'and e.get('request_id')in request_ids}
    items=[]
    for identity in sorted(request_ids):
        event=ready.get(identity)
        if not event or not event.get('payload_ref'):
            items.append(_item(identity,reason='final request payload missing'));continue
        store=locations[(event['producer_id'],event['sequence'])]
        import json
        payload=json.loads(read_object(store,event['payload_ref']))
        source=(event.get('prepared_boundary')or{}).get('expected_rule_template_ref')
        observed=read_object(store,source).decode()if source else None
        checks=rule_checkpoint(payload,template,variables,observed_template=observed)
        value=False if False in checks.values()else True if all(v is True for v in checks.values())else None
        items.append(dict(_item(identity,value,None if value else'frozen_rule_or_rendering_contract_not_met'),assertions=checks))
    return dict(summarize(items),template_sha256=hashlib.sha256(template.encode()).hexdigest(),
        scope='every actual actor request; frozen source/template values/unique complete system Rule; delivery only, not model adoption')
