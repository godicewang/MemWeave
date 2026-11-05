"""Finite, explicitly prompted TB01 propositions. Not a free-text semantic judge."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

PROTOCOL='tb01-capsule.v1'
NOTE='/app/evalbench/memory_capsules.jsonl'
FILES=['evalbench/'+n+'.py'for n in ('__init__','byte_stops','evaluate','generation','io_utils','metrics','model','packing','prefix_cache','reference','rendering','scheduler','schema','scoring','spans','tokenizer','trace')]
GOLD={
 'row':{'k':'row','by':'non_support_position','support':False,'ids':'repeat','s':'TB01'},
 'pmi':{'k':'pmi','pop':'full_shard','group':'label+effective','norm':'after_sub','s':'TB01'},
 'stop':{'k':'stop','domain':'raw_bytes','prompt':False,'extract':'after','min':True,'s':'TB01'},
}
DEPENDENCIES={'row':['evalbench/evaluate.py','evalbench/scheduler.py'],
 'pmi':['evalbench/evaluate.py','evalbench/scoring.py'],'stop':['evalbench/generation.py','evalbench/byte_stops.py']}
PUBLIC_PROTOCOL='''

Derived evaluation protocol TB01-capsule.v1 (same for both arms; original business task above remains required):
Before changing implementation files, identify and persist three concise constraint capsules from the original requirements. These are bounded, machine-readable notes, not a replacement for implementing the task. Do not guess the correct values from field names.
Use one compact JSON object per capsule, with exactly the indicated keys. s must be "TB01". Choose values from these vocabularies based on the original task:
row: {k:"row",by: one of "id"/"non_support_position"/"prefix_id",support: boolean meaning support rows produce output,ids: "repeat"/"unique" meaning duplicate output IDs permitted versus required unique,s:"TB01"}.
pmi: {k:"pmi",pop:"batch"/"full_shard"/"row",group:"label"/"label+effective"/"none",norm:"after_sub"/"before_sub" meaning normalization relative to raw-score subtraction,s:"TB01"}. pop is the population of the conditional calibration mean; group is its grouping key. effective means the calibration_group/group/default fallback defined above.
stop: {k:"stop",domain:"normalized"/"prompt"/"raw_bytes",prompt:boolean meaning prompt participates in stop matching,extract:"after"/"before" meaning extraction relative to stopping,min:boolean meaning honor min_new_tokens before stop matching,s:"TB01"}.
If dedicated State tools are available, create/bind the task as required by your normal rules and save each capsule as a Fact or Decision whose content is solely the compact JSON (under 100 characters); provide real evidence references. Use State tools to correct obsolete capsules; a Goal is not a saved capsule. Do not edit memory files directly.
Otherwise save the three JSON objects as lines in /app/evalbench/memory_capsules.jsonl using normal file tools; keep only current capsules in that note. Other notes are allowed.
Before first editing evaluate.py/scheduler.py (row), evaluate.py/scoring.py (pmi), or generation.py/byte_stops.py (stop), explicitly consult the saved current capsules: state_read if State is available, otherwise the read tool on the note file. Consult them again after your final source changes and before your final response. Merely saying you checked does not substitute for a read. Do not read evaluator/controller assets or hidden tests. Continue solving the complete original task with your normal tools and defaults.
'''


def truth(entries,key):
    if entries is None:return {'schema':'missing','values':'missing','no_conflict':'missing'}
    relevant=[r for r in entries if isinstance(r,dict)and not r.get('archived',False)and isinstance(r.get('value'),dict)and r['value'].get('k')==key]
    def schema(value):return set(value)==set(GOLD[key])and all(type(value[k])is type(v)for k,v in GOLD[key].items())
    correct=[r for r in relevant if schema(r['value'])and r['value']==GOLD[key]]
    return {'schema':'pass'if any(schema(r['value'])for r in relevant)else'fail','values':'pass'if correct else'fail',
            'no_conflict':'pass'if correct and all(schema(r['value'])and r['value']==GOLD[key]for r in relevant)else'fail'}


def _read_jsonl(path,*,pi=False):
    if not path.is_file():return None
    try:
        values=[json.loads(s)for s in path.read_text().splitlines()if s.strip()and(not pi or s.lstrip().startswith(('{','[')))]
        return values if all(isinstance(v,dict)for v in values)else None
    except (OSError,ValueError):return None


def _journals(archive):
    if not archive.is_file():return {}
    result={}
    with tarfile.open(archive)as source:
        for m in source:
            if m.isfile()and m.name.endswith('/state.json'):
                task=Path(m.name).parent.name
                if task in result:raise ValueError('duplicate task journal')
                result[task]=source.extractfile(m).read().splitlines(keepends=True)
    return result


def _replay_prefixes(journals,versions):
    """Use the actual product reducer, including archive/window/ID validation."""
    inputs=[];keys=[]
    for task,v in sorted(versions):
        lines=journals.get(task)
        if lines is None or type(v)is not int or not 0<v<=len(lines):continue
        inputs.append([json.loads(line)for line in lines[:v]]);keys.append((task,v))
    model=(Path(__file__).resolve().parents[3]/'src/state/model.ts').as_uri()
    code='import fs from "node:fs";const {reduceState}=await import('+json.dumps(model)+');const values=JSON.parse(fs.readFileSync(0,"utf8"));console.log(JSON.stringify(values.map(v=>Array.from(reduceState(v).entries.values()))));'
    r=subprocess.run(['node','--input-type=module','-e',code],input=json.dumps(inputs),capture_output=True,text=True,timeout=30,check=True)
    return dict(zip(keys,json.loads(r.stdout),strict=True))


def _recover_json_reads(agent,trace,read_ids):
    """Repair legacy null summaries only with original Session + exact wire hash.

    Pi 1.4 serializes text blocks joined by newline; the product inserts a
    reference head block which already ends in newline. No actor data is edited.
    """
    results={};refs={};sources={}
    for path in sorted((agent/'pi/sessions').glob('*.jsonl')):
        events=_read_jsonl(path)
        if events is None:continue
        sources[str(path.relative_to(agent.parent))]=hashlib.sha256(path.read_bytes()).hexdigest()
        for entry in events:
            m=entry.get('message',{})
            if isinstance(m,dict)and isinstance(m.get('toolCallId'),str)and m.get('role')=='toolResult'and m.get('toolName')=='state_read':
                results.setdefault(m.get('toolCallId'),[]).append((entry.get('id'),m))
            if entry.get('type')=='custom'and entry.get('customType')=='memweave.references.v1':
                data=entry.get('data',{})
                if not isinstance(data,dict)or not isinstance(data.get('bindings'),list):continue
                for binding in data['bindings']:
                    if isinstance(binding,dict)and all(isinstance(binding.get(k),str)for k in ('entry_id','ref'))and isinstance(data.get('task_id'),str):
                        refs.setdefault(binding['entry_id'],set()).add((binding['ref'],data['task_id']))
    missing=set();valid=set();proofs={}
    for request in trace:
        if request.get('event')!='request_ready':continue
        deliveries=request.get('capsule_deliveries')
        for delivery in deliveries if isinstance(deliveries,list)else[]:
            if not isinstance(delivery,dict):continue
            identity=delivery.get('tool_call_id')
            if identity not in read_ids:continue
            if delivery.get('task_id')is not None and delivery.get('state_version')is not None:
                valid.add(identity);continue  # Never replace an explicit wrong version.
            missing.add(identity);rows=results.get(identity,[])
            if len(rows)!=1:continue
            entry_id,message=rows[0]
            if message.get('isError')is not False:continue
            try:
                body='\n'.join(c['text']for c in message['content']if c['type']=='text')
                payload=json.loads(body);task=payload['task_id'];version=payload['state_version']
                if not isinstance(task,str)or not task or type(version)is not int or version<=0:continue
                values=[json.loads(item['content'])for item in payload['items']]
                values=[v for v in values if isinstance(v,dict)and v.get('k')in GOLD]
                if values!=delivery.get('values'):continue
            except (ValueError,KeyError,TypeError):continue
            heads=['']
            bindings=refs.get(entry_id,set())
            if len(bindings)==1:
                ref,source_task=next(iter(bindings))
                if isinstance(ref,str)and isinstance(source_task,str):
                    heads+=['['+ref+']\n\n','['+source_task+':'+ref+']\n\n']
            hashes={m.get('sha256')for m in request.get('messages',[])
                    if m.get('role')=='tool'and m.get('tool_call_id')==identity}
            for head in heads:
                wire={'role':'tool','content':head+body,'tool_call_id':identity}
                digest=hashlib.sha256(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                if hashes!={digest}:continue
                prepared=request.get('prepared_messages')
                if prepared is not None and {m.get('sha256')for m in prepared if m.get('role')=='tool'and m.get('tool_call_id')==identity}!={digest}:continue
                delivery.update(task_id=task,state_version=version)
                valid.add(identity);proofs[(identity,digest)]={'tool_call_id':identity,'message_sha256':digest,
                    'session_entry_id':entry_id,'task_id':task,'state_version':version}
                break
    return list(proofs.values()),sources if proofs else{},sorted(missing-valid)


def collect_capsules(trial,variant,*,expected_reducer_sha256=None):
    trial=Path(trial);agent=trial/'agent';trace=_read_jsonl(agent/'request-trace.jsonl');pi=_read_jsonl(agent/'pi.txt',pi=True)
    if trace is None or pi is None:return {'complete':False,'reason':'raw_trace_or_pi_json_missing','assertions':{}}
    boundaries=[(i,e)for i,e in enumerate(trace)if e.get('event')=='workspace_checkpoint']
    starts=[(i,e)for i,e in boundaries if e.get('phase')=='agent_start'];ends=[(i,e)for i,e in boundaries if e.get('phase')=='agent_end']
    tool_starts={};tool_ends={};invalid=[]
    for i,e in boundaries:
        if e.get('phase')in ('tool_start','tool_end'):
            target=tool_starts if e['phase']=='tool_start'else tool_ends
            identity=e.get('call_id')
            if not isinstance(identity,str)or identity in target:invalid.append('duplicate_or_missing_call_id')
            target[identity]=(i,e)
    expected=[e.get('toolCallId')for e in pi if e.get('type')=='tool_execution_start']
    if len(starts)!=1 or len(ends)!=1 or set(expected)!=set(tool_starts)or set(tool_starts)!=set(tool_ends):invalid.append('start_end_or_tool_boundary_missing')
    for identity,(i,_)in tool_starts.items():
        if identity not in tool_ends or tool_ends[identity][0]<=i:invalid.append('tool_order')
    recoveries=[];recovery_sources={}
    if variant=='pi-memweave':
        read_ids={identity for identity,(_,e)in tool_starts.items()if e.get('tool_name')=='state_read'}
        recoveries,recovery_sources,missing_reads=_recover_json_reads(agent,trace,read_ids)
        if missing_reads:invalid.append('capsule_read_metadata_unrecoverable')
    if not starts or not ends:return {'complete':False,'reason':'agent_boundary_missing','assertions':{}}
    def workspace(e):return e.get('workspace')if isinstance(e.get('workspace'),dict)else{}
    initial=workspace(starts[0][1]).get('files',{})
    if not isinstance(initial,dict):initial={}
    if set(initial)!=set(FILES)or any(not isinstance(initial.get(f),str)for f in FILES):invalid.append('initial_python_hashes_missing')
    for e in trace:
        if e.get('event')=='request_ready'and (not isinstance(e.get('capsule_deliveries'),list)or
                any(not isinstance(d,dict)for d in e['capsule_deliveries'])):
            invalid.append('capsule_request_projection_missing');e['capsule_deliveries']=[]
    versions=set()
    for _,e in boundaries:
        b=e.get('state_boundary',{})
        if not isinstance(b,dict):invalid.append('state_boundary_error');continue
        if 'expected_task_id'not in b or b.get('boundary_error'):invalid.append('state_boundary_error')
        if b.get('expected_task_id')is not None:
            if not isinstance(b.get('expected_task_id'),str)or type(b.get('expected_version_at_prepare'))is not int or not isinstance(b.get('expected_journal_sha256'),str):invalid.append('state_boundary_error')
            else:versions.add((b['expected_task_id'],b.get('expected_version_at_prepare')))
    journals={};replayed={}
    if variant=='pi-memweave':
        reducer=Path(__file__).resolve().parents[3]/'src/state/model.ts'
        if expected_reducer_sha256 is not None and hashlib.sha256(reducer.read_bytes()).hexdigest()!=expected_reducer_sha256:
            return {'complete':False,'reason':'frozen_product_reducer_changed','assertions':{}}
        try:journals=_journals(agent/'memory.tar.gz');replayed=_replay_prefixes(journals,versions)
        except (ValueError,OSError,tarfile.TarError,subprocess.SubprocessError):invalid.append('state_replay_invalid')
    def entries(e):
        if variant=='pi-native':
            note=workspace(e).get('memory_capsules')
            if not isinstance(note,dict)or note.get('status')not in ('present','absent','invalid'):return None
            if not isinstance(note.get('values'),list)or note['status']=='present'and(not isinstance(note.get('sha256'),str)or len(note['sha256'])!=64):return None
            return [{'value':v,'archived':False}for v in note['values']] if note.get('status')!='invalid'else[]
        b=e.get('state_boundary',{})
        if not isinstance(b,dict):return None
        task=b.get('expected_task_id');v=b.get('expected_version_at_prepare')
        if task is None:return []
        lines=journals.get(task);values=replayed.get((task,v))
        if values is None or hashlib.sha256(b''.join(lines[:v])).hexdigest()!=b.get('expected_journal_sha256'):return None
        out=[]
        for item in values:
            try:value=json.loads(item['content'])
            except ValueError:continue
            if isinstance(value,dict):out.append({'value':value,'archived':item['archived'],'id':item['id']})
        return out
    if any(entries(e)is None for _,e in boundaries):invalid.append('capsule_boundary_source_missing')
    edits={k:[]for k in GOLD};all_edits=[]
    for identity,(i,before)in tool_starts.items():
        if identity not in tool_ends:continue
        j,after=tool_ends[identity];bf=workspace(before).get('files',{});af=workspace(after).get('files',{})
        if not isinstance(bf,dict)or not isinstance(af,dict):invalid.append('workspace_fields_missing');continue
        if set(initial)-set(bf)or set(initial)-set(af):invalid.append('workspace_fields_missing')
        changed=[f for f in initial if bf.get(f)!=af.get(f)]
        if changed:all_edits.append((i,j))
        for k,files in DEPENDENCIES.items():
            if any(f in changed for f in files):edits[k].append((i,j,before,after))
    complete=not invalid;assertions={};details={}
    probes={}
    ctrf=trial/'verifier/derived-ctrf.json'
    if ctrf.is_file():
        try:
            for row in json.loads(ctrf.read_text())['results']['tests']:
                name=row.get('name');value={'passed':'pass','failed':'fail'}.get(row.get('status'),'missing')
                if name in probes:probes[name]='invalid'
                else:probes[name]=value
        except (ValueError,KeyError,TypeError,AttributeError):pass
    def read_visible(key,low,high):
        for i,start in tool_starts.values():
            identity=start.get('call_id')
            if identity not in tool_ends:continue
            j,end=tool_ends[identity]
            if not low<i<j<high or end.get('tool_is_error')is not False:continue
            if start.get('tool_name')!=('state_read'if variant=='pi-memweave'else'read'):continue
            if variant=='pi-native'and start.get('tool_path')!=NOTE:continue
            for q in trace[j+1:high]:
                if q.get('event')!='request_ready':continue
                for delivery in q.get('capsule_deliveries',[]):
                    if delivery.get('tool_call_id')!=identity:continue
                    if variant=='pi-memweave':
                        b=end.get('state_boundary',{})
                        if not isinstance(b,dict):continue
                        if delivery.get('task_id')!=b.get('expected_task_id')or delivery.get('state_version')!=b.get('expected_version_at_prepare'):continue
                    observed=[{'value':v,'archived':False}for v in delivery.get('values',[])]
                    if all(v=='pass'for v in truth(observed,key).values()):return True
        return False
    for key in GOLD:
        t=truth(entries(ends[0][1]),key)
        first=edits[key][0]if edits[key]else None
        before=truth(entries(first[2]),key)if first else None
        timely=bool(first and all(v=='pass'for v in before.values()))
        # Read starts strictly after a boundary that independently confirms correct persistence.
        saved=[i for i,e in boundaries if all(v=='pass'for v in truth(entries(e),key).values())]
        recalled=bool(first and any(read_visible(key,i,first[0])for i in saved if i<first[0]))
        final_read=bool(all_edits and all(v=='pass'for v in t.values())and read_visible(key,max(j for _,j in all_edits),ends[0][0]))
        for field,value in t.items():assertions[f'capsule:{key}:truth:{field}']=value if complete else'missing'
        for field,value in [('saved_before_edit',timely),('explicit_recall',recalled)]:assertions[f'capsule:{key}:timely:{field}']=('pass'if value else'fail')if complete else'missing'
        for field,value in [('prior_capture_and_recall',timely and recalled),('final_review',final_read)]:assertions[f'capsule:{key}:use:{field}']=('pass'if value else'fail')if complete else'missing'
        for n in (1,2):assertions[f'capsule:{key}:use:probe{n}']=probes.get(f'tb01_capsule_actions.py::test_{key}_{n}','missing')
        details[key]={'first_dependency_trace_position':first[0]if first else None,'recorded_before_edit':timely,'explicit_recall_delivered':recalled,'final_review_delivered':final_read,'final_truth':t}
    return {'protocol':PROTOCOL,'complete':complete,'issues':sorted(set(invalid)),'assertions':assertions,'opportunities':details,
        'decoder_version':'tb01-state-read-json.v2','delivery_recoveries':recoveries,'recovery_sources':recovery_sources,
        'interpretation':'Prompted finite propositions plus explicit read/delivery/action compliance; not free-text generalization, mental reading or causal benefit.'}
