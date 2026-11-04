"""Keep frozen category/family budgets after legitimate case NA, never hide missing."""
from __future__ import annotations

import math

NA={'DESIGN_NA','not_applicable','CONDITIONAL_NO_OPPORTUNITY','DIAGNOSTIC'}
VERSION='fixed35-balanced-profile-20261104-v1'


def balanced_profile(metrics,definition,*,allowed_ids=None):
    def canon(value):return 'S.case_v2.'+value[4:]if value.startswith('F35.')else value
    by={canon(m.get('id',m.get('metric_id',''))):m for m in metrics}
    allowed={canon(i)for i in allowed_ids}if allowed_ids is not None else None
    effective={};categories={};exceptions=[]
    for category,target in definition['class_weights'].items():
        live=[]
        for name,family in definition[category].items():
            leaves=[]
            for identity,weight in family['leaves'].items():
                m=by.get(identity)
                if m is None or allowed is not None and identity not in allowed or m.get('status')in NA:continue
                if m.get('status')=='EXCLUDED_UNCOLLECTABLE':
                    exceptions.append(identity);continue
                leaves.append((identity,weight,m))
            if leaves:live.append((name,family['weight'],leaves))
        family_weight=sum(f[1]for f in live)
        categories[category]={'target_weight':target,'designed':bool(live),'families':{}}
        for name,weight,leaves in live:
            allocation=target*weight/family_weight;denominator=sum(w for _,w,_ in leaves)
            categories[category]['families'][name]={'effective_weight':allocation,'metric_ids':[i for i,_,_ in leaves]}
            for identity,leaf,m in leaves:effective[identity]=allocation*leaf/denominator
    planned=sum(effective.values());known={}
    for identity,weight in effective.items():
        m=by[identity];value=m.get('score')
        if m.get('status')in {'scored','SCORED'}and type(value)in (int,float)and math.isfinite(value)and 0<=value<=100 and m.get('collection_complete')is not False and m.get('collection_status')!='REPAIR_REQUIRED':known[identity]=weight
    observed=sum(known.values());contribution=sum(w*by[i]['score']for i,w in known.items())
    complete=math.isclose(observed,planned,abs_tol=1e-12)and planned>0
    both=all(c['designed']for c in categories.values())
    for category,summary in categories.items():
        ids={i for f in summary['families'].values()for i in f['metric_ids']};budget=sum(effective[i]for i in ids);seen=sum(known.get(i,0)for i in ids)
        points=sum(known.get(i,0)*by[i]['score']for i in ids if i in known)
        summary.update(eligible_weight=budget,observed_weight=seen,coverage=seen/budget if budget else None,
            score=points/budget if budget and math.isclose(seen,budget,abs_tol=1e-12)else None)
    return {'score':contribution/planned if complete and both else None,
        'conditional_score':contribution/observed if observed else None,'coverage':observed/planned if planned else None,
        'eligible_weight':planned,'planned_weight':planned,'observed_weight':observed,
        'lower':contribution/planned if planned else None,'upper':(contribution+100*(planned-observed))/planned if planned else None,
        'full_profile_design_coverage':planned,'full_profile_evidence_coverage':observed,
        'full_profile_lower':contribution,'full_profile_upper':contribution+100*(1-observed),
        'effective_leaf_weights':effective,'classes':categories,'excluded_metric_ids':exceptions,
        'missing_metric_ids':[i for i in effective if i not in known],
        'class_balance_status':'BOTH_CATEGORIES_FIXED'if both else'ONE_OR_MORE_CATEGORIES_NOT_DESIGNED',
        'aggregation_version':VERSION,
        'interpretation':'Frozen class budgets and family budgets; legitimate NA redistributes only within its parent. Missing evidence retains weight. An absent entire category prevents a full two-class point score; observed conditional score and full-profile bounds remain explicit.'}
