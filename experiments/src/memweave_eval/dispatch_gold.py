"""TB-09's real temporal/business score, never its constant-success CTRF stub."""
from __future__ import annotations

import ast
import json
import math
import subprocess
from pathlib import Path, PurePosixPath

from .fixed35 import checkpoint_verdict
from .storage import atomic_json, file_digest

VERSION='fixed35-dispatch-source-20261104-v1'
BASE=['dispatch executable exists','timestamped event files hidden from main packet',
 'full CLI trace exits successfully','expected margins derivable from packet','all trace JSON outputs valid']


def _literal(node,paths):
    if isinstance(node,ast.Constant)and isinstance(node.value,str):return node.value
    if isinstance(node,ast.Name):return paths[node.id]
    if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Div):return str(PurePosixPath(_literal(node.left,paths))/_literal(node.right,paths))
    if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id in {'Path','str'}and len(node.args)==1:
        return _literal(node.args[0],paths)
    raise ValueError('unsupported static command argument')


def freeze_contract(case,source:Path,output:Path,*,metric_matrix=None):
    if case['pack_case_id']!='TB-09'or case['upstream_case_id'].rsplit('/',1)[-1]!='freight-dispatch-shift':
        raise ValueError('selected dispatch source required')
    pin=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if pin!=case['source_revision']or subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True):raise ValueError('dispatch source changed or dirty')
    task=source/'tasks/freight-dispatch-shift';tree=ast.parse((task/'tests/test_scoring.py').read_text())
    paths={};requests=[]
    for node in tree.body:
        if not isinstance(node,ast.Assign):continue
        if any(isinstance(t,ast.Name)and t.id=='EXPECTED'for t in node.targets):
            requests=[k.value for k in node.value.keys]
        for target in node.targets:
            if isinstance(target,ast.Name):
                try:paths[target.id]=_literal(node.value,paths)
                except (ValueError,KeyError):pass
    weights={};plan_checks=[];commands=None
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='commands'for t in node.targets):
            commands=[[_literal(value,paths)for value in command.elts]for command in node.value.elts]
        if not isinstance(node,ast.Call)or not isinstance(node.func,ast.Attribute)or not isinstance(node.func.value,ast.Name)or node.func.value.id!='score':continue
        if node.func.attr=='diagnostic'and isinstance(node.args[0],ast.Constant):
            name=node.args[0].value
            if name.endswith(' plan is valid JSON'):plan_checks.append(name)
        if node.func.attr not in {'add','case'}:continue
        weight=node.args[2].value if len(node.args)>2 and isinstance(node.args[2],ast.Constant)else 1.
        if type(weight)not in (int,float)or not math.isfinite(weight)or weight<=0:raise ValueError('unsupported source weight')
        first=node.args[0]
        if isinstance(first,ast.Constant):names=[first.value]
        elif isinstance(first,ast.JoinedStr)and len(first.values)==2 and isinstance(first.values[0],ast.FormattedValue) \
                and isinstance(first.values[0].value,ast.Name)and first.values[0].value.id=='rid'and isinstance(first.values[1],ast.Constant):
            names=[rid+first.values[1].value for rid in requests]
        else:raise ValueError('unsupported source score name')
        for name in names:
            if name in weights and weights[name]!=weight:raise ValueError('source check weight conflict')
            weights[name]=weight
    if len(weights)!=40 or sum(weights.values())!=232 or not commands or len(commands)!=20 or len(plan_checks)!=8:
        raise ValueError('selected dispatch protocol changed')
    visibility=[n for n in weights if'visibility case'in n or'replan case'in n]
    corrections=[n for n in weights if n.startswith('hardening ')or n in {'state ledger case','stateful commitments case'}]
    assignments=[n for n in weights if n.endswith(': final request case')]
    used=set(visibility+corrections+assignments)
    groups={'temporal-visibility':visibility,'current-corrections-ledger':corrections,
        'twenty-request-assignments':assignments,'operations-timeline-audit':[n for n in weights if n not in used]}
    files=[task/'instruction.md',task/'task.toml',*(task/'tests').rglob('*')]
    contract={'version':VERSION,'adapter_kind':'dispatch-source-v1','case_id':'TB-09','source_revision':pin,
        'weighted_checks':weights,'base_checks':BASE,'plan_presence_checks':plan_checks,'commands':commands,'groups':groups,
        'common_groups':['temporal-visibility','current-corrections-ledger'],
        'source_hashes':{str(p):file_digest(p)for p in files if p.is_file()},'metric_matrix':metric_matrix or[],
        'not_formal_admission':True,'gold_actor_visible':False,
        'scope':'Original dispatch event-cutoff, correction, assignment and audit program verdicts; not MemWeave State adoption'}
    atomic_json(output,contract,immutable=True);return contract


