"""Package views use the complete frozen matrix, never just discovered result rows."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .capability_coverage import capability_coverage, long_qualification_proof
from .fixed35 import aggregate_metric, collection_exception
from .fixed35_report import metric_alias
from .normalized_scores import catalogue
from .storage import atomic_json, file_digest


def validate_case_report(case,contract,report,metric_ids):
    """A case label alone cannot authorize mixing old score definitions."""
    if report.get('case_id')!=case['case_id']:
        raise ValueError('report belongs to a different case')
    if report.get('contract_sha256')!=case['contract_sha256']or report.get('contract_version')!=contract.get('version'):
        raise ValueError('report scoring contract hash/version mismatch')
    for key in ('schema_version','evaluator_version'):
        expected=case.get('report_'+key)
        if expected is None or report.get(key)!=expected:
            raise ValueError('report schema/evaluator version was not frozen or differs')
    if report.get('fixture_scores_included')is not False:
        raise ValueError('fixture results cannot enter a real package score')
    rows=report.get('rows')
    if not isinstance(rows,list)or len(rows)!=2 or {r.get('variant_id')for r in rows}!={'pi-native','pi-memweave'}:
        raise ValueError('report must contain exactly the two paired variants')
    for row in rows:
        if row.get('case_id')!=case['case_id']:
            raise ValueError('variant row belongs to a different case')
        metrics=row.get('normalized_metrics')
        if not isinstance(metrics,list)or len(metrics)!=len(metric_ids)or {m.get('id')for m in metrics}!=metric_ids:
            raise ValueError('report metric schema differs from frozen registry')
        if any(m.get('mapping_version')!=report['evaluator_version']for m in metrics):
            raise ValueError('report mixes metric mapping versions')


def profile_score(rows,registry,profile):
    weights={m['id']:m['weights'].get(profile,0)for m in registry}
    eligible=[r for r in rows if weights[r['metric_id']]>0 and r['status']not in
        {'DESIGN_NA','CONDITIONAL_NO_OPPORTUNITY','DIAGNOSTIC'}]
    design=sum(weights[r['metric_id']]for r in eligible)
    excluded=[]
    for row in eligible:
        if row['status']=='EXCLUDED_UNCOLLECTABLE':
            proofs=row.get('exclusions')or row.get('excluded_cases')
            if proofs:
                values=proofs.values()if isinstance(proofs,dict)else proofs
                for proof in values:
                    # Common-pair exceptions carry the already audited per-arm
                    # reasons, including a scored peer removed for fairness.
                    if 'reasons'in proof:
                        for reason,repairs in zip(proof['reasons'],proof['repair_attempts'],strict=True):
                            collection_exception({'reason':reason,'repair_attempts':repairs})
                    else:collection_exception(proof)
            else:collection_exception(row)
            excluded.append({'metric_id':row['metric_id'],'weight':weights[row['metric_id']],
                'reason':row.get('reason'),'repair_attempts':row.get('repair_attempts'),
                'case_exceptions':proofs})
    excluded_weight=sum(r['weight']for r in excluded)
    eligible=[r for r in eligible if r['status']!='EXCLUDED_UNCOLLECTABLE']
    planned=sum(weights[r['metric_id']]for r in eligible)
    known=[r for r in eligible if r['status']=='SCORED'and r['score']is not None
        and r.get('collection_complete')is not False and r.get('collection_status')!='REPAIR_REQUIRED']
    observed=sum(weights[r['metric_id']]for r in known)
    contribution=sum(weights[r['metric_id']]*r['score']for r in known)
    return {'score':contribution/planned if planned and observed==planned else None,
        'conditional_score':contribution/observed if observed else None,
        'coverage':observed/planned if planned else None,'planned_weight':planned,'observed_weight':observed,
        'design_weight':design,'excluded_weight':excluded_weight,'excluded_metrics':excluded,
        'pre_exclusion_coverage':observed/design if design else None,
        'lower':contribution/planned if planned else None,
        'upper':(contribution+100*(planned-observed))/planned if planned else None,
        'interpretation':'Audited irreparable exceptions leave the effective denominator and remain explicit; ordinary missing evidence blocks point total. Effective-subset coverage does not prove full-design coverage.'}


def profile_with_classes(rows,registry,profile):
    result=profile_score(rows,registry,profile)
    result['classes']={}
    for category in ('engineering','behavior'):
        identities={m['id']for m in registry if m.get('category')==category}
        result['classes'][category]=profile_score([r for r in rows if r['metric_id']in identities],registry,profile)
    definition=catalogue()['profiles'].get(profile)
    if definition and {m['id']for m in registry}=={metric_alias(m['id'])for m in catalogue()['metrics']}:
        from .balanced_profile import balanced_profile
        balanced=balanced_profile(rows,definition)
        return dict(result,legacy_flat_profile=result,**balanced)
    return result


def package_metrics(rows,expected,registry):
    """Two-level macro means; omission is NOT_RUN, explicit exceptions remain visible."""
    identities={(r['case_id'],r['metric_id'],r['arm'])for r in rows}
    if len(identities)!=len(rows):raise ValueError('duplicate case metric arm result')
    wanted={(r['case_id'],r['metric_id'],r['arm'])for r in expected}
    if len(wanted)!=len(expected)or identities-wanted:raise ValueError('result outside unique frozen matrix')
    by_id={key:r for key,r in zip([(r['case_id'],r['metric_id'],r['arm'])for r in rows],rows,strict=True)}
    complete=[];metadata={m['id']:m for m in registry}
    for e in expected:
        row=by_id.get((e['case_id'],e['metric_id'],e['arm']))
        if row is None:
            row=dict(e,status='DESIGN_NA'if e['design_status']=='DESIGN_NA'else'NOT_RUN',score=None)
        elif e['design_status']=='DESIGN_NA'and row['status']!='DESIGN_NA':
            raise ValueError('result contradicts frozen design NA')
        elif row['status']=='DESIGN_NA'and e['design_status']!='DESIGN_NA':
            raise ValueError('result cannot introduce a design NA absent from the frozen matrix')
        if e['design_status']=='DESIGN_UNRESOLVED':
            row=dict(row,observed_unaccepted_score=row.get('score'),score=None,
                status='DESIGN_UNRESOLVED',reason=e['reason'],collection_complete=False)
        if row['status']=='CONDITIONAL_NO_OPPORTUNITY'and row.get('collection_complete')is not True:
            row=dict(row,status='MISSING_EVIDENCE',score=None,collection_complete=False,
                reason='A conditional denominator exemption requires explicit complete collection evidence')
        if row['status']=='EXCLUDED_UNCOLLECTABLE':collection_exception(row)
        complete.append(dict(metadata[e['metric_id']],**{k:v for k,v in row.items()if k!='id'}))
    aggregates=[]
    for arm in ('pi-native','pi-memweave'):
        for metric in registry:
            selected=[r for r in complete if r['arm']==arm and r['metric_id']==metric['id']]
            if not selected:raise ValueError('frozen matrix omits entire metric arm')
            if metric['mapping']=='diagnostic':
                aggregates.append({'arm':arm,'metric_id':metric['id'],'status':'DIAGNOSTIC',
                    'score':None,'meaning':metric['meaning'],'raw_formula':metric['raw_formula'],
                    'raw_rows':selected,'weights':metric['weights']});continue
            mathematical=[r for r in selected if r['status']=='CONDITIONAL_NO_OPPORTUNITY']
            effective=[r for r in selected if r not in mathematical]
            result=aggregate_metric(effective,expected_cases=[r for r in expected if r['arm']==arm and
                r['metric_id']==metric['id']and r['case_id']not in {x['case_id']for x in mathematical}])
            if not effective and mathematical:
                result.update(collection_accepted=all(r.get('collection_complete')is True for r in mathematical))
            aggregates.append(dict(result,arm=arm,metric_id=metric['id'],
                status='SCORED'if result['valid_cases']and not(result['missing']or result['not_run'])else
                    'EXCLUDED_UNCOLLECTABLE'if result['eligible_cases']and result['excluded']==result['eligible_cases']else
                    'CONDITIONAL_NO_OPPORTUNITY'if result['eligible_cases']==0 and mathematical else
                    'DESIGN_NA'if result['eligible_cases']==0 else'MISSING_EVIDENCE',
                mathematical_na=len(mathematical),meaning=metric['meaning'],
                raw_formula=metric['raw_formula'],score_formula=metric['score_formula'],weights=metric['weights']))
    totals={arm:{profile:profile_with_classes([r for r in aggregates if r['arm']==arm],registry,profile)
        for profile in ('plugin_memory','common_product')}for arm in ('pi-native','pi-memweave')}
    case_totals=[];comparisons=[]
    for case in sorted({r['case_id']for r in complete}):
        selected={arm:[r for r in complete if r['case_id']==case and r['arm']==arm]
            for arm in ('pi-native','pi-memweave')}
        common_ids={m['id']for m in registry if m.get('applicability','all')=='all'and m['mapping']!='diagnostic'}
        exclusions={}
        for identity in list(common_ids):
            pair=[next(r for r in selected[a]if r['metric_id']==identity)for a in selected]
            status=next((s for s in ('DESIGN_NA','CONDITIONAL_NO_OPPORTUNITY','EXCLUDED_UNCOLLECTABLE')
                if any(r['status']==s for r in pair)),None)
            if status:
                common_ids.remove(identity)
                exclusions[identity]={'status':status,'reasons':[r.get('reason')for r in pair if r['status']==status],
                    'repair_attempts':[r.get('repair_attempts')for r in pair if r['status']==status]}
        scored_pair={i for i in common_ids if all(any(r['metric_id']==i and r['status']=='SCORED'and r.get('score')is not None
            and r.get('collection_complete')is not False and r.get('collection_status')!='REPAIR_REQUIRED'
            for r in selected[a])for a in selected)}
        comparison={'case_id':case,'eligible_metric_ids':sorted(common_ids),'matched_metric_ids':sorted(scored_pair),
            'excluded_metrics':exclusions,'arms':{}}
        for arm,items in selected.items():
            case_totals.append({'case_id':case,'arm':arm,'profiles':{profile:profile_with_classes(items,registry,profile)
                for profile in ('plugin_memory','common_product')}})
            paired=[dict(r,status='MISSING_EVIDENCE',score=None)if r['metric_id']not in scored_pair else r
                for r in items if r['metric_id']in common_ids]
            comparison['arms'][arm]=profile_score(paired,registry,'common_product')
        comparisons.append(comparison)
    matched_aggregates=[]
    for metric in registry:
        if metric.get('applicability','all')!='all'or metric['mapping']=='diagnostic':continue
        eligible_cases={c['case_id']for c in comparisons if metric['id']in c['eligible_metric_ids']}
        matched_cases={c['case_id']for c in comparisons if metric['id']in c['matched_metric_ids']}
        exclusions={c['case_id']:c['excluded_metrics'][metric['id']]for c in comparisons
            if metric['id']in c['excluded_metrics']}
        empty_status=next((status for status in ('EXCLUDED_UNCOLLECTABLE','CONDITIONAL_NO_OPPORTUNITY')
            if any(e['status']==status for e in exclusions.values())),'DESIGN_NA')
        for arm in ('pi-native','pi-memweave'):
            subset=[r for r in complete if r['arm']==arm and r['metric_id']==metric['id']and r['case_id']in matched_cases]
            specs=[e for e in expected if e['arm']==arm and e['metric_id']==metric['id']and e['case_id']in eligible_cases]
            value=aggregate_metric(subset,expected_cases=specs)
            if not eligible_cases and empty_status=='CONDITIONAL_NO_OPPORTUNITY':
                value['collection_accepted']=True  # exclusions above require explicit complete evidence
            matched_aggregates.append(dict(value,arm=arm,metric_id=metric['id'],
                status=empty_status if not eligible_cases else'SCORED'if eligible_cases==matched_cases else'MISSING_EVIDENCE',
                excluded_cases=exclusions))
    matched_totals={arm:profile_with_classes([r for r in matched_aggregates if r['arm']==arm],registry,'common_product')
        for arm in ('pi-native','pi-memweave')}
    return {'rows':complete,'aggregates':aggregates,'totals':totals,'case_totals':case_totals,'comparisons':comparisons,
        'matched_common_aggregates':matched_aggregates,'matched_common_totals':matched_totals,
        'collection_accepted':all(r.get('collection_complete',True)and r['status']in
            {'SCORED','DESIGN_NA','CONDITIONAL_NO_OPPORTUNITY','DIAGNOSTIC'}for r in complete),
        'expected_cells':len(expected),'observed_cells':len(rows)}


def pack_report(manifest:Path,output:Path):
    frozen=json.loads(manifest.read_text());cases=frozen['cases']
    if len(cases)!=35 or len({c['case_id']for c in cases})!=35:
        raise ValueError('package report requires all 35 frozen distinct cases')
    registry=[dict(m,id=metric_alias(m['id']))for m in catalogue()['metrics']]
    expected=[];rows=[];source_hashes={}
    for case in cases:
        contract_path=Path(case['contract_path'])
        if file_digest(contract_path)!=case['contract_sha256']:raise ValueError('package case contract changed')
        contract=json.loads(contract_path.read_text());matrix={metric_alias(m['metric_id']):m for m in contract['metric_matrix']}
        if set(matrix)!={m['id']for m in registry}:raise ValueError('incomplete case metric contract')
        for arm in ('pi-native','pi-memweave'):
            for metric in registry:
                spec=matrix[metric['id']];native_na=arm=='pi-native'and metric['applicability']=='plugin'
                expected.append({'case_id':case['case_id'],'benchmark':case['benchmark'],'metric_id':metric['id'],
                    'arm':arm,'design_status':'DESIGN_NA'if native_na else spec['design_status'],
                    'reason':'Plugin-only metric in native mode'if native_na else spec.get('reason')})
        if case.get('report_path'):
            path=Path(case['report_path']);source_hashes[str(path)]=file_digest(path)
            if case.get('report_sha256')!=source_hashes[str(path)]:raise ValueError('report artifact hash was not frozen or changed')
            report=json.loads(path.read_text())
            validate_case_report(case,contract,report,{m['id']for m in registry})
            for run in report['rows']:
                for metric in run['normalized_metrics']:
                    rows.append(dict(metric,case_id=case['case_id'],benchmark=case['benchmark'],
                        metric_id=metric['id'],arm=run['variant_id'],
                        status='SCORED'if metric['status']=='scored'else'DIAGNOSTIC'if metric['status']=='diagnostic'else metric['status'],
                        collection_complete=metric.get('collection_status')!='REPAIR_REQUIRED'))
    result=package_metrics(rows,expected,registry)
    result['capability_coverage']=capability_coverage(result['rows'])
    result['long_qualification']=long_qualification_proof(frozen.get('long_qualification'))
    result['package_accepted']=result['collection_accepted']and result['capability_coverage']['complete']and result['long_qualification']['complete']
    result.update(version='fixed35-pack-20261104-v7',manifest_sha256=file_digest(manifest),source_sha256=source_hashes,
        aggregation='valid cases equally within benchmark, then valid benchmark means equally; no test-count weighting')
    output.mkdir(parents=True,exist_ok=False);atomic_json(output/'results.json',result,immutable=True)
    with (output/'metrics.csv').open('w',newline='')as stream:
        columns=['case_id','benchmark','arm','metric_id','meaning','raw','raw_formula','score','score_formula',
            'mapping_version','weights','effective_weights','status','reason','repair_attempts','support_s','support_f','support_u','support_n',
            'receipt_version','session_receipt_counts','execution_receipt_counts']
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader()
        effective={(x['case_id'],x['arm']):{name:p.get('effective_leaf_weights',{})for name,p in x['profiles'].items()}for x in result['case_totals']}
        def weights(row):
            identity=row['metric_id'];identity='S.case_v2.'+identity[4:]if identity.startswith('F35.')else identity
            return {name:values.get(identity,0)for name,values in effective.get((row['case_id'],row['arm']),{}).items()}
        writer.writerows(dict(r,raw=json.dumps(r.get('raw'),ensure_ascii=False),weights=json.dumps(r['weights']),effective_weights=json.dumps(weights(r)),
            repair_attempts=json.dumps(r.get('repair_attempts'),ensure_ascii=False),
            receipt_version=r.get('receipt_evidence',{}).get('receipt_version'),
            session_receipt_counts=json.dumps(r.get('receipt_evidence',{}).get('observed_session_counts')),
            execution_receipt_counts=json.dumps(r.get('receipt_evidence',{}).get('observed_independent_counts')))for r in result['rows'])
    for arm in ('pi-native','pi-memweave'):
        with (output/(arm+'-wide.csv')).open('w',newline='')as stream:
            columns=['case_id',*[m['id']for m in registry if m['mapping']!='diagnostic'],'weighted_total','weighted_coverage',
                'pre_exclusion_coverage','excluded_weight','excluded_metrics']
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
            for case in cases:
                row={'case_id':case['case_id']}
                for item in result['rows']:
                    if item['case_id']==case['case_id']and item['arm']==arm and item['metric_id']in columns:
                        row[item['metric_id']]='-'if item['status']=='DESIGN_NA'else item['score']if item['score']is not None else item['status']
                total=next(x for x in result['case_totals']if x['case_id']==case['case_id']and x['arm']==arm)
                score=total['profiles']['plugin_memory'if arm=='pi-memweave'else'common_product']
                row.update(weighted_total=score['score'],weighted_coverage=score['coverage'],
                    pre_exclusion_coverage=score['pre_exclusion_coverage'],excluded_weight=score['excluded_weight'],
                    excluded_metrics=json.dumps(score['excluded_metrics'],ensure_ascii=False))
                writer.writerow(row)
    with (output/'comparison.csv').open('w',newline='')as stream:
        columns=['case_id','native_score','plugin_score','native_conditional_score','plugin_conditional_score','coverage','matched_metrics','eligible_metrics']
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for pair in result['comparisons']:
            native,plugin=pair['arms']['pi-native'],pair['arms']['pi-memweave']
            writer.writerow({'case_id':pair['case_id'],'native_score':native['score'],'plugin_score':plugin['score'],
                'native_conditional_score':native['conditional_score'],'plugin_conditional_score':plugin['conditional_score'],
                'coverage':native['coverage'],'matched_metrics':len(pair['matched_metric_ids']),
                'eligible_metrics':len(pair['eligible_metric_ids'])})
    with (output/'comparison-metrics.csv').open('w',newline='')as stream:
        common_ids=[m['id']for m in registry if m['applicability']=='all'and m['mapping']!='diagnostic']
        columns=['case_id',*[identity+'.'+arm for identity in common_ids for arm in ('native','plugin')]]
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for pair in result['comparisons']:
            row={'case_id':pair['case_id']}
            for identity in common_ids:
                for label,arm in [('native','pi-native'),('plugin','pi-memweave')]:
                    excluded=pair['excluded_metrics'].get(identity)
                    row[identity+'.'+label]=('-'if excluded and excluded['status']=='DESIGN_NA'else
                        excluded['status']if excluded else
                        'UNMATCHED_EVIDENCE'if identity not in pair['matched_metric_ids']else next(
                            r['score']for r in result['rows']if r['case_id']==pair['case_id']and
                            r['arm']==arm and r['metric_id']==identity))
            writer.writerow(row)
    (output/'report.md').write_text('# 固定35案例整包报告\n\n完整冻结单元格：'+str(result['expected_cells'])+
        '；实际结果单元格：'+str(result['observed_cells'])+'；采集验收：'+str(result['collection_accepted'])+
        '；整包验收：'+str(result['package_accepted'])+'；真实能力组观测：'+str(result['capability_coverage']['observed_group_count'])+'/24；千调用成功案例：'+str(result['long_qualification']['qualified_cases'])+'/5。\n\n`-`仅表示预注册设计不适用；NOT_RUN/缺证据不伪装成0或不适用。明确记录修复失败的采集例外从有效评分分母剔除，仍阻止采集验收；排除前覆盖率、排除权重及原因独立展示。有效子集分数不代表完整设计覆盖。能力组观测不等于行为通过，五个长例须由原件验证成功及去重真实调用数，不以fixture或调用累加代替。公式和原始分母见JSON/metrics.csv。\n')
    return {'output':str(output),'collection_accepted':result['collection_accepted'],'package_accepted':result['package_accepted'],
        'expected_cells':result['expected_cells'],'observed_cells':result['observed_cells']}
