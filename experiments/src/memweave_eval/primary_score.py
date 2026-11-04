"""Independent engineering-relative and behavioral scores; no actor or file I/O.

Mappings must be selected and weights approved in the case review before a real
run. This kernel supplies no default weights, no cross-category total, and no
runtime-derived applicability mask.
"""
from __future__ import annotations

import math

VERSION='primary-independent-score.v1'


def _number(value):
    try:return type(value)in(int,float)and math.isfinite(value)
    except OverflowError:return False


def relative_score(native,plugin,*,mapping):
    if mapping not in {'rate_difference','lower_share'}:raise ValueError('explicit supported mapping required')
    result={'native_raw':native,'plugin_raw':plugin,'mapping':mapping,'mapping_version':VERSION,'score':None}
    if native is None or plugin is None:return dict(result,status='missing',reason='paired raw value missing')
    if not all(_number(x)and x>=0 for x in (native,plugin))or mapping=='rate_difference'and max(native,plugin)>1:
        return dict(result,status='invalid',reason='negative, nonfinite, boolean, or rate outside[0,1]')
    quotient=plugin/native if native else None
    ratio=({'kind':'finite','value':quotient}if math.isfinite(quotient)else {'kind':'overflow','value':None})if native else {'kind':'positive_infinity','value':None}if plugin else {'kind':'undefined','value':None}
    result.update(difference=plugin-native,plugin_native_ratio=ratio,equivalence_point=50)
    if mapping=='lower_share'and native+plugin==0:
        return dict(result,status='not_comparable',reason='both values zero; ratio undefined')
    if mapping=='rate_difference':score=50+50*(plugin-native)
    else:
        scale=max(native,plugin);n,p=native/scale,plugin/scale;score=100*n/(n+p)
    return dict(result,status='observed',score=score,
        formula='50+50*(plugin-native)'if mapping=='rate_difference'else'100*native/(native+plugin)')


def behavior_score(opportunities,evidence):
    if not isinstance(opportunities,list)or not opportunities or not isinstance(evidence,dict):
        raise ValueError('nonempty frozen opportunities and explicit evidence required')
    seen=set();points=[]
    for opportunity in opportunities:
        if not isinstance(opportunity,dict):raise TypeError('opportunity must be an object')
        identity=opportunity.get('id');required=opportunity.get('required_assertions')
        if not isinstance(identity,str)or not identity or identity in seen or not isinstance(required,list)or not required \
                or any(not isinstance(i,str)or not i for i in required)or len(set(required))!=len(required):
            raise ValueError('unique opportunity and nonempty unique required assertion IDs required')
        seen.add(identity);values=evidence.get(identity,{})
        if not isinstance(values,dict):values={}
        assertions={i:values.get(i,'missing')for i in required}
        invalid=[i for i,v in assertions.items()if not isinstance(v,str)or v not in {'pass','fail','missing','invalid'}]
        missing=[i for i,v in assertions.items()if v=='missing']
        invalid.extend(i for i,v in assertions.items()if v=='invalid')
        failed=[i for i,v in assertions.items()if v=='fail']
        status='invalid'if invalid else'missing'if missing else'observed_fail'if failed else'observed_pass'
        points.append({'opportunity_id':identity,'assertions':assertions,'status':status,
            'score':None if missing or invalid else 0 if failed else 100,'known_failed_assertions':failed,
            'missing_assertions':missing,'invalid_assertions':invalid})
    if set(evidence)-seen:raise ValueError('evidence contains an unregistered opportunity')
    missing=sum(p['status']=='missing'for p in points);invalid=sum(p['status']=='invalid'for p in points)
    successes=sum(p['status']=='observed_pass'for p in points);failures=sum(p['status']=='observed_fail'for p in points)
    return {'score':None if missing or invalid else 100*successes/len(points),
        'status':'invalid'if invalid else'missing'if missing else'observed',
        'numerator':successes,'denominator':len(points),'failed_opportunities':failures,
        'missing_opportunities':missing,'invalid_opportunities':invalid,'opportunities':points,
        'formula':'100 * all-required-assertions-passed opportunities / fixed applicable opportunities',
        'mapping_version':VERSION}


def weighted_total(metrics,weights):
    if not isinstance(metrics,dict)or not isinstance(weights,dict)or not weights or set(weights)-set(metrics) \
            or any(not _number(w)or w<0 for w in weights.values())or not math.isfinite(sum(weights.values()))or sum(weights.values())<=0:
        raise ValueError('explicit nonnegative weights with positive sum and every metric required')
    planned=sum(weights.values());observed=0.;contribution=0.;missing=[];usable=[];states=[]
    for identity,weight in weights.items():
        if not weight:continue
        metric=metrics[identity]
        if not isinstance(metric,dict):raise TypeError('metric must be an object')
        score=metric.get('score')
        if metric.get('status')=='observed'and _number(score)and 0<=score<=100:
            observed+=weight;contribution+=(weight/planned)*score;usable.append((weight,score))
        else:missing.append(identity);states.append(metric.get('status','missing'))
    return {'score':contribution if not missing else None,
        'status':'observed'if not missing else'invalid'if 'invalid'in states else'not_comparable'if all(s=='not_comparable'for s in states)else'missing',
        'conditional_score':sum(w/observed*s for w,s in usable)if observed else None,
        'planned_weight':planned,'observed_weight':observed,'evidence_coverage':observed/planned,
        'missing_metric_ids':missing,'weights':dict(weights),'mapping_version':VERSION,
        'interpretation':'One category only. Unknown or incomparable values retain their planned weight; no implicit exclusions or cross-category credit.'}