def _number(v):return type(v)in (int,float)and math.isfinite(v)


def grade_trial(trial:Path,contract,*,fixture_control=False):
    for path,digest in contract['source_hashes'].items():
        if file_digest(Path(path))!=digest:raise ValueError('frozen dispatch source changed')
    issues=[]
    def load(path):
        try:
            value=json.loads(path.read_text())
            if not isinstance(value,dict):raise TypeError('not an object')
            return value
        except (FileNotFoundError,ValueError,TypeError):issues.append('missing_or_invalid:'+path.name);return{}
    verifier=trial/'verifier';result=load(trial/'result.json');raw=load(verifier/'trace_results.json')
    agent=result.get('config',{}).get('agent',{})
    fixture=agent.get('name')in {'oracle','nop'}or agent.get('kwargs',{}).get('prepare_only')is True
    if fixture and not fixture_control:raise ValueError('dispatch controls require explicit fixture-control')
    positive={};diagnostics={};values=raw.get('checks')
    if not isinstance(values,list):values=[];issues.append('checks_missing')
    for check in values:
        if not isinstance(check,dict)or not isinstance(check.get('name'),str)or type(check.get('passed'))is not bool \
                or not _number(check.get('weight'))or check['weight']<0:
            issues.append('invalid_check');continue
        name=check['name']
        if check['weight']==0:diagnostics.setdefault(name,[]).append(check['passed']);continue
        if name in positive:issues.append('duplicate_positive_check:'+name)
        positive[name]=check
        if contract['weighted_checks'].get(name)!=check['weight']:issues.append('unexpected_check_or_weight:'+name)
    available=(positive.get('dispatch executable exists')or{}).get('passed')
    commands=raw.get('command_outputs');command_ok=True
    if not isinstance(commands,list):commands=[];issues.append('commands_missing')
    expected=contract['commands']
    for i,command in enumerate(commands):
        if i>=len(expected)or not isinstance(command,dict)or command.get('command')!=expected[i]or type(command.get('ok'))is not bool:
            command_ok=False
    full=(positive.get('full CLI trace exits successfully')or{}).get('passed')
    branch='UNKNOWN';expected_names=set(contract['weighted_checks']);plan_guard=None
    if available is False:
        branch='NO_EXECUTABLE';expected_names={'dispatch executable exists'}
        if commands:command_ok=False
    elif available is True:
        flags=[]
        for name in contract['plan_presence_checks']:
            parts=diagnostics.get(name,[])
            if len(parts)!=1:issues.append('missing_or_duplicate_plan_guard:'+name);flags.append(None)
            else:flags.append(parts[0])
        if all(type(v)is bool for v in flags):
            plan_guard=all(flags);branch='FULL'if plan_guard else'INCOMPLETE_PLANS'
            expected_names=set(contract['weighted_checks']if plan_guard else contract['base_checks'])
        if full is True:
            command_ok &= len(commands)==len(expected)and all(c.get('ok')is True for c in commands if isinstance(c,dict))
        elif full is False:
            command_ok &= bool(commands)and all(isinstance(c,dict)for c in commands)and commands[-1].get('ok')is False and all(c.get('ok')is True for c in commands[:-1])
        else:issues.append('full_cli_verdict_missing')
    else:issues.append('executable_verdict_missing')
    if not command_ok:issues.append('command_transcript_mismatch')
    if set(positive)!=expected_names:issues.append('source_branch_check_set_mismatch')
    total=sum(c['weight']for c in positive.values());points=sum(c['weight']for c in positive.values()if c['passed'])
    for key,want in [('points',points),('total',total),('diagnostic_score',round(points/total,4)if total else 0)]:
        if not _number(raw.get(key))or not math.isclose(raw[key],want,abs_tol=1e-9):issues.append('source_arithmetic_mismatch:'+key)
    native=load(verifier/'reward.json').get('reward');reported=(result.get('verifier_result')or{}).get('rewards',{}).get('reward')
    rewards=[raw.get('reward'),native,reported]
    reward=rewards[0]if all(_number(v)and v in (0,1)for v in rewards)and len(set(rewards))==1 else None
    if reward is None:issues.append('source_reward_mismatch')
    elif bool(reward)!=(bool(total)and points==total):issues.append('source_reward_arithmetic_mismatch')
    prerequisite_failed=available is False or plan_guard is False
    points_by_group={};not_executed=[]
    for name,identities in contract['groups'].items():
        if prerequisite_failed and not set(identities)<=set(positive):
            checks={'required_delivery_prerequisite':False};not_executed.extend(i for i in identities if i not in positive)
        else:checks={i:(positive.get(i)or{}).get('passed')for i in identities}
        checks['source_capture_consistent']=True if not issues else None
        point=checkpoint_verdict({'id':'F35.DISPATCH.'+name,'required_assertions':list(checks)},checks)
        points_by_group[name]=point
    whole_checks={i:c['passed']for i,c in positive.items()}
    whole_checks['complete_source_branch_evidence']=True if not issues else None
    whole=checkpoint_verdict({'id':'F35.DISPATCH.whole-protocol','required_assertions':list(whole_checks)},whole_checks)
    common_checks={name:points_by_group[name]['score']==100 if points_by_group[name]['collection_complete']else None
        for name in contract.get('common_groups',contract['groups'])}
    common=checkpoint_verdict({'id':'F35.DISPATCH.temporal-current-business','required_assertions':list(common_checks)},common_checks)
    process_checks={'required_delivery_prerequisite':False}if available is False else{
        'full_cli_trace_succeeds':full,'all_business_outputs_valid_json':(positive.get('all trace JSON outputs valid')or{}).get('passed')}
    process_checks['complete_command_and_source_capture']=True if not issues else None
    process=checkpoint_verdict({'id':'F35.DISPATCH.source-command-protocol','required_assertions':list(process_checks)},process_checks)
    return {'version':VERSION,'case_id':'TB-09','fixture_only':fixture,'original_reward':reward,
        'original_weighted_diagnostic':{'points':raw.get('points'),'total':raw.get('total'),'ratio':raw.get('diagnostic_score')},
        'source_branch':branch,'observed_positive_checks':len(positive),'source_positive_checks':positive,
        'downstream_not_executed':sorted(set(not_executed)),'command_count':len(commands),
        'checkpoints':points_by_group,'whole_protocol':whole,'evidence_issues':issues,
        'common_checkpoint':common,'process_checkpoint':process,
        'collection_complete':not issues and all(p['collection_complete']for p in points_by_group.values()),
        'artifacts':{str(p):file_digest(p)for p in [trial/'result.json',verifier/'trace_results.json',verifier/'reward.json']if p.is_file()},
        'scope':contract['scope'],'ctrf_is_not_a_business_score':True}


