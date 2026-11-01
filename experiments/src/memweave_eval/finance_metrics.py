"""Provider-evidenced cache ratios and matched, peak-estimated paired costs."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def ratio(numerator, denominator, *, zero='zero_denominator'):
    if numerator is None or denominator is None:
        return {'value':None,'status':'unknown','reason':'missing_value'}
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (numerator,denominator)):
        return {'value':None,'status':'invalid','reason':'invalid_negative_or_nonfinite_value'}
    if denominator==0:
        return {'value':None,'status':'not_applicable','reason':zero}
    return {'value':numerator/denominator,'status':'scored','reason':None}


def cache_metrics(usage):
    i,h,o=(usage.get(k) for k in ('input_tokens','cache_tokens','output_tokens'))
    invalid=bool(usage.get('_invalid_member')) or any(v is not None and (type(v) is not int or v<0)for v in (i,h,o))
    invalid |= type(i) is int and type(h) is int and h>i
    if invalid:
        bad={'value':None,'status':'invalid','reason':'invalid_token_counts_or_cache_exceeds_input'}
        return {'input_cache_utilization':dict(bad),'all_tokens_cache_share':dict(bad)}
    return {'input_cache_utilization':ratio(h,i),
            'all_tokens_cache_share':ratio(h,i+o if i is not None and o is not None else None)}


def aggregate_cache(usages):
    usages=list(usages)
    if not usages:
        na={'value':None,'status':'not_applicable','reason':'no_samples'}
        return {'input_cache_utilization':dict(na),'all_tokens_cache_share':dict(na),'samples':0}
    counts={k:sum(u[k] for u in usages)if all(type(u.get(k)) is int for u in usages)else None
            for k in ('input_tokens','cache_tokens','output_tokens')}
    invalid=any(cache_metrics(u)['input_cache_utilization']['status']=='invalid'for u in usages)
    result=cache_metrics(counts)
    if invalid:
        result={k:{'value':None,'status':'invalid','reason':'invalid_member'}for k in result}
    result.update(samples=len(usages),totals=counts,aggregation='sum_tokens_then_divide')
    return result


def context_from_lock(lock):
    config=lock.get('config',lock.get('spec',{}))
    model=config.get('model',lock.get('model',{}))
    pricing=dict(lock.get('pricing',{}))
    if 'per_million_tokens'not in pricing and all(k in pricing for k in ('input_miss','cache_hit','output')):
        pricing['per_million_tokens']={'input':pricing['input_miss'],'cache_read':pricing['cache_hit'],'output':pricing['output']}
    price_fields={k:pricing.get(k)for k in ('source','currency','per_million_tokens','catalog_model_version')}
    price=(hashlib.sha256(json.dumps(price_fields,sort_keys=True).encode()).hexdigest()
           if price_fields['source'] and price_fields['currency'] and price_fields['per_million_tokens'] else None)
    return {'model':f"{model.get('provider')}/{model.get('id')}" if model.get('provider') and model.get('id') else None,
            'price':price,'currency':pricing.get('currency'), 'price_source':pricing.get('source'),
            'cost_basis':'peak_reference_estimate_not_account_bill'}


def transport_finance(agent: Path):
    path=agent/'request-trace.jsonl'
    if not path.is_file():
        return None
    events=[]
    try:
        events=[json.loads(line)for line in path.read_text().splitlines()]
    except (ValueError,OSError):
        return None
    attempts={e.get('request_id')for e in events if e.get('event')=='http_attempt'}
    if not attempts:
        return None
    ends={e.get('request_id'):e for e in events if e.get('event')=='request_end'}
    settled={e.get('request_id'):e.get('charge_usd')for e in events if e.get('event')=='budget_settled'}
    rows=[]
    for identity in attempts:
        usage=(ends.get(identity)or{}).get('usage')or{}
        rows.append({'input_tokens':usage.get('input'),'cache_tokens':usage.get('cache_hit'),
                     'output_tokens':usage.get('output')})
    totals={k:sum(r[k]for r in rows)if all(type(r.get(k))is int for r in rows)else None
            for k in ('input_tokens','cache_tokens','output_tokens')}
    metrics=aggregate_cache(rows)
    if metrics['input_cache_utilization']['status']=='invalid':
        totals['_invalid_member']=True
    cost=sum(settled[i]for i in attempts)if all(i in settled and ends.get(i,{}).get('settled')is True
        and type(settled[i])in(int,float)and math.isfinite(settled[i])and settled[i]>=0 for i in attempts)else None
    return {'usage':totals,'cache_metrics':metrics,'estimated_usd':cost,'http_attempts':len(attempts),
            'cache_reported_attempts':sum(type(r['cache_tokens'])is int for r in rows),
            'source':'original_provider_HTTP_usage','unknown_charge_attempts':sum(i not in settled for i in attempts)}


def attach_finance(row, context, agent=None):
    observed=transport_finance(agent)if agent is not None else None
    if observed is None:
        usage=row.get('usage')or{}
        tokens={'input_tokens':usage.get('input_tokens'),'output_tokens':usage.get('output_tokens'),
                'cache_tokens':usage.get('cache_tokens')if usage.get('cache_reported')is True else None}
        cost=usage.get('cost_usd')
        observed={'usage':tokens,'cache_metrics':cache_metrics(tokens),'estimated_usd':cost,
                  'source':'legacy_normalized_cache_reporting_unknown'}
    row['finance_usage']=observed['usage']
    row['finance_context']=dict(context)
    row['finance_estimated_usd']=observed['estimated_usd']
    row['finance']=observed
    row['cache_input_utilization']=observed['cache_metrics']['input_cache_utilization']['value']
    row['cache_all_tokens_share']=observed['cache_metrics']['all_tokens_cache_share']['value']
    row['cache_status']=observed['cache_metrics']['input_cache_utilization']['status']


def finance_summary(rows):
    grouped=defaultdict(lambda:defaultdict(list))
    for row in rows:
        grouped[(row.get('suite_id'),row['task_id'],row.get('repetition',1))][row['variant_id']].append(row)
    pairs=[];numeric=[]
    for key,variants in grouped.items():
        a,b=variants.get('pi-native',[]),variants.get('pi-memweave',[])
        value={'value':None,'status':'unknown','reason':'missing_or_duplicate_arm'}
        native=plugin=None;compatible=False
        if len(a)==len(b)==1:
            a,b=a[0],b[0];ca,cb=a.get('finance_context',{}),b.get('finance_context',{})
            compatible=(all(ca.get(k)is not None and ca.get(k)==cb.get(k)for k in ('model','price','currency'))
                        and a.get('actual_task_id',a['task_id'])==b.get('actual_task_id',b['task_id']))
            if not compatible:
                value={'value':None,'status':'unknown','reason':'incompatible_pair_context'}
            else:
                native=a.get('finance_estimated_usd');plugin=b.get('finance_estimated_usd')
                value=ratio(plugin,native,zero='zero_baseline')
                if value['status']in('scored','not_applicable'):
                    numeric.append((native,plugin,ca['currency']))
        value.update(percent_of_native=100*value['value']if value['value']is not None else None,
                     relative_change=value['value']-1 if value['value']is not None else None)
        pairs.append({'task_id':key[1],'repetition':key[2],'native_estimated_usd':native,
                      'plugin_estimated_usd':plugin,'cost_ratio':value})
    overall=ratio(sum(p for _,p,_ in numeric),sum(n for n,_,_ in numeric),zero='zero_baseline')
    if len(numeric)!=len(pairs)or len({c for _,_,c in numeric})>1:
        overall={'value':None,'status':'unknown','reason':'incomplete_or_incompatible_pairs'}
    if not pairs:
        overall={'value':None,'status':'not_applicable','reason':'no_pairs'}
    overall.update(percent_of_native=100*overall['value']if overall['value']is not None else None,
                   relative_change=overall['value']-1 if overall['value']is not None else None,
                   matched_pairs=len(numeric),planned_pairs=len(pairs),
                   aggregation='sum_matched_costs_then_divide')
    return {'pairs':pairs,'overall_cost_ratio':overall,
            'cache_overall':aggregate_cache(r.get('finance_usage',r.get('usage',{}))for r in rows),
            'cache_by_variant':{v:aggregate_cache(r.get('finance_usage',r.get('usage',{}))for r in rows if r['variant_id']==v)
                                for v in sorted({r['variant_id']for r in rows})},
            'cache_by_task':{t:aggregate_cache(r.get('finance_usage',r.get('usage',{}))for r in rows if r['task_id']==t)
                             for t in sorted({r['task_id']for r in rows})}}


FINANCE_COLUMNS=('cache_input_utilization','cache_all_tokens_share','cache_status',
                 'paired_cost_ratio','plugin_cost_percent_of_native','plugin_cost_relative_change','cost_pair_status')


def attach_pair_columns(rows, summary):
    for row in rows:
        pair=next((p for p in summary['pairs']if p['task_id']==row['task_id']and p['repetition']==row.get('repetition',1)),None)
        value=pair['cost_ratio']if pair else {}
        row.update(paired_cost_ratio=value.get('value'),plugin_cost_percent_of_native=value.get('percent_of_native'),
                   plugin_cost_relative_change=value.get('relative_change'),cost_pair_status=value.get('status'))


def finance_markdown(rows, summary):
    lines=['','## 缓存与配对费用','',
           '输入token已包含cache-hit；主比率=hit/input，辅助=hit/(input+completion)。缺供应商cache字段为unknown。',
           '费用为同模型/价格/币种的峰值参考估计，不是账户实扣；总体用匹配费用和相除。',
           '', '|任务|变体|输入缓存利用率|全部token缓存占比|插件/原生费用比|状态|',
           '|---|---|---:|---:|---:|---|']
    for row in rows:
        lines.append(f"|{row['task_id']}|{row['variant_id']}|{row.get('cache_input_utilization')}|{row.get('cache_all_tokens_share')}|{row.get('paired_cost_ratio')}|{row.get('cache_status')}/{row.get('cost_pair_status')}|")
    lines.extend(['',f"总体费用比：`{json.dumps(summary['overall_cost_ratio'],ensure_ascii=False)}`"])
    return lines
