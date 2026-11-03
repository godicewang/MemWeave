"""Selected Switch-SWE remembered-contract probes and closed-set route labels.

These are explicit extra business actions, not claims that an arbitrary source
edit proves cognitive recovery. Original source tasks and final verifiers remain
separate. No gold value is included in the public probe prompt.
"""
from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path

import toml

from .fixed35 import checkpoint_verdict
from .fixed35_switch import switch_contract
from .storage import atomic_json, file_digest
from .suites import task_digest

VERSION='fixed35-switch-remembered-contract-20261103-v2'
ROUTES={
 'INT-06':{'w01':'w01-base64-strict','w03':'w03-password-hasher-async','w00':'w00-auth-user-consistency',
    'w02':'w02-deferred-annotation-safety','w04':'w04-cache-async-dispatch'},
 'INT-07':{'w00':'w00-linkcheck-redirect-policy','w02':'w02-forwardref-signature','w03':'w03-image-mimetype-converter',
    'w04':'w04-data-uri-handler','w01':'w01-latex-table-description'}}
AUDIT_TAGS={
 'INT-06':{'w01':'k4q8-P7v2-m5Hs','w03':'b9T2-r6Nz-u3Cx','w00':'p6W3-a8Lc-d2R5',
    'w02':'t7M4-e9Qb-n5K1','w04':'f2J8-c6Vs-h4P9'},
 'INT-07':{'w00':'s8D3-v5Hm-q2Z7','w02':'j6A9-r1Px-c4F8','w03':'m3L7-u8Bk-e5N2',
    'w04':'w9C4-g2Ty-a6R1','w01':'n5H8-p3Vd-k7S6'}}
PROBES={
 'INT-06':[
    {'id':'old-strict-decoder','before_turn':5,'slot':'w01','source_turn':1,
     'support':'Add validate=True to base64.b64decode() calls',
     'description':'the earlier base64-decoding hardening work',
     'expected':{'checkout':'/work/w01','validate':True}},
    {'id':'canonical-binaryfield','before_turn':11,'slot':'w01','source_turn':5,
     'support':'Empty strings remain valid binary data.',
     'description':'the earlier BinaryField canonical-string contract',
     'expected':{'checkout':'/work/w01','canonical_rfc4648':True,'empty_string_valid':True,
        'error_code':'invalid','params_original_value':True,'message_from_field':True}}],
 'INT-07':[
    {'id':'redirect-warning-policy','before_turn':15,'slot':'w00','source_turn':1,
     'support':'--fail-on-warning',
     'description':'the earlier linkcheck redirect-warning work',
     'expected':{'checkout':'/work/w00','warnings_when_rules_empty':True,'ci_flag':'--fail-on-warning'}}]}
PROBES['INT-06'].insert(0,{'id':'ephemeral-return','before_turn':5,'slot':'w00','source_turn':4,
    'support':'request.user after alogin()/alogout()',
    'description':'the work you were doing immediately before the temporary question','search_requested':False,
    'expected':{'checkout':'/work/w00','async_user_consistent':True}})
PROBES['INT-07'].insert(0,{'id':'ephemeral-return','before_turn':15,'slot':'w03','source_turn':3,
    'support':'instead of absolute path.',
    'additional_support':[{'source_turn':12,'support':'webp->png conversion.'}],
    'description':'the work you were doing immediately before the temporary question','search_requested':False,
    'expected':{'checkout':'/work/w03','absolute_image_path':True,'webp_png':True}})
for _case,_probes in PROBES.items():
    for _probe in _probes:_probe['expected']['audit_tag']=AUDIT_TAGS[_case][_probe['slot']]


def route_marker(goal):
    if not isinstance(goal,str):return None
    found=re.findall(r'^ROUTE ([a-z0-9-]+)$',goal,re.MULTILINE)
    return found[0]if len(found)==1 else None


def grade_probe(text,probe):
    expected=probe['expected'];parsed=None;known=text is not None
    if known:
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('duplicate member')
                value[key]=item
            return value
        try:parsed=json.loads(text,object_pairs_hook=unique,parse_constant=lambda _:None)
        except (ValueError,TypeError):pass
    schema=isinstance(parsed,dict)and set(parsed)==set(expected)
    checks={'exact_probe_schema':schema if known else None}
    for key,value in expected.items():
        checks['source_constraint:'+key]=(schema and type(parsed[key])is type(value)and parsed[key]==value)if known else None
    return checkpoint_verdict({'id':VERSION+':'+probe['id'],'required_assertions':list(checks)},checks)


def public_probe(probe,filename):
    keys=', '.join(probe['expected'])
    search=('Use the persistent work-search tools if available, or your existing notes; list up to three real matching records. '
        if probe.get('search_requested',True)else
        'Continue the current work record; when already correctly bound, you need not repeat search or resume. ')
    return ('Derived memory/routing checkpoint, identical for both variants. Return to '+probe['description']+'. '
        +search+
        'Before continuing code changes, write '+filename+' as one JSON object with exactly these keys: '+keys+'. '
        'Recover their values from the earlier supplied requirements; this message supplies no values. '
        'For Boolean fields use JSON booleans. Resume the corresponding saved work if applicable. '
        'Write one compact, readable regular UTF-8 JSON file no larger than 4096 bytes, synchronously. '
        'This is a recall checkpoint; do not implement additional features in this step.')


