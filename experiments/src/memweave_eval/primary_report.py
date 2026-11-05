"""Offline, explicitly approved per-case E/H scores; never call or modify an actor.

Original business rewards are carried through separately. A fixture result is not
an actor result. No defaults, applicability choices or weights are inferred here.
"""
from __future__ import annotations

import math

from .primary_score import behavior_score, relative_score, weighted_total

ARMS=('pi-native','pi-memweave')


def ctrf_assertions(report,names):
    results=report.get('results')if isinstance(report,dict)else None
    tests=results.get('tests')if isinstance(results,dict)else None
    if not isinstance(tests,list):return {'test:'+n:'missing'for n in names}
    result={}
    for name in names:
        rows=[r for r in tests if isinstance(r,dict)and r.get('name')==name]
        if len(rows)>1:status='invalid'
        elif not rows:status='missing'
        else:status={'passed':'pass','failed':'fail'}.get(rows[0].get('status'),'missing')
        result['test:'+name]=status
    return result


def validate_contract(contract):
    if not isinstance(contract,dict)or contract.get('schema_version')!='primary-score-contract.v1' \
            or contract.get('status')!='approved' or not contract.get('scoring_version')or not contract.get('case_id'):
        raise ValueError('approved, versioned primary case scoring contract required')
    seen=set()
    for category in ('engineering','behavior'):
        metrics=contract.get(category)
        if not isinstance(metrics,list)or not metrics:raise ValueError('both independent categories require a fixed metric set')
        for m in metrics:
            if not isinstance(m,dict)or any(not isinstance(m.get(k),str)or not m[k]for k in ('id','meaning','raw_formula','unit')):
                raise ValueError('metric identity, meaning, formula and unit required')
            if m['id']in seen:raise ValueError('duplicate metric identity')
            seen.add(m['id']);w=m.get('weight')
            if type(w)not in(int,float)or not math.isfinite(w)or w<0:raise ValueError('finite nonnegative frozen weight required')
            if category=='engineering'and(m.get('mapping')not in {'rate_difference','lower_share'}or not isinstance(m.get('source'),str)):
                raise ValueError('explicit engineering source and relative mapping required')
            if category=='behavior':behavior_score(m.get('opportunities'),{})
        if not math.isfinite(sum(m['weight']for m in metrics))or sum(m['weight']for m in metrics)<=0:
            raise ValueError('each category requires a positive finite weight sum')
    return contract


def score_pair(contract,arms):
    validate_contract(contract)
    if not isinstance(arms,dict)or set(arms)!=set(ARMS)or any(not isinstance(arms[a],dict)for a in ARMS):
        raise ValueError('exactly one native and one plugin arm required')
    engineering={};behaviors={a:{}for a in ARMS}
    for definition in contract['engineering']:
        source=definition['source'];raw={}
        for arm in ARMS:
            values=arms[arm].get('metrics',{})
            if not isinstance(values,dict):raise TypeError('raw metrics must be an object')
            raw[arm]=values.get(source,{})
        for value in raw.values():
            if not isinstance(value,dict):raise TypeError('raw metric must be an object')
        if all(raw[a].get('status')=='observed'for a in ARMS):
            score=relative_score(raw[ARMS[0]].get('raw'),raw[ARMS[1]].get('raw'),mapping=definition['mapping'])
        else:
            states={raw[a].get('status','missing')for a in ARMS}
            score={'score':None,'status':'invalid'if 'invalid'in states else'not_comparable'if states=={'not_comparable'}else'missing',
                   'reason':'both arms need valid same-window raw observations'}
        engineering[definition['id']]={**definition,**score,'arm_raw':raw}
    for definition in contract['behavior']:
        for arm in ARMS:
            assertions=arms[arm].get('assertions',{})
            if not isinstance(assertions,dict):raise TypeError('assertion evidence must be an object')
            evidence={o['id']:{a:assertions[a]for a in o['required_assertions']if a in assertions}for o in definition['opportunities']}
            behaviors[arm][definition['id']]={**definition,**behavior_score(definition['opportunities'],evidence)}
    ew={m['id']:m['weight']for m in contract['engineering']};hw={m['id']:m['weight']for m in contract['behavior']}
    return {'schema_version':'primary-paired-report.v1','case_id':contract['case_id'],'scoring_version':contract['scoring_version'],
        'engineering':{'interpretation':'plugin relative to native; equivalence is 50','metrics':engineering,'total':weighted_total(engineering,ew)},
        'behavior':{a:{'metrics':behaviors[a],'total':weighted_total(behaviors[a],hw)}for a in ARMS},
        'original_business_results':{a:arms[a].get('original_business_result')for a in ARMS},
        'scope':contract.get('scope'),'not_an_official_leaderboard_result':True}


