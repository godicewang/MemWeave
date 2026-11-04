"""Exact LONG-05 source gates; original collapsed CTRF counts stay separate."""
from __future__ import annotations

import ast
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from .fixed35 import checkpoint_verdict
from .storage import atomic_json, file_digest

VERSION='fixed35-ruby-source-20261104-v1'
GROUPS={'security':['auth_register_login','csrf_session','csp_security_headers','rate_limit'],
 'orm':['orm_basic','orm_associations','orm_validations'],
 'content':['posts_crud','comments_crud','tags_taxonomy','admin_moderation'],
 'views':['routes','views_liquid','rss_atom_sitemap','pagination'],
 'persistence':['search_fts5','media_uploads','caching_etag','background_jobs'],
 'replay-load':['fixture_replay','concurrency_smoke']}


def source_ids(path,traces):
    tree=ast.parse(path.read_text());cases=next((ast.literal_eval(n.value)for n in tree.body
        if isinstance(n,ast.AnnAssign)and isinstance(n.target,ast.Name)and n.target.id=='CASES'),None)
    ids=[]
    for n in tree.body:
        if not isinstance(n,ast.FunctionDef)or not n.name.startswith('test_'):continue
        base=path.name+'::'+n.name
        if not n.decorator_list:ids.append(base);continue
        if len(n.decorator_list)!=1:raise ValueError('unexpected source decorators')
        d=n.decorator_list[0]
        if not isinstance(d,ast.Call)or not isinstance(d.func,ast.Attribute)or d.func.attr!='parametrize':
            raise ValueError('unexpected source parametrization')
        if path.name=='test_fixture_replay.py'and ast.literal_eval(d.args[0])=='trace':
            ids.extend(base+'[trace_'+str(t['idx']).zfill(4)+']'for t in traces)
        elif path.name=='test_markdown_render.py'and ast.literal_eval(d.args[0])=='case_name,markdown':
            ids.extend(base+'['+'-'.join(v.encode('unicode_escape').decode('ascii')for v in row)+']'for row in cases)
        else:raise ValueError('unadapted source parameters')
    if not ids or len(ids)!=len(set(ids)):raise ValueError('empty or repeated source identities')
    return ids


def freeze_contract(case,source:Path,output:Path,*,metric_matrix=None):
    pin=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if case['pack_case_id']!='LONG-05'or case['upstream_case_id'].rsplit('/',1)[-1]!='ruby-rust-port' \
            or pin!=case['source_revision']or subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):
        raise ValueError('selected clean Ruby source pin required')
    task=source/'tasks/ruby-rust-port';tests=task/'tests'
    script=(tests/'test.sh').read_text()
    calls=re.findall(r'^run_gate\s+(\w+)\s+/tests/(test_\w+\.py)\s*$',script,re.MULTILINE)
    wanted={n for names in GROUPS.values()for n in names}|{'markdown_render'}
    if len(calls)!=22 or {n for n,_ in calls}!=wanted:raise ValueError('Ruby gate source changed')
    traces=[json.loads(l)for l in (tests/'fixtures/golden_traces.jsonl').read_text().splitlines()if l.strip()]
    if len(traces)!=2000 or len({t['idx']for t in traces})!=2000:raise ValueError('Ruby trace corpus changed')
    gates={n:{'file':f,'ids':source_ids(tests/f,traces)}for n,f in calls}
    if sum(len(g['ids'])for g in gates.values())!=2298:raise ValueError('Ruby source sample count changed')
    paths=[task/'instruction.md',task/'task.toml',*tests.rglob('*')]
    if any(p.is_symlink()for p in paths):raise ValueError('redirected Ruby source')
    value={'case_id':'LONG-05','version':VERSION,'adapter_kind':'ruby-source-v1','source_revision':pin,
        'source_hashes':{str(p):file_digest(p)for p in paths if p.is_file()},'gates':gates,'groups':GROUPS,
        'allowed_skip_functions':['test_markdown_render.py::test_markdown_renders_consistent_html'],
        'metric_matrix':metric_matrix or[],'not_formal_admission':True,'fixture_only':False,'gold_actor_visible':False,
        'scope':'Exact source business outcomes; six strict groups exclude documented Markdown divergence skips; no State/Task/adoption proof'}
    atomic_json(output,value,immutable=True);return value


