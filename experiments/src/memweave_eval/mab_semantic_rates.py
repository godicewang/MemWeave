"""Finite selected-fact rates; no claim about unparsed free-text memory value."""
from __future__ import annotations

import json

from .fixed35_fact_cards import fact_snapshot

VERSION='fixed35-mab-target-fact-rates-20261104-v2'


def _and(values):
    return False if any(v is False for v in values)else True if all(v is True for v in values)else None


def _rate(values,*,complete):
    if not complete:return {'value':None,'numerator':None,'denominator':None,'unknown':None,
        'status':'unknown','collection_complete':False,'reason':'whole source observation sequence incomplete'}
    s=sum(v is True for v in values);f=sum(v is False for v in values);u=len(values)-s-f
    return {'value':s/(s+f)if s+f and not u else None,'numerator':s,'denominator':s+f,'unknown':u,
        'status':'not_applicable'if not values else'partial'if u else'scored',
        'collection_complete':not u,'reason':'No eligible target-card changes'if not values else None}


def classify_target_card(text,contract):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate card key')
            result[key]=value
        return result
    try:card=json.loads(text,object_pairs_hook=unique)
    except (ValueError,TypeError):return None
    if not isinstance(card,dict)or set(card)!={'s','r','o','n'}or type(card['n'])is not int \
            or card['n']<1 or any(not isinstance(card[k],str)for k in ['s','r','o']):return None
    norm=lambda s:' '.join(s.casefold().split())
    for fact in contract['facts']:
        gold=fact['card']
        if norm(card['s'])==norm(gold['s'])and norm(card['r'])in {norm(v)for v in [gold['r'],*fact['relation_aliases']]}:
            return fact_snapshot([text],{'facts':[fact]})['all_current_relations']
    return None


def semantic_rates(contract,evictions,correction,writes,*,complete,prior_active_record=None):
    """Three source-retention opportunities, one deadline, actual target changes."""
    points=[evictions[i]if i<len(evictions)else{}for i in range(3)]
    retained=[_and([p.get('original_source_absent'),p.get('current_facts_retained')])for p in points]
    assertions=(correction or{}).get('assertions',{})
    check=lambda key:assertions.get(key,{}).get('value')
    timely=retained[0]if evictions else _and([check('all_current_relations'),check('snapshot_precedes_dependency'),
        check('source_exposed_before_dependency')])
    pollution=[None if type((p.get('semantic_unarchived_checks')or{}).get('no_competing_current_relation'))is not bool
        else not p['semantic_unarchived_checks']['no_competing_current_relation']for p in points]
    decisions=[classify_target_card(t,contract)for t in writes];known=[v for v in decisions if type(v)is bool]
    return {'version':VERSION,'timely_write':_rate([timely],complete=complete),
        'retention':_rate(retained,complete=complete),'pollution':_rate(pollution,complete=complete),
        'write_precision':_rate(known,complete=complete),
        'correction':_rate([]if prior_active_record is False else[None]if prior_active_record is None else
            [_and([check(k)for k in ['all_current_relations','no_competing_current_relation',
            'snapshot_precedes_dependency','action_uses_current_value','source_exposed_before_dependency']])],complete=complete),
        'adoption':_rate([_and([check(k)for k in ['all_current_relations','snapshot_precedes_dependency',
            'action_uses_current_value','source_exposed_before_dependency']])],complete=complete),
        'controlled_coverage':{'all_observed_post_source_fd_changes':len(writes),'target_card_changes':len(known),
            'outside_parser_or_target':len(writes)-len(known),'required_retention_boundaries':3,
            'prior_active_record_observed':prior_active_record},
        'scope':'Only frozen target subject/relation/object/serial cards after all target source exposure; '
            'unparsed or unrelated text is outside precision scope, not proven correct. '
            'Correction rate requires a separately observed previously active old card. '
            'Action consistency does not prove internal reading or causal State adoption.'}