def score_run(root,lock,rows):
    """Only a new primary-default run may select this versioned report path."""
    import json

    from .primary_evidence import collect_arm
    from .storage import contained, file_digest

    path=root/'primary-case.json'
    if not path.is_file()or file_digest(path)!=lock.get('primary_case_sha256'):
        raise ValueError('frozen primary case contract missing or changed')
    contract=validate_contract(json.loads(path.read_text()))
    if len(rows)!=2 or {r['variant_id']for r in rows}!=set(ARMS)or any(r['task_id']!=contract.get('task_name')for r in rows):
        raise ValueError('one frozen first-case pair required; no silent task or repetition pooling')
    names=contract.get('verifier_test_names')
    if not isinstance(names,list)or not names or len(set(names))!=len(names)or any(not isinstance(n,str)for n in names):
        raise ValueError('frozen original verifier test identities required')
    index=json.loads((root/'evidence-index.json').read_text())
    hashes={i['path']:i['sha256']for i in index['files']}
    authority={}
    for name,key in [('quota.final.json','ledger'),('transport-terminal.json','terminal'),('transport-audit.jsonl','audit')]:
        source=root/'trusted'/name
        if not source.is_file():authority[key]=None;continue
        relative=source.relative_to(root).as_posix()
        if hashes.get(relative)!=file_digest(source):raise ValueError('trusted authority source changed or unindexed')
        authority[key]=[json.loads(line)for line in source.read_text().splitlines()]if key=='audit'else json.loads(source.read_text())
    arms={}
    for row in rows:
        source=row.get('score_source')
        principal=(row['task_id']+':'+row['variant_id'])if (lock.get('config',{}).get('evaluation')or{}).get('per_task_arm_caps')else row['variant_id']
        arm=collect_arm(contained(root,source).parent,names,authority=authority,arm=principal,episode=lock['run_id'])if source else {'metrics':{},'assertions':{}}
        if source and contract.get('memory_protocol')=='tb01-capsule.v1':
            from .tb01_capsules import collect_capsules
            capsule=collect_capsules(contained(root,source).parent,row['variant_id'],expected_reducer_sha256=contract.get('state_reducer_sha256'))
            arm['capsule_evidence']=capsule;arm['assertions'].update(capsule['assertions'])
            if not capsule['complete']:arm['parse_issues'].append('capsule_source_chain_incomplete')
            memory=contained(root,source).parent/'agent/memory.tar.gz'
            if row['variant_id']=='pi-memweave'and memory.is_file():arm['sources']['agent/memory.tar.gz']=file_digest(memory)
        if source:
            parent=contained(root,source).parent
            for name,digest in arm['sources'].items():
                relative=(parent/name).relative_to(root).as_posix()
                if hashes.get(relative)!=digest:raise ValueError('primary source is unindexed or changed')
        arms[row['variant_id']]=arm
    result=score_pair(contract,arms)
    result['raw_arms']=arms;result['contract_sha256']=file_digest(path)
    result['provenance']={'run_id':lock['run_id'],'primary_default':True,'guidance':contract.get('guidance'),'pricing':lock.get('pricing'),
        'experiment_kind':lock.get('experiment_kind','unspecified'),'is_model_performance_result':lock.get('experiment_kind')=='primary_default_paired'}
    return result