def read_gate(verifier,name,spec,allowed):
    issues=[];outcomes={};log=verifier/(name+'.log');cp=verifier/(name+'_ctrf.json')
    text=log.read_text()if log.is_file()else''
    for line in text.splitlines():
        m=re.match(r'^(?:.*?/)?(test_\w+\.py::.*) (PASSED|FAILED|SKIPPED|ERROR)\s+\[\s*\d+%\]',line)
        if not m:continue
        if m[1]in outcomes:issues.append('duplicate_console_identity')
        outcomes[m[1]]=m[2]
    if set(outcomes)!=set(spec['ids']):issues.append('console_identity_set')
    terminal=re.findall(r'^=+ (.*?) in [\d.]+s =+\s*$',text,re.MULTILINE)
    counts=Counter(outcomes.values())
    if not terminal:issues.append('terminal_summary_missing')
    else:
        declared={s.upper():int(n)for n,s in re.findall(r'(\d+) (passed|failed|skipped|errors?)',terminal[-1])}
        if any(declared.get(s,0)!=counts[s]for s in ['PASSED','FAILED','SKIPPED','ERROR']):issues.append('terminal_count_mismatch')
    by_function=defaultdict(list)
    for identity,status in outcomes.items():by_function[identity.split('[')[0]].append(status)
    ctrf_counts={};rows=[]
    try:
        data=json.loads(cp.read_text())['results'];rows=data['tests'];summary=data['summary']
        if not isinstance(rows,list)or not all(isinstance(r,dict)for r in rows)or not isinstance(summary,dict):
            raise ValueError('invalid source CTRF shape')
        if len(rows)!=len(by_function)or len({r['name']for r in rows})!=len(rows):issues.append('ctrf_function_identity')
        if {r['name']for r in rows}!=set(by_function):issues.append('ctrf_function_set')
        for r in rows:
            states=by_function.get(r['name'],[])
            status='failed'if any(s in {'FAILED','ERROR'}for s in states)else'skipped'if'SKIPPED'in states else'passed'
            if r['status']!=status or type(r.get('retries',0))is not int or r.get('retries',0)!=len(states)-1:
                issues.append('ctrf_collapsed_outcome')
        count=Counter(r['status']for r in rows)
        for key in ['tests','passed','failed','skipped','pending','other']:
            value=summary.get(key)
            if type(value)is not int or value!=(len(rows)if key=='tests'else count[key]):issues.append('ctrf_count_mismatch')
            if type(value)is int and value>=0:ctrf_counts[key]=value
    except (OSError,ValueError,KeyError,TypeError):issues.append('ctrf_missing_invalid')
    disallowed=[i for i,s in outcomes.items()if s=='SKIPPED'and i.split('[')[0]not in allowed]
    if disallowed or counts['ERROR']:issues.append('unexpected_skip_or_error')
    source_accepts=not any(s in {'FAILED','ERROR'}for s in outcomes.values())and not disallowed
    return {'outcomes':outcomes,'issues':issues,'ctrf_counts':ctrf_counts,'source_accepts':source_accepts,
        'counts':{s.lower():counts[s]for s in ['PASSED','FAILED','SKIPPED','ERROR']},
        'log':str(log),'ctrf':str(cp)}