def derive_switch_probes(source:Path,runtime_task:Path,case_id,output:Path):
    component=switch_contract(source,case_id)
    config=tomllib.loads((runtime_task/'task.toml').read_text());original_steps=config['steps']
    expected=[r['source_step']for r in component['route_ledger']]+['final']
    if [s['name']for s in original_steps]!=expected:raise ValueError('runtime source stage order differs')
    if any(p.is_symlink()for p in runtime_task.rglob('*')):raise ValueError('redirected source task')
    target=output/'tasks'/runtime_task.name;shutil.copytree(runtime_task,target)
    first_by_slot={}
    for route in component['route_ledger']:first_by_slot.setdefault(route['goal_slot'],route['source_step'])
    route_labels=[]
    for slot,step in first_by_slot.items():
        path=target/'steps'/step/'instruction.md';original=path.read_text()
        if file_digest(path)!=next(r['instruction_sha256']for r in component['route_ledger']if r['source_step']==step):
            raise ValueError('runtime original instruction differs from selected source')
        label=ROUTES[case_id][slot]
        path.write_text(original+'\n\nDerived persistent-record convention (same source information for both variants): '
            'when preserving this continuing objective in a Task Goal or ordinary work note, retain a separate line '
            '`ROUTE '+label+'`. Do not create a new persistent record for every follow-up or a temporary question. '
            'The identifier denotes this source objective, not a new requirement or a solution. '
            'Audit tag for this work record: '+AUDIT_TAGS[case_id][slot]+'. Retain it with this objective; '
            'use that exact tag if a later routing-verification artifact asks for the saved work tag.\n')
        route_labels.append({'slot':slot,'route_id':label,'first_source_step':step,
            'original_instruction_sha256':component['route_ledger'][int(step[-2:])-1]['instruction_sha256']})
    steps=[];probes=[];ephemeral=None;stage_map={}
    first_probe=min(p['before_turn']for p in PROBES[case_id])
    for original in original_steps:
        name=original['name'];turn=int(name[-2:])if name.startswith('turn-')else None
        if turn==first_probe:
            simple='ephemeral-conversion';folder=target/'steps'/simple;folder.mkdir()
            (folder/'instruction.md').write_text('Temporary question: what is 6 multiplied by 7? Reply with only the integer. We will then continue the earlier work.\n')
            steps.append({'name':simple,'agent':{'timeout_sec':90}});ephemeral=str(len(steps))
        for spec in PROBES[case_id]:
            if turn!=spec['before_turn']:continue
            support=runtime_task/'steps'/f"turn-{spec['source_turn']:02d}"/'instruction.md'
            if support.read_text().count(spec['support'])!=1:raise ValueError('source probe support missing or ambiguous')
            additional=[]
            for extra in spec.get('additional_support',[]):
                path=runtime_task/'steps'/f"turn-{extra['source_turn']:02d}"/'instruction.md'
                if path.read_text().count(extra['support'])!=1:raise ValueError('latest source update support missing or ambiguous')
                additional.append({'source_path':str(path),'source_sha256':file_digest(path)})
            step='probe-'+spec['id'];filename='memweave-'+case_id.lower()+'-'+spec['id']+'.json'
            folder=target/'steps'/step;folder.mkdir()
            (folder/'instruction.md').write_text(public_probe(spec,'/work/'+filename)+'\n')
            steps.append({'name':step,'agent':{'timeout_sec':180}})
            probes.append(dict(spec,stage_id=str(len(steps)),step=step,filename=filename,
                route_id=ROUTES[case_id][spec['slot']],source_path=str(support),source_sha256=file_digest(support),
                additional_source_paths=additional))
        steps.append(original);stage_map[name]=str(len(steps))
    config['steps']=steps;config.setdefault('metadata',{})['memory_overlay']=VERSION
    (target/'task.toml').write_text(toml.dumps(config))
    for label in route_labels:label['stage_id']=stage_map[label['first_source_step']]
    record={'version':VERSION,'case_id':case_id,'adapter_kind':'switch-remembered-contract-v2',
        'fixture_only':False,'source_component':component,'probes':probes,
        'ephemeral_stage_id':ephemeral,'ephemeral_step':'ephemeral-conversion',
        'original_stage_ids':stage_map,'route_labels':route_labels,
        'task_path':str(target),'task_sha256':task_digest(target),'source_task_sha256':task_digest(runtime_task),
        'task_config':{'workspace':{'root':'/work','files':[p['filename']for p in probes],
            'content_files':[p['filename']for p in probes],'worktrees':sorted(first_by_slot)}},
        'window_contract':{'kind':'native-identity-plain-text-v2','recent_turns':200,'evict_turns':40,
            'max_source_bytes':4000000,'scope':'Frozen Flash 1M/default 200/40; same-Session declared resume seed fidelity only'},
        'scope':'Explicit closed-set source identities and remembered-contract JSON actions, not a general natural-language Goal oracle. '
            'Original final business tests remain unchanged and separate; no ranking success is inferred without query-time corpus evidence.',
        'status':'SOURCE_BOUND_DERIVED_COMPONENT_NOT_FORMAL_ADMISSION',
        'not_formal_admission':True}
    private=output/'evaluator-only'/case_id/'contract.json';atomic_json(private,record,immutable=True)
    return record
