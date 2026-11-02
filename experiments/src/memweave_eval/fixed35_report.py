"""Raw and 0–100 views on actual admitted episodes; fixtures never enter scores."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .contract_evidence import task_contract_metrics
from .engineering_metrics import task_engineering_metrics
from .fixed35_mab import grade_mab_trial
from .normalized_scores import normalize_trial_scores
from .storage import atomic_json, file_digest

VERSION='fixed35-score-20261102-v1'


def weighted_profile(metrics,profile,*,allowed_ids=None):
    eligible=[m for m in metrics if m['weights'].get(profile,0)>0 and
        m['status']not in {'DESIGN_NA','not_applicable','CONDITIONAL_NO_OPPORTUNITY'} and
        (allowed_ids is None or m['id']in allowed_ids)]
    planned=sum(m['weights'][profile]for m in eligible)
    known=[m for m in eligible if m['status']in {'scored','SCORED'}and m['score']is not None]
    weight=sum(m['weights'][profile]for m in known)
    contribution=sum(m['weights'][profile]*m['score']for m in known)
    return {'score':contribution/planned if planned and weight==planned else None,
        'conditional_score':contribution/weight if weight else None,'coverage':weight/planned if planned else None,
        'eligible_weight':planned,'observed_weight':weight,'lower':contribution/planned if planned else None,
        'upper':(contribution+100*(planned-weight))/planned if planned else None,
        'missing_metric_ids':[m['id']for m in eligible if m not in known],
        'interpretation':'fixed leaf weights; design NA removed; incomplete evidence is not a zero or a full score'}


def metric_alias(identity):
    if identity.startswith('S.case_v2.'):
        return 'F35.'+identity.removeprefix('S.case_v2.')
    return identity


def single_report(root:Path,output:Path|None=None):
    admission=json.loads((root/'admission.json').read_text())
    contract=json.loads(Path(admission['contract_path']).read_text())
    if file_digest(Path(admission['contract_path']))!=admission['contract_sha256']:
        raise ValueError('frozen scoring contract changed')
    pair=json.loads((root/'pair-result.json').read_text());rows=[]
    for outcome in pair['arms']:
        arm=outcome['arm'];collection=outcome['collection'];trial=Path(outcome['result_path']).parent
        agents=[p.parent for p in trial.rglob('request-trace.jsonl')]
        agent=max(agents,key=lambda p:(p/'request-trace.jsonl').stat().st_size)if agents else None
        engineering=task_engineering_metrics(agent)if agent else {}
        engineering['tools']={name:dict(value,error_rate=value['errors']/value['attempts']
            if value['attempts']and not value['unknown_results']else None)for name,value in collection['tools'].items()}
        behavior=grade_mab_trial(trial,contract,arm=arm)if admission['family']=='mab'else None
        if contract.get('adapter_kind')=='readonly-before-first-change-v1':
            from .fixed35_business import grade_readonly
            behavior=grade_readonly(trial,contract,arm=arm)
        reward=behavior['native']['native_outcome']/100 if admission['family']=='mab'else (outcome.get('verifier')or{}).get('rewards',{}).get('reward')
        row={'case_id':admission['case_id'],'task_id':admission['case_id'],'benchmark':admission['benchmark'],
            'variant_id':arm,'execution_status':'scored','native_reward':reward,
            'state_metrics':collection['state_metrics'],'engineering_metrics':engineering,
            'contract_metrics':task_contract_metrics(agent,enabled=arm=='pi-memweave')if agent else {},
            'finance':{'cache_metrics':collection['cache']},'normalization_evidence':{},
            'collection':collection,'original_exception':outcome['exception'],'case_behavior':behavior}
        row['_normalization_cost_pair']={'native':pair['arms'][0]['collection']['estimated_usd'],
            'plugin':pair['arms'][1]['collection']['estimated_usd'],
            'compatible':all(a['collection']['collection_complete']for a in pair['arms'])}
        def explicit(identity,score,reason=None,row=row):
            row['normalization_evidence'][identity]={'value':None if score is None else score/100,
                'status':'unknown'if score is None else 'scored','reason':reason}
        if admission['family']=='mab':
            explicit('S.common.protected_constraints',behavior['derived_action']['score'],
                'MAB typed-action overlay: correct final answer AND exact one-value JSON schema AND correct file value')
            memory=behavior.get('memory',{})
            for old,field in [('S.case_v2.C5-correct-before-action','correction'),
                              ('S.case_v2.C4-three-window-checkpoints','three_evictions')]:
                point=memory.get(field)or{}
                explicit(old,point.get('score'),point.get('reason')or'controlled checkpoint evidence unavailable')
        elif contract.get('adapter_kind')=='readonly-before-first-change-v1':
            explicit('S.common.protected_constraints',behavior['common_constraint']['score'])
            explicit('S.case_v2.C3-before-dependent-edit',behavior['plugin_memory']['score'])
            for metric,field in [('S1.timely_write','timely_write'),('S1.retention','retention'),
                                 ('S1.write_precision','write_precision'),('S1.pollution','pollution')]:
                row['normalization_evidence'][metric]=dict(behavior[field],
                    reason='Controlled READ_ONLY path records only; see parser coverage and exact case contract')
        normalized=normalize_trial_scores(row)
        metrics=[]
        assigned={m['metric_id']:m for m in contract['metric_matrix']}
        for item in normalized['metrics']:
            original_id=item['id'];spec=assigned[original_id]
            item['id']=metric_alias(original_id);item['legacy_registry_id']=original_id
            if spec['design_status']=='DESIGN_NA':
                item.update(score=None,status='DESIGN_NA',reason=spec['reason'])
            elif item['status']=='not_applicable':
                item.update(status='CONDITIONAL_NO_OPPORTUNITY',design_reason=spec.get('conditional_na'))
            elif item['status'] in {'unknown','partial'}:
                item['collection_status']='REPAIR_REQUIRED'
            item['opportunity_ids']=spec['opportunity_ids'];item['mapping_version']=VERSION
            metrics.append(item)
        row['normalized_metrics']=metrics
        row['profiles']={name:weighted_profile(metrics,name)for name in ('common_product','plugin_memory')}
        if arm=='pi-native':
            row['profiles']['plugin_memory']={'score':None,'status':'DESIGN_NA','reason':'Native Pi has no plugin memory profile'}
        rows.append(row)
    common={m['id']for m in rows[0]['normalized_metrics']if m['status']in {'scored','SCORED'}and m['applicability']=='all'}
    common&={m['id']for m in rows[1]['normalized_metrics']if m['status']in {'scored','SCORED'}and m['applicability']=='all'}
    for row in rows:
        row['matched_common_profile']=weighted_profile(row['normalized_metrics'],'common_product',allowed_ids=common)
    output=output or root/'reports';output.mkdir(exist_ok=False)
    result={'schema_version':3,'evaluator_version':VERSION,'case_id':admission['case_id'],
        'rows':rows,'collection_accepted':all(r['collection']['collection_complete'] for r in rows)
            and not any(m.get('collection_status')=='REPAIR_REQUIRED'for r in rows for m in r['normalized_metrics']),
        'fixture_scores_included':False,'contract_sha256':admission['contract_sha256']}
    atomic_json(output/'results.json',result,immutable=True)
    columns=['case_id','arm','metric_id','meaning','raw','raw_formula','score','status','score_formula',
        'weight','reason','support_s','support_f','support_u','support_n','mapping_version']
    with (output/'metrics.csv').open('w',newline='')as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for row in rows:
            for m in row['normalized_metrics']:
                writer.writerow({'case_id':row['case_id'],'arm':row['variant_id'],'metric_id':m['id'],
                    'meaning':m.get('meaning'), 'raw':json.dumps(m['raw'],ensure_ascii=False),
                    'raw_formula':m.get('raw_formula'),'score':m['score'],'status':m['status'],
                    'score_formula':m.get('score_formula'),'weight':json.dumps(m['weights']), 'reason':m.get('reason'),
                    **{k:m.get(k)for k in ('support_s','support_f','support_u','support_n','mapping_version')}})
    text=['# 固定案例配对报告',f"\n案例：{admission['case_id']}；评分版本：{VERSION}。原始结果、派生行为与采集验收分别保留。\n",
          '|变体|指标|含义与原公式|原始值|百分制|状态/原因|','|---|---|---|---|---|---|']
    for row in rows:
        for m in row['normalized_metrics']:
            if m['status']=='diagnostic' or m['status']=='DESIGN_NA':continue
            values=[row['variant_id'],m['id'],str(m.get('meaning',''))+' / '+str(m.get('raw_formula','')),
                json.dumps(m['raw'],ensure_ascii=False),str(m['score']),m['status']+': '+str(m.get('reason'))]
            text.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ')for v in values)+' |')
    (output/'report.md').write_text('\n'.join(text)+'\n')
    return {'complete':True,'collection_accepted':result['collection_accepted'],'report':str(output),'rows':len(rows)}