def grade_trial(trial:Path,contract,*,fixture_control=False):
    for p,d in contract['source_hashes'].items():
        if file_digest(Path(p))!=d:raise ValueError('Ruby source changed')
    rp=trial/'result.json';result=json.loads(rp.read_text())if rp.is_file()else{}
    agent=result.get('config',{}).get('agent',{});fixture=bool(fixture_control or agent.get('name')in {'oracle','nop'}or
        agent.get('import_path')in {'memweave_eval.resource_control:ResourceOracle','memweave_eval.resource_control:ResourceNop'}or
        agent.get('kwargs',{}).get('prepare_only')is True)
    if fixture and not fixture_control:raise ValueError('Ruby controls require explicit fixture-control')
    v=trial/'verifier';issues=[];metrics={};reward=None
    try:
        metrics=json.loads((v/'metrics.json').read_text())
        if not isinstance(metrics,dict):raise TypeError('invalid original metrics')
        value=float((v/'reward.txt').read_text())
        reported=(result.get('verifier_result')or{}).get('rewards',{}).get('reward')
        if value in (0,1)and type(reported)in (int,float)and value==reported:reward=value
    except (OSError,ValueError,TypeError):metrics={}if not isinstance(metrics,dict)else metrics
    if reward is None:issues.append('reward_missing_or_mismatch')
    console=(v/'test-stdout.txt').read_text()if(v/'test-stdout.txt').is_file()else''
    health_failure=bool(reward==0 and 'FAIL: rj-rust :8000 did not come up'in console and
        all(type(metrics.get(k))is int and metrics[k]==0 for k in ['gates_passed','gates_total','tests_passed','tests_total'])and
        metrics.get('reward')==0 and metrics.get('partial_score')==0 and not list(v.glob('*_ctrf.json'))and
        not any((v/(n+'.log')).exists()for n in contract['gates']))
    gates={}if health_failure else{n:read_gate(v,n,s,contract['allowed_skip_functions'])for n,s in contract['gates'].items()}
    for n,g in gates.items():issues.extend(n+':'+e for e in g['issues'])
    raw=Counter();expanded=Counter()
    for g in gates.values():raw.update(g['ctrf_counts']);expanded.update(g['counts'])
    if not health_failure:
        if {p.name for p in v.glob('*_ctrf.json')}!={n+'_ctrf.json'for n in gates}:issues.append('unexpected_gate_artifact')
        expected={'tests_passed':raw['passed'],'tests_total':raw['tests'],'gates_total':len(gates),
            'gates_passed':sum(g['source_accepts']for g in gates.values())}
        for k,value in expected.items():
            if type(metrics.get(k))is not int or metrics[k]!=value:issues.append('original_metrics:'+k)
        partial=raw['passed']/raw['tests']if raw['tests']else None;value=metrics.get('partial_score')
        if type(value)not in (int,float)or not math.isfinite(value)or partial is None or abs(value-partial)>1e-12:
            issues.append('original_partial_mismatch')
        if metrics.get('health')is not True or metrics.get('anti_cheat')is not True:issues.append('source_health_anti_cheat')
        expected_reward=int(all(g['source_accepts']for g in gates.values()))
        if reward!=expected_reward or metrics.get('reward')!=expected_reward:issues.append('original_reward_contradiction')
        if not re.search(r'^reward=[01]\s+partial_score=[\d.]+\s+tests=\d+/\d+\s+gates=\d+/\d+\s*$',console,re.MULTILINE):
            issues.append('source_terminal_missing')
    points={}
    for name,names in contract['groups'].items():
        checks={'mandatory_rust_service_available':False}if health_failure else{
            i:True if s=='PASSED'else False if s=='FAILED'else None for n in names for i,s in gates[n]['outcomes'].items()}
        if not health_failure:
            for n in names:
                for i in contract['gates'][n]['ids']:checks.setdefault(i,None)
            checks['source_gate_evidence_complete']=not any(gates[n]['issues']for n in names)or None
        points[name]=checkpoint_verdict({'id':'F35.SOURCE.LONG-05.'+name,'required_assertions':list(checks)},checks)
    common=checkpoint_verdict({'id':'F35.SOURCE.LONG-05.strict-core','required_assertions':list(points)},
        {n:p['score']==100 if p['collection_complete']else None for n,p in points.items()})
    process=checkpoint_verdict({'id':'F35.SOURCE.LONG-05.original-protocol','required_assertions':[
        'original_gate_acceptance','complete_source_protocol_evidence']},
        {'original_gate_acceptance':bool(reward)if reward is not None else None,
         'complete_source_protocol_evidence':True if not issues else None})
    total=sum(len(s['ids'])for s in contract['gates'].values())
    return {'version':VERSION,'case_id':'LONG-05','fixture_only':fixture,'original_reward':reward,
        'original_metrics':metrics,'original_ctrf_counts':dict(raw),
        'expanded_source_counts':dict({s:expanded[s]for s in ['passed','failed','skipped','error']},total=0 if health_failure else sum(expanded.values())),
        'expected_source_cases':total,'unexecuted_source_cases':total if health_failure else 0,
        'health_delivery_failure_proved':health_failure,'evidence_issues':issues,'gates':gates,
        'checkpoints':points,'common_checkpoint':common,'process_checkpoint':process,
        'collection_complete':not issues and all(p['collection_complete']for p in points.values()),
        'scope':contract['scope'],'not_a_memory_adoption_score':True,
        'artifacts':{str(p):file_digest(p)for p in v.iterdir()if p.is_file()}if v.is_dir()else{}}


def checkpoint_rows(result):
    points=dict(result['checkpoints'],original_protocol=result['process_checkpoint'])
    return [{'id':p['checkpoint_id'],'meaning':'LONG-05 '+name+'; '+result['scope'],
        'applicability':'all','raw':p['score']/100 if p['score']is not None else None,'score':p['score'],
        'status':p['status'],'raw_formula':'AND of frozen original source assertions and complete source identity proof; original protocol accepts documented Markdown skips, not a claim they passed',
        'score_formula':'100 if all required predicates pass; known failure 0; absent proof remains explicit',
        'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
        'weight_reason':'Source subpoints explain existing common outcomes; no duplicate child-assertion weighting',
        'support_s':sum(a['value']is True for a in p['assertions'].values()),
        'support_f':len(p['failed_assertions']),'support_u':len(p['missing_assertions']),
        'support_n':len(p['assertions']),'collection_complete':p['collection_complete']}for name,p in points.items()]
