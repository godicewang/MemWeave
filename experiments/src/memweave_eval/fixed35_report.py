"""Raw and 0–100 views on actual admitted episodes; fixtures never enter scores."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .contract_evidence import task_contract_metrics
from .engineering_metrics import episode_phase_seconds, task_engineering_metrics
from .fixed35_mab import grade_mab_trial
from .normalized_scores import normalize_trial_scores
from .storage import atomic_json, file_digest

VERSION='fixed35-score-20261104-v40'


def raw_display(metric):
    data={'raw':metric.get('raw')}
    if metric.get('observed_raw')is not None:data['observed_raw']=metric['observed_raw']
    if any(metric.get('support_'+k)is not None for k in ('s','f','u','n')):
        data.update({k:metric.get('support_'+k)for k in ('s','f','u','n')})
    proof=metric.get('receipt_evidence')or{}
    for key in ['observed_session_counts','observed_independent_counts']:
        if proof.get(key)is not None:data[key]=proof[key]
    return json.dumps(data,ensure_ascii=False)


def mark_checkpoint_collection(metrics,points):
    """A known failure is still zero, but missing mandatory proof needs repair."""
    for metric in metrics:
        point=points.get(metric['id'])
        if isinstance(point,dict)and point.get('collection_complete')is False and metric['status']!='DESIGN_NA':
            metric.update(collection_status='REPAIR_REQUIRED',
                collection_reason='Mandatory checkpoint assertion evidence missing; known failure does not waive collection')


def weighted_profile(metrics,profile,*,allowed_ids=None):
    from .fixed35 import collection_exception
    eligible=[m for m in metrics if m['weights'].get(profile,0)>0 and
        m['status']not in {'DESIGN_NA','not_applicable','CONDITIONAL_NO_OPPORTUNITY'} and
        (allowed_ids is None or m['id']in allowed_ids)]
    design=sum(m['weights'][profile]for m in eligible)
    excluded=[]
    for metric in eligible:
        if metric['status']=='EXCLUDED_UNCOLLECTABLE':
            excluded.append(dict(metric_id=metric['id'],weight=metric['weights'][profile],
                **collection_exception(metric)))
    eligible=[m for m in eligible if m['status']!='EXCLUDED_UNCOLLECTABLE']
    planned=sum(m['weights'][profile]for m in eligible)
    known=[m for m in eligible if m['status']in {'scored','SCORED'}and m['score']is not None]
    weight=sum(m['weights'][profile]for m in known)
    contribution=sum(m['weights'][profile]*m['score']for m in known)
    return {'score':contribution/planned if planned and weight==planned else None,
        'conditional_score':contribution/weight if weight else None,'coverage':weight/planned if planned else None,
        'eligible_weight':planned,'observed_weight':weight,'lower':contribution/planned if planned else None,
        'design_weight':design,'excluded_weight':sum(m['weight']for m in excluded),'excluded_metrics':excluded,
        'pre_exclusion_coverage':weight/design if design else None,
        'upper':(contribution+100*(planned-weight))/planned if planned else None,
        'missing_metric_ids':[m['id']for m in eligible if m not in known],
        'interpretation':'fixed leaf weights; design NA and audited collection exceptions leave the effective denominator; ordinary missing evidence still blocks a full score; pre-exclusion coverage remains explicit'}


def metric_alias(identity):
    if identity.startswith('S.case_v2.'):
        return 'F35.'+identity.removeprefix('S.case_v2.')
    return identity


def qualify_state_statistics(item,identity,state):
    """A proved zero statistical denominator is not a lost observation."""
    positions=state.get('write_model_positions');uniform=state.get('uniformity')or{}
    total=state.get('model_responses_with_usage')
    known_positions=(state.get('source_status')=='ok'and type(total)is int and total>=0
        and isinstance(positions,list)and all(type(p)is int and 0<=p<=total for p in positions)
        and positions==sorted(positions))
    no_internal_gaps=known_positions and len(positions)<2 and uniform.get('intervals')==[] \
        and uniform.get('status')=='insufficient_sample'
    undefined_diagnostic=(identity in {'Q7.mean_interval','Q7.max_interval'}and no_internal_gaps
        or identity in {'Q7.head_calls','Q7.tail_calls'}and no_internal_gaps and not positions)
    if undefined_diagnostic and item.get('status')=='unknown'and item.get('raw')is None:
        item.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY',
            reason='Complete committed journal and model positions prove no internal interval, or no first/last write; undefined diagnostic is not lost evidence or a zero-valued interval',
            statistical_denominator={'committed_batches':len(positions),'internal_intervals':0,
                'whole_no_write_span':total if not positions else None})
        item.pop('collection_status',None)
    if identity=='Q7.fd_density'and item.get('status')=='unknown'and item.get('raw')is None \
            and state.get('source_status')=='ok'and state.get('ratio_status')=='zero_model_responses' \
            and type(state.get('model_responses_with_usage'))is int and state['model_responses_with_usage']==0 \
            and type(state.get('fd_events_added'))is int:
        item.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY',reason='Complete episode evidence proves zero usage-bearing assistant returns; F/D density has a zero denominator',
            statistical_denominator={'model_responses_with_usage':0,'fd_events_added':state['fd_events_added']})
        item.pop('collection_status',None)
    if identity=='Q7.uniformity_cv'and item.get('status')=='insufficient_sample'and state.get('source_status')=='ok' \
            and isinstance(positions,list)and uniform.get('status')=='insufficient_sample':
        item.update(score=None,status='CONDITIONAL_NO_OPPORTUNITY',
            reason='Complete committed journal and model positions prove fewer than two internal gaps, or a zero mean gap; CV is mathematically undefined, not missing collection',
            statistical_denominator={'committed_batches':len(positions),'internal_intervals':len(uniform.get('intervals')or[]),
                'mean_interval':uniform.get('mean_interval')})


def single_report(root:Path,output:Path|None=None,official_outcomes:Path|None=None,*,fixture_control=False):
    admission=json.loads((root/'admission.json').read_text())
    contract=json.loads(Path(admission['contract_path']).read_text())
    if file_digest(Path(admission['contract_path']))!=admission['contract_sha256']:
        raise ValueError('frozen scoring contract changed')
    pair=json.loads((root/'pair-result.json').read_text());rows=[]
    if not isinstance(pair.get('arms'),list)or len(pair['arms'])!=2 or {a.get('arm')for a in pair['arms']}!={'pi-native','pi-memweave'}:
        raise ValueError('exactly one native and one plugin episode required')
    by_arm={a['arm']:a for a in pair['arms']}
    finance_context=None
    if admission.get('campaign'):
        from .fixed35_campaign_config import campaign_config
        cfg=campaign_config(admission)
        finance_context={k:cfg.get(k)for k in ['model','model_version','price_version','currency','price_source','prices_per_million']}
        finance_context.update(cost_basis='peak_reference_estimate_not_account_bill',campaign_sha256=admission['campaign']['sha256'])
    official=json.loads(official_outcomes.read_text())if official_outcomes else None
    if admission['family']=='slop'and (not official or official.get('case_id')!=admission['case_id']or
            official.get('fixture_scores_included')is not False and not(fixture_control and official.get('fixture_scores_included')is True)):
        raise ValueError('matching actual Slop verifier outcomes required; fixture scores rejected')
    for outcome in pair['arms']:
        arm=outcome['arm'];collection=outcome['collection'];trial=Path(outcome['result_path']).parent
        if collection.get('fixture_control')and not fixture_control:
            raise ValueError('fake-provider collection requires explicit fixture-control report')
        agents=[p.parent for p in trial.rglob('request-trace.jsonl')]
        agent=max(agents,key=lambda p:(p/'request-trace.jsonl').stat().st_size)if agents else None
        engineering=task_engineering_metrics(agent)if agent else {}
        engineering.update(collection.get('episode_engineering')or{})
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
        if contract.get('adapter_kind')=='source-protection-v2':
            from .source_protection import grade_protection_trial
            behavior=grade_protection_trial(trial,contract,arm=arm)
            if behavior['fixture_only']and not fixture_control:
                raise ValueError('fake-provider source-protection traces require explicit fixture-control reporting')
        if contract.get('adapter_kind')=='wdm-artifact-v1':
            from .wdm_artifact import grade_wdm_trial
            behavior=grade_wdm_trial(trial,contract)
            if behavior['fixture_only']and not fixture_control:
                raise ValueError('fake-provider WDM artifacts require explicit fixture-control reporting')
        if contract.get('adapter_kind')=='warranty-source-v1':
            from .warranty_gold import grade_trial
            behavior=grade_trial(trial,contract,arm=arm)
            if behavior['fixture_only']and not fixture_control:raise ValueError('Warranty source fixture cannot enter real results')
        if contract.get('adapter_kind')=='wal-source-v1':
            from .wal_gold import grade_trial
            behavior=grade_trial(trial,contract,fixture_control=fixture_control)
        if contract.get('adapter_kind')=='pytest-selected-source-v1':
            from .pytest_source_gold import grade_trial
            behavior=grade_trial(trial,contract,fixture_control=fixture_control)
        if contract.get('adapter_kind')=='ruby-source-v1':
            from .ruby_source import grade_trial
            behavior=grade_trial(trial,contract,fixture_control=fixture_control)
        if contract.get('adapter_kind')=='dispatch-source-v1':
            from .dispatch_gold import grade_trial
            behavior=grade_trial(trial,contract,fixture_control=fixture_control)
        if contract.get('adapter_kind')=='interrupt-final-source-v1':
            from .interrupt_source_gold import grade_capture
            capture_path=Path(admission['browser_evaluator_output'])/trial.name/'final.json'
            behavior=grade_capture(contract,json.loads(capture_path.read_text())if capture_path.is_file()else None)
            if behavior['fixture_only']is True and not fixture_control:
                raise ValueError('Interrupt fixture capture requires explicit fixture-control reporting')
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
        from .pytest_source_gold import attached_source_outcome
        source_outcome=attached_source_outcome(trial,contract,fixture_control=fixture_control)
        reward=behavior['native']['native_outcome']/100 if admission['family']=='mab'else (outcome.get('verifier')or{}).get('rewards',{}).get('reward')
        if admission['family']=='slop':
            from .fixed35_slop import score_channels
            behavior=official['arms'][arm];slop_channels=score_channels(behavior)
            original=slop_channels['original_strict']['score'];reward=original/100 if original is not None else None
            if contract.get('adapter_kind')=='slop-source-business-v1':
                from .slop_source_business import grade_official
                behavior=grade_official(official['arms'][arm],contract,fixture_control=fixture_control)
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
        raw_result=json.loads(Path(outcome['result_path']).read_text())if Path(outcome['result_path']).is_file()else{}
        row.update(finance_usage=collection.get('usage'),
            finance_estimated_usd=collection['estimated_usd']if collection.get('transport_collection_complete')is True else None,
            finance_known_settled_lower_bound_usd=collection['estimated_usd'],phase_seconds=episode_phase_seconds(raw_result),
            finance_context=finance_context,
            cache_input_utilization=collection['cache'].get('input_cache_utilization',{}).get('value'),
            cache_all_tokens_share=collection['cache'].get('all_tokens_cache_share',{}).get('value'))
        if contract.get('adapter_kind')=='wal-source-v1':
            from .wal_gold import checkpoint_rows
            row['wal_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
            row['native_reward']=behavior['original_reward']
            row['behavior_metrics']={'native_metrics':behavior['first_run_native_metrics']or{}}
        if contract.get('adapter_kind')=='pytest-selected-source-v1':
            from .pytest_source_gold import checkpoint_rows
            row['selected_source_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
            row['native_reward']=behavior['original_reward']
            row['behavior_metrics']={'native_metrics':behavior['native_metrics']or{}}
        if contract.get('adapter_kind')=='ruby-source-v1':
            from .ruby_source import checkpoint_rows
            row['ruby_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
            row['native_reward']=behavior['original_reward']
            original=behavior['original_metrics']
            row['behavior_metrics']={'native_metrics':{'passed':original['tests_passed'],'total':original['tests_total'],
                'unit':'Original source CTRF collapsed function rows, not expanded parameter sample count'}if behavior['collection_complete']else{}}
        if contract.get('adapter_kind')=='slop-source-business-v1':
            from .slop_source_business import checkpoint_rows
            row['slop_business_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
        if contract.get('adapter_kind')=='dispatch-source-v1':
            from .dispatch_gold import checkpoint_rows
            row['dispatch_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
            row['native_reward']=behavior['original_reward']
        if source_outcome is not None:
            from .pytest_source_gold import checkpoint_rows
            row['attached_original_source_outcome']=source_outcome
            row.setdefault('derived_behavior_checkpoints',[]).extend(checkpoint_rows(source_outcome))
            previous=(row.get('behavior_metrics')or{}).get('native_metrics')
            native=source_outcome['native_metrics']or{}
            if previous and previous!=native:raise ValueError('two source test count definitions conflict')
            row.setdefault('behavior_metrics',{})['native_metrics']=native
            if source_outcome['original_reward']is not None and source_outcome['original_reward']!=row['native_reward']:
                raise ValueError('source stdout/CTRF reward differs from original trial outcome')
        if admission['family']=='state':row['official_llm_judged_result']=row_official
        if admission['family']=='slop':row['slop_score_channels']=slop_channels
        if contract.get('adapter_kind')=='warranty-source-v1':
            from .warranty_gold import checkpoint_rows
            row['warranty_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
            native=behavior.get('native_source_trace',{})
            row['behavior_metrics']={'native_metrics':{'passed':native['passed'],'total':native['total'],
                'unit':native['unit'],'source_sha256':native['source_sha256']}if native.get('status')=='SCORED'else{}}
        if contract.get('adapter_kind')=='slop-fk-source-v1':
            from .slop_fk_gold import checkpoint_rows, grade_trial
            component=grade_trial(trial,contract,arm=arm,official_outcome=official['arms'][arm])
            if component['fixture_only']and not fixture_control:raise ValueError('Slop FK fixture cannot enter an actual report')
            row['slop_fk_component']=component;row['derived_behavior_checkpoints']=checkpoint_rows(component)
        if contract.get('adapter_kind')=='interrupt-final-source-v1':
            from .interrupt_source_gold import checkpoint_rows
            row['interrupt_component']=behavior;row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
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
            for name in ('state_latest_at_prepare','state_confirmed_receipt_lower_bound','provider_delivery_integrity'):
                if name in delivery:row['contract_metrics'][name]=delivery[name]
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
        costs_complete=all(a['collection'].get('transport_collection_complete')is True for a in pair['arms'])
        fixture_pair=fixture_control and all(a['collection'].get('fixture_control')is True for a in pair['arms'])
        matching_context=bool(finance_context and all(finance_context.get(k)is not None for k in
            ['model','price_version','currency','prices_per_million']))and all(
                a['collection'].get('ledger_path')==cfg['ledger']and
                a['collection'].get('requested_models')==[cfg['model']]for a in pair['arms'])
        row['_normalization_cost_pair']={'native':by_arm['pi-native']['collection']['estimated_usd'],
            'plugin':by_arm['pi-memweave']['collection']['estimated_usd'],
            'compatible':costs_complete and(fixture_pair or matching_context)}
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
            from .fixed35_mab import normalization_points
            proxy=behavior.get('memory',{}).get('three_evictions')or{}
            row.setdefault('behavior_metrics',{})['constraint_retention_proxy']={
                'value':proxy['score']/100 if proxy.get('score')is not None else None,
                'status':'scored'if proxy.get('score')is not None else'unknown',
                'reason':'Observed selected-source three-cut checkpoint conjunction; not internal adoption or causal memory benefit'}
            explicit('S.common.protected_constraints',behavior['derived_action']['score'],
                'MAB typed-action overlay: correct final answer AND exact one-value JSON schema AND correct file value')
            for identity,point in normalization_points(behavior,admission['case_id']).items():
                point=point or{}
                explicit(identity,point.get('score'),point.get('reason')or(
                    'Selected finite typed source relation AND no known incompatible active card AND pre-action timing AND actual first answer-file value; not general free-text memory semantics'
                    if 'C1-'in identity else'controlled checkpoint evidence unavailable'),
                    status='not_applicable'if point.get('status')=='CONDITIONAL_NO_OPPORTUNITY'else None)
            if arm=='pi-memweave'and behavior.get('semantic_rates'):
                rates=behavior['semantic_rates']
                for prefix,names in [('S1.',['timely_write','retention','write_precision','pollution']),
                                     ('S2.',['correction','adoption'])]:
                    for name in names:
                        if name in rates:
                            row['normalization_evidence'][prefix+name]=dict(rates[name],reason=rates[name].get('reason')or rates['scope'])
        elif contract.get('adapter_kind')in {'readonly-before-first-change-v1','readonly-before-first-change-v2'}:
            explicit('S.common.protected_constraints',behavior['common_constraint']['score'])
            point=behavior['plugin_memory']
            explicit('S.case_v2.C3-before-dependent-edit',point['score'],behavior['opportunity_status'],
                status='not_applicable'if point['status']=='CONDITIONAL_NO_OPPORTUNITY'else None)
            for metric,field in [('S1.timely_write','timely_write'),('S1.retention','retention'),
                                 ('S1.write_precision','write_precision'),('S1.pollution','pollution')]:
                row['normalization_evidence'][metric]=dict(behavior[field],
                    reason='Controlled READ_ONLY path records only; see parser coverage and exact case contract')
        elif contract.get('adapter_kind')=='wdm-artifact-v1':
            from .wdm_artifact import checkpoint_rows
            row['derived_behavior_checkpoints']=checkpoint_rows(behavior)
            explicit('S.common.protected_constraints',behavior['checkpoint']['score'],
                'LONG-02 source geometry/NPY/binary output assertions AND; excludes optical quality and minimum-feature DRC')
        elif contract.get('adapter_kind')=='warranty-source-v1':
            common=behavior['common_metric']
            row['normalization_evidence']['S.common.protected_constraints']={
                'value':common['score']/100 if common['score']is not None else None,
                'numerator':common['s'],'denominator':common['n']-common['u'],'unknown':common['u'],
                'status':'scored'if common['score']is not None else'unknown',
                'reason':'Fixed mean over 20 independently ANDed source claim decisions; first submissions and State are separate supplement rows'}
            if behavior.get('semantic_rates')and arm=='pi-memweave':
                for name in ['timely_write','retention','write_precision','pollution']:
                    row['normalization_evidence']['S1.'+name]=dict(behavior['semantic_rates'][name],
                        reason='Restricted source c/b/q claim cards only; no free-text/adoption claim; creation coverage='+
                            json.dumps(behavior['semantic_rates']['controlled_coverage'],ensure_ascii=False))
        elif contract.get('adapter_kind')=='wal-source-v1':
            for identity,point in [('S.common.protected_constraints',behavior['common_checkpoint']),
                ('S.common.process_validation',behavior['checkpoints']['ten-run-validation']),
                ('S.common.dependency_constraints',behavior['checkpoints']['structural'])]:
                explicit(identity,point['score'],
                    'Selected original WAL source assertions; first-run behavior, whole ten-run validation and structural restrictions are separate; no State/adoption inference')
        elif contract.get('adapter_kind')=='pytest-selected-source-v1':
            for identity,point in [('S.common.protected_constraints',behavior['common_checkpoint']),
                ('S.common.process_validation',behavior['whole_protocol']),
                ('S.common.dependency_constraints',behavior['dependency_checkpoint'])]:
                if point is not None:explicit(identity,point['score'],
                    'Exact selected source business cases and matched console/CTRF evidence; no memory-adoption or general cleanroom-origin inference')
        elif contract.get('adapter_kind')=='ruby-source-v1':
            explicit('S.common.protected_constraints',behavior['common_checkpoint']['score'],
                'Six frozen source business groups AND; documented Markdown skips excluded from these strict groups; no State/Task/adoption inference')
            explicit('S.common.process_validation',behavior['process_checkpoint']['score'],
                'Original source gate acceptance with its declared Markdown skip policy AND complete captured source protocol; expanded samples separate')
        elif contract.get('adapter_kind')=='slop-source-business-v1':
            for identity,point,reason in [
                ('S.common.protected_constraints',behavior['common_checkpoint'],
                    'Mean across fixed old-checkpoint regression opportunities; AND of all exact source parameter identities within each checkpoint; no State/adoption inference'),
                ('S.common.process_validation',behavior['process_checkpoint'],
                    'Mean across fixed current-feature opportunities; AND of all source Core/Functionality/Error identities per checkpoint; original strict whole-case result separate')]:
                row['normalization_evidence'][identity]={'value':point['score']/100 if point['score']is not None else None,
                    'numerator':point['numerator'],'denominator':point['denominator']-point['unknown'],
                    'unknown':point['unknown'],'status':'scored'if point['score']is not None else'unknown','reason':reason}
        elif contract.get('adapter_kind')=='dispatch-source-v1':
            explicit('S.common.protected_constraints',behavior['common_checkpoint']['score'],
                'AND of original temporal visibility and current-correction/ledger source cases; not MemWeave memory adoption')
            explicit('S.common.process_validation',behavior['process_checkpoint']['score'],
                'Original full CLI success and valid business JSON AND exact captured command protocol; absent mandatory executable is delivery failure')
        elif contract.get('adapter_kind')=='interrupt-final-source-v1':
            explicit('S.common.protected_constraints',behavior['goal_checkpoint']['score'],
                'Pinned final source DOM constraints only; not temporal State correction or transient-action safety. INT-10 requires active-filter evidence beyond native URL matching.')
        elif contract.get('adapter_kind')=='source-protection-v2':
            explicit('S.common.protected_constraints',behavior['common']['score'],
                'AND of source-gold initial hashes and every complete observed protected-tree boundary; not original task success')
            explicit('S.case_v2.C3-before-dependent-edit',behavior['plugin']['score'],
                'Exact typed active constraint before first persistent change in the frozen selected source projection AND protected invariants; '
                    'other actions are outside this component deadline scope',
                status='not_applicable'if behavior['plugin']['status']=='CONDITIONAL_NO_OPPORTUNITY'else None)
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
        elif contract.get('adapter_kind')=='slop-fk-source-v1':
            # Source components supplement, rather than impersonate, the broad
            # legacy C5/Task families. Their explicit rows have zero extra weight.
            explicit('S.common.protected_constraints',row['slop_fk_component']['checkpoints']['source-business-3']['score'],
                'AND of five pinned independent FK/rollback source tests at checkpoint 3; original strict source outcome remains separate')
        from .state_write_receipts import METRICS, qualify_receipt, receipt_evidence
        if source_outcome is not None:
            explicit('S.common.process_validation',source_outcome['whole_protocol']['score'],
                'Attached fixed original source verifier: every source test AND consistent stdout/CTRF/reward; primary State/protection oracle remains separate')
        write_receipts=receipt_evidence(collection)if arm=='pi-memweave'else{}
        row['state_write_receipt_evidence']=write_receipts
        row['normalization_evidence'].update({identity:write_receipts[tool]for identity,tool in METRICS.items()if tool in write_receipts})
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
            elif item['status'] in {'unknown','partial','invalid'}:
                item['collection_status']='REPAIR_REQUIRED'
            qualify_state_statistics(item,original_id,row['state_metrics'])
            if original_id in METRICS and arm=='pi-memweave':qualify_receipt(item,write_receipts[METRICS[original_id]])
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
        if source_outcome is not None:
            mark_checkpoint_collection(metrics,{'S.common.process_validation':source_outcome['whole_protocol']})
            if not source_outcome['collection_complete']:
                for item in metrics:
                    if item['id']in {'S3.original_reward','S3.partial_pass_rate'}and item['status']!='DESIGN_NA':
                        item.update(collection_status='REPAIR_REQUIRED',collection_reason='Original source test identities, required results or reward are incomplete/inconsistent')
        if admission['family']=='mab':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['derived_action'],
                **{metric_alias(identity):point for identity,point in normalization_points(behavior,admission['case_id']).items()}})
            if arm=='pi-memweave'and behavior.get('semantic_rates'):
                rates=behavior['semantic_rates']
                for item in metrics:
                    if item['id'].startswith(('S1.','S2.'))and item['id'].split('.',1)[1]in rates:
                        item['controlled_coverage']=rates['controlled_coverage'];item['semantic_rate_scope']=rates['scope']
                        if not rates[item['id'].split('.',1)[1]]['collection_complete']and item['status']!='DESIGN_NA':
                            item['collection_status']='REPAIR_REQUIRED'
        if contract.get('adapter_kind')=='source-protection-v2':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['common'],
                'F35.C3-before-dependent-edit':behavior['plugin']})
        if contract.get('adapter_kind')=='wdm-artifact-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['checkpoint']})
        if contract.get('adapter_kind')=='warranty-source-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['common_metric']})
            if behavior.get('semantic_rates')and arm=='pi-memweave':
                for m in metrics:
                    if m['id'].startswith('S1.'):
                        rate=behavior['semantic_rates'][m['id'].removeprefix('S1.')]
                        m['controlled_coverage']=behavior['semantic_rates']['controlled_coverage']
                        if not rate['collection_complete']and m['status']!='DESIGN_NA':m['collection_status']='REPAIR_REQUIRED'
        if contract.get('adapter_kind')=='wal-source-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['common_checkpoint'],
                'S.common.process_validation':behavior['checkpoints']['ten-run-validation'],
                'S.common.dependency_constraints':behavior['checkpoints']['structural']})
            if behavior['contradictory_source_protocol']or behavior['contradictory_suffix']:
                for metric in metrics:
                    if metric['id']in {'S3.original_reward','S3.partial_pass_rate','S.common.protected_constraints',
                            'S.common.process_validation','S.common.dependency_constraints'}and metric['status']!='DESIGN_NA':
                        metric.update(collection_status='REPAIR_REQUIRED',collection_reason='WAL source verifier artifacts contradict the frozen execution order or reward')
        if contract.get('adapter_kind')=='pytest-selected-source-v1':
            mark_checkpoint_collection(metrics,{identity:point for identity,point in [
                ('S.common.protected_constraints',behavior['common_checkpoint']),
                ('S.common.process_validation',behavior['whole_protocol']),
                ('S.common.dependency_constraints',behavior['dependency_checkpoint'])]if point is not None})
            if behavior['contradictory_reward']or behavior['evidence_issues']:
                for metric in metrics:
                    if metric['id']in {'S3.original_reward','S3.partial_pass_rate','S.common.protected_constraints',
                            'S.common.process_validation','S.common.dependency_constraints'}and metric['status']!='DESIGN_NA':
                        metric.update(collection_status='REPAIR_REQUIRED',collection_reason='Selected source test identity/reward evidence requires repair')
        if contract.get('adapter_kind')=='ruby-source-v1':
            for metric in metrics:
                if metric['id']=='S3.partial_pass_rate':
                    metric.update(meaning='Original LONG-05 partial score over collapsed CTRF function rows; expanded parameter samples are a separate diagnostic',
                        raw_formula='original metrics.tests_passed / original metrics.tests_total; original pytest-json-ctrf 0.3.5 collapses parameter IDs',
                        reason='Preserved original source partial; see ruby-source-counts.csv for expanded parameter passed/failed/skipped and unexecuted counts')
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['common_checkpoint'],
                'S.common.process_validation':behavior['process_checkpoint']})
            if not behavior['collection_complete']:
                for metric in metrics:
                    if metric['id']in {'S3.original_reward','S3.partial_pass_rate','S.common.protected_constraints',
                            'S.common.process_validation'}and metric['status']!='DESIGN_NA':
                        metric.update(collection_status='REPAIR_REQUIRED',collection_reason='Ruby source gate, collapsed/expanded identity or original outcome evidence requires repair')
        if contract.get('adapter_kind')=='slop-source-business-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['common_checkpoint'],
                'S.common.process_validation':behavior['process_checkpoint']})
            if not behavior['collection_complete']:
                for metric in metrics:
                    if metric['id']in {'S.common.protected_constraints','S.common.process_validation'}and metric['status']!='DESIGN_NA':
                        metric.update(collection_status='REPAIR_REQUIRED',collection_reason='Frozen Slop source feature/regression inventory evidence requires repair')
        if contract.get('adapter_kind')=='dispatch-source-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['common_checkpoint'],
                'S.common.process_validation':behavior['process_checkpoint']})
            if behavior['evidence_issues']:
                for metric in metrics:
                    if metric['id']in {'S3.original_reward','S.common.protected_constraints','S.common.process_validation'}and metric['status']!='DESIGN_NA':
                        metric.update(collection_status='REPAIR_REQUIRED',collection_reason='Dispatch source branch, command or score evidence requires repair')
        if contract.get('adapter_kind')=='interrupt-final-source-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':behavior['goal_checkpoint']})
        if contract.get('adapter_kind')=='slop-fk-source-v1':
            mark_checkpoint_collection(metrics,{'S.common.protected_constraints':row['slop_fk_component']['checkpoints']['source-business-3']})
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
            and all(r.get('slop_fk_component',{}).get('collection_complete',True)for r in rows)
            and all(r.get('warranty_component',{}).get('collection_complete',True)for r in rows)
            and all(r.get('wal_component',{}).get('collection_complete',True)for r in rows)
            and all(r.get('selected_source_component',{}).get('collection_complete',True)for r in rows)
            and all(r.get('ruby_component',{}).get('collection_complete',True)for r in rows)
            and all(r.get('slop_business_component',{}).get('collection_complete',True)for r in rows)
            and all(r.get('dispatch_component',{}).get('collection_complete',True)for r in rows)
            and not any(m.get('collection_status')=='REPAIR_REQUIRED'for r in rows for m in r['normalized_metrics']),
        'fixture_scores_included':fixture_control,'official_outcomes_sha256':file_digest(official_outcomes)if official_outcomes else None,
        'contract_sha256':admission['contract_sha256'],'contract_version':contract['version']}
    atomic_json(output/'results.json',result,immutable=True)
    columns=['case_id','arm','metric_id','meaning','raw','observed_raw','raw_formula','score','status','score_formula',
        'weight','reason','support_s','support_f','support_u','support_n','score_coverage','lower','upper',
        'collection_status','controlled_coverage','mapping_version','receipt_version','session_receipt_counts','execution_receipt_counts']
    with (output/'metrics.csv').open('w',newline='')as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for row in rows:
            for m in row['normalized_metrics']:
                writer.writerow({'case_id':row['case_id'],'arm':row['variant_id'],'metric_id':m['id'],
                    'meaning':m.get('meaning'), 'raw':json.dumps(m['raw'],ensure_ascii=False),'observed_raw':m.get('observed_raw'),
                    'raw_formula':m.get('raw_formula'),'score':m['score'],'status':m['status'],
                    'score_formula':m.get('score_formula'),'weight':json.dumps(m['weights']), 'reason':m.get('reason'),
                    'score_coverage':m.get('coverage'),'lower':m.get('lower'),'upper':m.get('upper'),
                    'collection_status':m.get('collection_status'),
                    'controlled_coverage':json.dumps(m.get('controlled_coverage'),ensure_ascii=False),
                    'receipt_version':m.get('receipt_evidence',{}).get('receipt_version'),
                    'session_receipt_counts':json.dumps(m.get('receipt_evidence',{}).get('observed_session_counts')),
                    'execution_receipt_counts':json.dumps(m.get('receipt_evidence',{}).get('observed_independent_counts')),
                    **{k:m.get(k)for k in ('support_s','support_f','support_u','support_n','mapping_version')}})
    derived=[dict(m,case_id=row['case_id'],arm=row['variant_id'])for row in rows for m in row.get('derived_behavior_checkpoints',[])]
    if derived:
        with (output/'derived-behavior.csv').open('w',newline='')as stream:
            fields=['case_id','arm','id','meaning','applicability','raw','raw_formula','score','score_formula','status','mapping_version',
                'weights','weight_reason','support_s','support_f','support_u','support_n','evidence_coverage','collection_complete']
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
            writer.writerows(dict(m,score='-'if m['status']=='DESIGN_NA'else m['score'],weights=json.dumps(m['weights']))for m in derived)
    slop_rows=[dict(case_id=row['case_id'],arm=row['variant_id'],channel=name,**value)
        for row in rows for name,value in row.get('slop_score_channels',{}).items()if isinstance(value,dict)]
    if slop_rows:
        with(output/'slop-score-channels.csv').open('w',newline='')as stream:
            columns=['case_id','arm','channel','score','status','source_field','raw_formula','score_formula','reason']
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader();writer.writerows(slop_rows)
    ruby_rows=[]
    for row in rows:
        component=row.get('ruby_component')
        if component:
            original=component['original_metrics'];expanded=component['expanded_source_counts']
            ruby_rows.append({'case_id':row['case_id'],'arm':row['variant_id'],
                'original_ctrf_passed':original.get('tests_passed'),'original_ctrf_total':original.get('tests_total'),
                'original_partial_score':original.get('partial_score'),'original_reward':component['original_reward'],
                **{'observed_expanded_'+k:expanded[k]for k in ['passed','failed','skipped','error','total']},
                'expected_expanded':component['expected_source_cases'],'unexecuted_expanded':component['unexecuted_source_cases'],
                'collection_complete':component['collection_complete'],'fixture_only':component['fixture_only'],
                'formula':'Original partial = original collapsed CTRF passed/total; expanded counters count unique full source parameter IDs, not model requests',
                'interpretation':'Documented Markdown skips are observed skips, never passed assertions; proved Rust health failure leaves all later cases unexecuted; partial capture counters are observed subsets only'})
    if ruby_rows:
        with(output/'ruby-source-counts.csv').open('w',newline='')as stream:
            writer=csv.DictWriter(stream,fieldnames=list(ruby_rows[0]));writer.writeheader();writer.writerows(ruby_rows)
    text=['# 固定案例配对报告',f"\n案例：{admission['case_id']}；评分版本：{VERSION}。原始结果、派生行为与采集验收分别保留。\n",
          '|变体|指标|含义／原公式／百分制公式|原始值|百分制|状态/原因|','|---|---|---|---|---|---|']
    for row in rows:
        for m in row['normalized_metrics']:
            if m['status']=='diagnostic' or m['status']=='DESIGN_NA':continue
            values=[row['variant_id'],m['id'],str(m.get('meaning',''))+' / '+str(m.get('raw_formula',''))+' / '+str(m.get('score_formula','')),
                raw_display(m),str(m['score']),m['status']+': '+str(m.get('reason'))]
            text.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ')for v in values)+' |')
    if slop_rows:
        text.extend(['','## Slop原始严格与派生适用测试口径','',
            'S3.original_reward只使用原始严格口径；派生适用测试单列，不能称原题全过。两列都是本系统固定的程序AND，不冒称Slop官方榜单唯一分数。','',
            '|变体|口径|百分制|状态|来源字段／计算方式|','|---|---|---:|---|---|'])
        for item in slop_rows:
            values=[item['arm'],item['channel'],str(item['score']),item['status'],item['source_field']+' / '+item['raw_formula']]
            text.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ')for v in values)+' |')
    if ruby_rows:
        text.extend(['','## LONG-05原始折叠计数与展开参数样本','',
            '原partial和reward原样保留；展开计数不替代原分。skip不是通过，测试参数不是模型API调用。缺采集时所列仅已观察子集，不表示完整总量。','',
            '|变体|原CTRF passed/total|原partial|展开 passed/failed/skipped/error/total|未执行展开样本|完整采集|','|---|---|---|---|---|---|'])
        for item in ruby_rows:
            values=[item['arm'],str(item['original_ctrf_passed'])+'/'+str(item['original_ctrf_total']),str(item['original_partial_score']),
                '/'.join(str(item['observed_expanded_'+k])for k in ['passed','failed','skipped','error','total']),
                str(item['unexecuted_expanded']),str(item['collection_complete'])]
            text.append('| '+' | '.join(values)+' |')
    if derived:
        text.extend(['','## 派生案例的共同程序检查点','',
            '共同检查点在两臂按同一程序判定；State条目仅插件适用，原生为设计NA。权重0，不替代原170行的State/记忆指标，不并入既有加权总分。fixture控制不作为模型成绩。','',
            '|变体|指标|含义与原公式|原始值|百分制|状态|','|---|---|---|---|---|---|'])
        for item in derived:
            values=[item['arm'],item['id'],item['meaning']+' / '+item['raw_formula']+' / '+item['score_formula'],str(item['raw']),
                '-'if item['status']=='DESIGN_NA'else str(item['score']),item['status']]
            text.append('| '+' | '.join(v.replace('|','\\|').replace('\n',' ')for v in values)+' |')
    (output/'report.md').write_text('\n'.join(text)+'\n')
    return {'complete':True,'collection_accepted':result['collection_accepted'],'report':str(output),'rows':len(rows)}
