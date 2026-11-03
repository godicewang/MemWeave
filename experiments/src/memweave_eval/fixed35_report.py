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

VERSION='fixed35-score-20261103-v9'


def mark_checkpoint_collection(metrics,points):
    """A known failure is still zero, but missing mandatory proof needs repair."""
    for metric in metrics:
        point=points.get(metric['id'])
        if isinstance(point,dict)and point.get('collection_complete')is False and metric['status']!='DESIGN_NA':
            metric.update(collection_status='REPAIR_REQUIRED',
                collection_reason='Mandatory checkpoint assertion evidence missing; known failure does not waive collection')


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


def single_report(root:Path,output:Path|None=None,official_outcomes:Path|None=None,*,fixture_control=False):
    admission=json.loads((root/'admission.json').read_text())
    contract=json.loads(Path(admission['contract_path']).read_text())
    if file_digest(Path(admission['contract_path']))!=admission['contract_sha256']:
        raise ValueError('frozen scoring contract changed')
    pair=json.loads((root/'pair-result.json').read_text());rows=[]
    official=json.loads(official_outcomes.read_text())if official_outcomes else None
    if admission['family']=='slop'and (not official or official.get('case_id')!=admission['case_id']or official.get('fixture_scores_included')is not False):
        raise ValueError('matching actual Slop verifier outcomes required; fixture scores rejected')
    for outcome in pair['arms']:
        arm=outcome['arm'];collection=outcome['collection'];trial=Path(outcome['result_path']).parent
        if collection.get('fixture_control')and not fixture_control:
            raise ValueError('fake-provider collection requires explicit fixture-control report')
        agents=[p.parent for p in trial.rglob('request-trace.jsonl')]
        agent=max(agents,key=lambda p:(p/'request-trace.jsonl').stat().st_size)if agents else None
        engineering=task_engineering_metrics(agent)if agent else {}
        delivery=collection.get('delivery_metrics')
        if delivery:
            engineering.update(delivery['engineering'])
            engineering.update(usage_confirmed_attempts=collection['actor_http_attempts']-len([
                i for i in collection['unsettled_request_ids']if i in delivery['request_ids']]),
                unknown_charge_attempts=len([i for i in collection['unsettled_request_ids']if i in delivery['request_ids']]))
        engineering['tools']={name:dict(value,error_rate=value['errors']/value['attempts']
            if value['attempts']and not value['unknown_results']else None)for name,value in collection['tools'].items()}
        behavior=grade_mab_trial(trial,contract,arm=arm)if admission['family']=='mab'else None
        if contract.get('adapter_kind')in {'readonly-before-first-change-v1','readonly-before-first-change-v2'}:
            from .fixed35_business import grade_readonly
            behavior=grade_readonly(trial,contract,arm=arm)
        if contract.get('adapter_kind')=='state-business-v1':
            from .fixed35_state_behavior import grade_state_trial
            private=Path(admission['agent_options']['state_evaluator_output'])/trial.name
            behavior=grade_state_trial(private,contract['state_business'],arm=arm)
        if contract.get('adapter_kind')=='state-equal-authority-v1':
            from .state_conflict import grade_conflict_trial
            private=Path(admission['agent_options']['state_evaluator_output'])/trial.name
            behavior=grade_conflict_trial(trial,private,contract['state_business'],arm=arm)
            if behavior.get('fixture_only')and not fixture_control:
                raise ValueError('fake-provider overlay evidence requires explicit fixture-control report; never an actual score')
        if contract.get('adapter_kind')=='switch-remembered-contract-v2':
            from .fixed35_switch_replay import grade_switch_probe_trial
            behavior=grade_switch_probe_trial(trial,contract,arm=arm)
            if behavior['fixture_only']and not fixture_control:
                raise ValueError('fake-provider Switch probes require explicit fixture-control report; never an actual score')
        reward=behavior['native']['native_outcome']/100 if admission['family']=='mab'else (outcome.get('verifier')or{}).get('rewards',{}).get('reward')
        if admission['family']=='slop':
            behavior=official['arms'][arm];reward=behavior['score']/100 if behavior['score']is not None else None
        row_official=None
        if admission['family']=='state'and outcome.get('host_official_score')and 'official_status'in outcome['host_official_score']:
            status=outcome['host_official_score'];score_path=Path(status['scored_file'])
            if status['official_status'].get('status')=='OK'and score_path.is_file()and file_digest(score_path)==status['scored_sha256']:
                state_official=json.loads(score_path.read_text());value=state_official.get('task_completion_pass')
                reward=int(value)if type(value)is bool else value if value in (0,1)else None
                row_official=state_official
            else:row_official=None
        row={'case_id':admission['case_id'],'task_id':admission['case_id'],'benchmark':admission['benchmark'],
            'variant_id':arm,'execution_status':'scored','native_reward':reward,
            'state_metrics':collection['state_metrics'],'engineering_metrics':engineering,
            'contract_metrics':task_contract_metrics(agent,enabled=arm=='pi-memweave')if agent else {},
            'finance':{'cache_metrics':collection['cache']},'normalization_evidence':{},
            'collection':collection,'original_exception':outcome['exception'],'case_behavior':behavior}
        if admission['family']=='state':row['official_llm_judged_result']=row_official
        if contract.get('adapter_kind')=='switch-remembered-contract-v2'and arm=='pi-memweave':
            row['behavior_metrics']=row['task_behavior']=behavior['task_behavior']
        if contract.get('adapter_kind')=='switch-remembered-contract-v2':
            row.setdefault('behavior_metrics',{})['native_metrics']=behavior['source_final']['native_metrics']
        if contract.get('adapter_kind')=='state-equal-authority-v1':
            from .state_conflict import common_checkpoint_rows
            row['derived_behavior_checkpoints']=common_checkpoint_rows(behavior,arm=arm)
        if contract.get('task_behavior')and arm=='pi-memweave':
            from .fixed35_task_behavior import grade_task_trial
            if contract['task_behavior'].get('fixture_only')is not False:
                raise ValueError('actual-case Task contract must explicitly reject fixture scores')
            row['behavior_metrics']=grade_task_trial(trial,contract['task_behavior'])
            row['task_behavior']=row['behavior_metrics']
        if delivery:
            for name in ('state_latest_at_prepare','provider_delivery_integrity'):
                row['contract_metrics'][name]=delivery[name]
        if contract.get('reference_contract')=='known-complete-text-v1':
            row['contract_metrics']['reference_integrity']=collection.get('known_reference_integrity',{})
        if contract.get('window_contract',{}).get('kind')=='uncut-plain-text-v1':
            from .fixed35_window import grade_small_windows
            window=contract['window_contract']
            row['contract_metrics']['window_integrity']=grade_small_windows(trial,
                collection['delivery_metrics']['request_ids'],recent_turns=window['recent_turns'],
                enabled=arm=='pi-memweave',max_source_bytes=window.get('max_source_bytes',100000))
        if contract.get('window_contract',{}).get('kind')in {'native-identity-plain-text-v1','native-identity-plain-text-v2'}:
            from .fixed35_identity_window import grade_identity_windows
            window=contract['window_contract']
            row['contract_metrics']['window_integrity']=grade_identity_windows(trial,
                collection['delivery_metrics']['request_ids'],recent_turns=window['recent_turns'],
                evict_turns=window['evict_turns'],enabled=arm=='pi-memweave',
                max_source_bytes=window.get('max_source_bytes',4000000))
        row['_normalization_cost_pair']={'native':pair['arms'][0]['collection']['estimated_usd'],
            'plugin':pair['arms'][1]['collection']['estimated_usd'],
            'compatible':all(a['collection']['collection_complete']for a in pair['arms'])}
        def explicit(identity,score,reason=None,row=row,status=None):
            row['normalization_evidence'][identity]={'value':None if score is None else score/100,
                'status':status or('unknown'if score is None else 'scored'),'reason':reason}
        if contract.get('rule_gold'):
            from .fixed35_rule import grade_rule_trial
            gold=contract['rule_gold'];template=Path(gold['path'])
            if file_digest(template)!=gold['sha256']:
                raise ValueError('independent frozen Rule gold changed')
            proof=grade_rule_trial(trial,template.read_text(),gold['variables'],
                collection['delivery_metrics']['request_ids'],enabled=arm=='pi-memweave')
            row['contract_metrics']['rule_integrity']=proof
            row['normalization_evidence']['Q3.rule_integrity']=proof
        if admission['family']=='mab':
            explicit('S.common.protected_constraints',behavior['derived_action']['score'],
                'MAB typed-action overlay: correct final answer AND exact one-value JSON schema AND correct file value')
            memory=behavior.get('memory',{})
            for old,field in [('S.case_v2.C5-correct-before-action','correction'),
                              ('S.case_v2.C4-three-window-checkpoints','three_evictions')]:
                point=memory.get(field)or{}
                explicit(old,point.get('score'),point.get('reason')or'controlled checkpoint evidence unavailable')
        elif contract.get('adapter_kind')in {'readonly-before-first-change-v1','readonly-before-first-change-v2'}:
            explicit('S.common.protected_constraints',behavior['common_constraint']['score'])
            point=behavior['plugin_memory']
            explicit('S.case_v2.C3-before-dependent-edit',point['score'],behavior['opportunity_status'],
                status='not_applicable'if point['status']=='CONDITIONAL_NO_OPPORTUNITY'else None)
            for metric,field in [('S1.timely_write','timely_write'),('S1.retention','retention'),
                                 ('S1.write_precision','write_precision'),('S1.pollution','pollution')]:
                row['normalization_evidence'][metric]=dict(behavior[field],
                    reason='Controlled READ_ONLY path records only; see parser coverage and exact case contract')
        elif contract.get('adapter_kind')=='state-business-v1':
            explicit('S.common.protected_constraints',behavior['score'],
                behavior.get('reason')or'AND of pinned state fields, protected domain records and case-specific behavior assertions; official LLM judge is separate')
            if admission['case_id']in {'INT-01','INT-02'}:
                explicit('S.case_v2.C8-missing',behavior['score'],
                    'Finite English clarification parser, actual domain actions and all protected-state checks; not a general semantic classifier')
        elif contract.get('adapter_kind')=='state-equal-authority-v1':
            explicit('S.common.protected_constraints',behavior['followthrough']['score'],
                'Source required cancellation fields AND original lookup ordering AND all other fields at every observed domain boundary')
        elif contract.get('adapter_kind')=='switch-remembered-contract-v2':
            row['normalization_evidence']['S.common.protected_constraints']=behavior['common_checkpoint_metric']
            if arm=='pi-memweave':row['normalization_evidence'].update(behavior['task_checkpoint_metrics'])
        normalized=normalize_trial_scores(row)
        metrics=[]
        assigned={m['metric_id']:m for m in contract['metric_matrix']}
        for item in normalized['metrics']:
            original_id=item['id'];spec=assigned[original_id]
            item['id']=metric_alias(original_id);item['legacy_registry_id']=original_id
            if spec['design_status']=='DESIGN_NA'or arm=='pi-native'and item['applicability']=='plugin':
                item.update(score=None,status='DESIGN_NA',reason='Plugin-only metric in native mode'
                    if arm=='pi-native'and item['applicability']=='plugin'else spec['reason'])
            elif spec['design_status']=='DESIGN_UNRESOLVED':
                item.update(observed_unaccepted_score=item.get('score'),score=None,status='DESIGN_UNRESOLVED',
                    reason=spec['reason'],collection_status='REPAIR_REQUIRED')
            elif original_id.startswith('Q1.tool.')and '.duration.'in original_id and \
                    collection.get('execution_boundary_collection',{}).get('complete')is True and \
                    collection['tools'].get(original_id.split('.')[2],{}).get('executions')==0:
                item.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY',
                    reason='complete independent execution log proves this tool execute() never started; no execution latency denominator')
            elif item['status']=='not_applicable':
                item.update(status='CONDITIONAL_NO_OPPORTUNITY',design_reason=spec.get('conditional_na'))
            elif item['status'] in {'unknown','partial'}:
                item['collection_status']='REPAIR_REQUIRED'
            if contract.get('adapter_kind')in {'readonly-before-first-change-v1','readonly-before-first-change-v2'}and not behavior['boundary_coverage']['complete']and original_id in {
                    'S.common.protected_constraints','S.case_v2.C3-before-dependent-edit'}and item['status']!='DESIGN_NA':
                item['collection_status']='REPAIR_REQUIRED'
            if contract.get('adapter_kind')=='state-business-v1'and not behavior['collection_complete']and original_id in {
                    'S.common.protected_constraints','S.case_v2.C8-missing'}and item['status']!='DESIGN_NA':
                item['collection_status']='REPAIR_REQUIRED'
            if contract.get('adapter_kind')=='state-equal-authority-v1'and not behavior['collection_complete']and original_id in {
                    'S.common.protected_constraints','S.case_v2.C8-conflict'}and item['status']!='DESIGN_NA':
                item['collection_status']='REPAIR_REQUIRED'
            item['opportunity_ids']=spec['opportunity_ids'];item['mapping_version']=VERSION
            metrics.append(item)
        if admission['family']=='mab':
            memory=behavior.get('memory')or{}
            mark_checkpoint_collection(metrics,{
                'S.common.protected_constraints':behavior['derived_action'],
                'F35.C5-correct-before-action':memory.get('correction'),
                'F35.C4-three-window-checkpoints':memory.get('three_evictions')})
        if contract.get('adapter_kind')=='switch-remembered-contract-v2'and not behavior['collection_complete']:
            for metric in metrics:
                if (metric['id']=='S.common.protected_constraints'or metric['id'].startswith(('S4.','F35.T')) )and metric['status']!='DESIGN_NA':
                    metric.update(collection_status='REPAIR_REQUIRED',collection_reason='Selected Switch action/Task checkpoint proof incomplete')
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
            and (official is None or all(p['collection_complete']for p in official['arms'].values()))
            and not any(m.get('collection_status')=='REPAIR_REQUIRED'for r in rows for m in r['normalized_metrics']),
        'fixture_scores_included':fixture_control,'official_outcomes_sha256':file_digest(official_outcomes)if official_outcomes else None,
        'contract_sha256':admission['contract_sha256'],'contract_version':contract['version']}
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
    derived=[dict(m,case_id=row['case_id'],arm=row['variant_id'])for row in rows for m in row.get('derived_behavior_checkpoints',[])]
    if derived:
        with (output/'derived-behavior.csv').open('w',newline='')as stream:
            fields=['case_id','arm','id','meaning','applicability','raw','raw_formula','score','score_formula','status','mapping_version',
                'weights','weight_reason','support_s','support_f','support_u','support_n','evidence_coverage','collection_complete']
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
            writer.writerows(dict(m,score='-'if m['status']=='DESIGN_NA'else m['score'],weights=json.dumps(m['weights']))for m in derived)
    text=['# 固定案例配对报告',f"\n案例：{admission['case_id']}；评分版本：{VERSION}。原始结果、派生行为与采集验收分别保留。\n",
          '|变体|指标|含义与原公式|原始值|百分制|状态/原因|','|---|---|---|---|---|---|']
    for row in rows:
        for m in row['normalized_metrics']:
            if m['status']=='diagnostic' or m['status']=='DESIGN_NA':continue
            values=[row['variant_id'],m['id'],str(m.get('meaning',''))+' / '+str(m.get('raw_formula','')),
                json.dumps(m['raw'],ensure_ascii=False),str(m['score']),m['status']+': '+str(m.get('reason'))]
            text.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ')for v in values)+' |')
    if derived:
        text.extend(['','## 派生案例的共同程序检查点','',
            '共同检查点在两臂按同一程序判定；State条目仅插件适用，原生为设计NA。权重0，不替代原170行的State/记忆指标，不并入既有加权总分。fixture控制不作为模型成绩。','',
            '|变体|指标|含义与原公式|原始值|百分制|状态|','|---|---|---|---|---|---|'])
        for item in derived:
            values=[item['arm'],item['id'],item['meaning']+' / '+item['raw_formula'],str(item['raw']),
                '-'if item['status']=='DESIGN_NA'else str(item['score']),item['status']]
            text.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ')for v in values)+' |')
    (output/'report.md').write_text('\n'.join(text)+'\n')
    return {'complete':True,'collection_accepted':result['collection_accepted'],'report':str(output),'rows':len(rows)}