def write_primary_artifacts(output,result):
    """Same result object feeds JSON, long CSV and the readable per-metric table."""
    import csv
    import io
    import json

    from .storage import atomic_json

    records=[]
    for identity,m in result['engineering']['metrics'].items():
        raw=m['arm_raw']
        records.append({'metric_id':identity,'category':'engineering_relative','variant':'paired',
            'meaning':m['meaning'],'raw_formula':m['raw_formula'],'unit':m['unit'],
            'native_raw':raw['pi-native'].get('raw'),'plugin_raw':raw['pi-memweave'].get('raw'),
            'support':{a:raw[a].get('support')for a in ARMS},'score':m['score'],'status':m['status'],
            'normalization_formula':m.get('formula',m['mapping']),'weight':m['weight'],
            'scoring_version':result['scoring_version'],'reason':m.get('reason')})
    for arm in ARMS:
        for identity,m in result['behavior'][arm]['metrics'].items():
            records.append({'metric_id':identity,'category':'high_value_behavior','variant':arm,
                'meaning':m['meaning'],'raw_formula':m['raw_formula'],'unit':m['unit'],
                'native_raw':None,'plugin_raw':None,'support':{'s':m['numerator'],'f':m['failed_opportunities'],
                    'u':m['missing_opportunities']+m['invalid_opportunities'],'n':m['denominator']},
                'score':m['score'],'status':m['status'],'normalization_formula':m['formula'],'weight':m['weight'],
                'scoring_version':result['scoring_version'],'reason':None})
    for row in records:
        row.update(experiment_kind=result.get('provenance',{}).get('experiment_kind','unspecified'),
                   is_model_performance_result=result.get('provenance',{}).get('is_model_performance_result',False))
    atomic_json(output/'primary-scores.json',result)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader()
    for row in records:writer.writerow({k:json.dumps(v,ensure_ascii=False)if isinstance(v,(dict,list))else v for k,v in row.items()})
    (output/'primary-scores.csv').write_text(stream.getvalue())
    def cell(v):return ('missing'if v is None else str(v)).replace('|','\\|').replace('\n',' ')
    lines=['','## 独立工程相对分与高价值行为分','',
        '工程分是 plugin 相对 native 的配对分，相等为 50；行为分分别计算。两类不合成。任务原始奖励另列，业务断言不证明 State 已被采用。','',
        '| 指标 | 类别／臂 | 含义 | 原始公式 | native 原值 | plugin 原值 | s/f/u/n 或两臂分母 | 百分制公式 | 分数 | 权重 | 状态 |',
        '|---|---|---|---|---:|---:|---|---|---:|---:|---|']
    if not result.get('provenance',{}).get('is_model_performance_result',False):
        lines[3:3]=['> 免费接线／评分器验收，不是模型任务成绩；不可作为产品表现对比。','']
    for r in records:
        lines.append('| '+' | '.join(cell(r[k])for k in ['metric_id','variant','meaning','raw_formula','native_raw','plugin_raw','support','normalization_formula','score','weight','status'])+' |')
    lines+=['','| 独立总分 | /100 | 有效权重覆盖 | 条件分（不能代替完整总分） |','|---|---:|---:|---:|']
    totals={'工程（配对相对分）':result['engineering']['total'],**{'高价值行为 '+a:result['behavior'][a]['total']for a in ARMS}}
    for name,m in totals.items():lines.append(f"| {name} | {cell(m['score'])} | {m['evidence_coverage']:.1%} | {cell(m['conditional_score'])} |")
    (output/'primary-report.md').write_text('\n'.join(lines)+'\n')
    return lines
