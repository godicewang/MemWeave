"""Finite narrative-event card rates; unparsed memory is outside this oracle."""
from __future__ import annotations

import json

from .fixed35_mab_cards import card_snapshot
from .mab_semantic_rates import _and, _rate

VERSION='fixed35-mab-target-book-rates-20261104-v1'


def classify_book_target(text,contract):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate event-card key')
            result[key]=value
        return result
    try:card=json.loads(text,object_pairs_hook=unique)
    except (ValueError,TypeError):return None
    if not isinstance(card,dict)or set(card)!={'s','r','o','q'}or any(not isinstance(v,str)for v in card.values()):
        return None
    norm=lambda s:' '.join(s.casefold().split())
    card={k:norm(v)for k,v in card.items()}
    allowed={k:{norm(v)for v in [value,*contract['aliases'].get(k,[])]}for k,value in contract['card'].items()}
    target=all(card[k]in allowed[k]for k in ['s','r','q'])
    known_bad=any(all(card[k]==norm(v)for k,v in bad.items())and
        all(card[k]in allowed[k]for k in allowed if k not in bad)for bad in contract['incompatible'])
    if not(target or known_bad):return None
    return all(card_snapshot([text],contract).values())


def book_semantic_rates(contract,evictions,action,writes,*,complete,source_exposed):
    points=[evictions[i]if i<len(evictions)else{}for i in range(3)]
    retained=[_and([p.get('original_source_absent'),p.get('current_facts_retained')])for p in points]
    checks=(action or{}).get('assertions',{})
    get=lambda name:checks.get(name,{}).get('value')
    at_action=_and([get('correct_typed_event_relation'),get('no_incompatible_current_event'),
        get('before_dependency'),source_exposed])
    timely=retained[0]if evictions else at_action
    pollution=[None if type((p.get('semantic_unarchived_checks')or{}).get('no_incompatible_current_event'))is not bool
        else not p['semantic_unarchived_checks']['no_incompatible_current_event']for p in points]
    values=[classify_book_target(t,contract)for t in writes];known=[v for v in values if type(v)is bool]
    return {'version':VERSION,'timely_write':_rate([timely],complete=complete),
        'retention':_rate(retained,complete=complete),'pollution':_rate(pollution,complete=complete),
        'write_precision':_rate(known,complete=complete),
        'adoption':_rate([_and([at_action,get('business_action_correct')])],complete=complete),
        'controlled_coverage':{'all_observed_post_source_fd_changes':len(writes),'target_card_changes':len(known),
            'outside_parser_or_target':len(writes)-len(known),'required_retention_boundaries':3},
        'scope':'Only frozen source event s/r/o/q cards with explicit aliases and incompatible alternatives. '
            'Other contexts and unparsed free text are outside precision scope, not proven correct. '
            'Three actual source cuts and pre-action evidence are distinct opportunities; action consistency is not causal State adoption.'}