def checkpoint_rows(result):
    points=dict(result['checkpoints'],whole_protocol=result['whole_protocol'],command_protocol=result['process_checkpoint'])
    rows=[{'id':p['checkpoint_id'],'meaning':'TB-09 source '+name+'; '+result['scope'],
        'applicability':'all','raw':p['score']/100 if p['score']is not None else None,'score':p['score'],
        'status':p['status'],'raw_formula':'AND('+', '.join(p['assertions'])+'); source branch='+result['source_branch'],
        'score_formula':'100 * binary checkpoint; failed mandatory delivery prerequisite is 0, downstream unexecuted cases remain listed',
        'mapping_version':VERSION,'weights':{'common_product':0,'plugin_memory':0},
        'weight_reason':'Supplementary source checks, no repeated leaf weight',
        'support_s':sum(a['status']=='pass'for a in p['assertions'].values()),'support_f':len(p['failed_assertions']),
        'support_u':len(p['missing_assertions']),'support_n':len(p['assertions']),
        'collection_complete':p['collection_complete']}for name,p in points.items()]
    diagnostic=result['original_weighted_diagnostic'];known=result['collection_complete']
    rows.append({'id':'F35.DISPATCH.original-weighted-diagnostic','meaning':'Original source executed-branch weighted diagnostic; denominator may be 232 or 5, not native reward',
        'applicability':'all','raw':diagnostic['ratio'],'raw_formula':'source points/source total, rounded to 4 decimals by original verifier',
        'score':100*diagnostic['ratio']if known else None,'score_formula':'100 * source diagnostic ratio',
        'status':'SCORED'if known else'MISSING_EVIDENCE','mapping_version':VERSION,
        'weights':{'common_product':0,'plugin_memory':0},'weight_reason':'Original source diagnostic only; variable executed-branch denominator, no extra aggregate weight',
        'support_s':diagnostic['points'],'support_f':diagnostic['total']-diagnostic['points']if known else None,
        'support_u':0 if known else None,'support_n':diagnostic['total'],'collection_complete':known})
    return rows
