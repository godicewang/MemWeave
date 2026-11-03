"""Finite source-bound subject/relation/object/serial cards, not word overlap."""
from __future__ import annotations

import json

from .fixed35 import checkpoint_verdict

VERSION='fixed35-current-fact-cards-20261103-v1'
PUBLIC_PROTOCOL='''
Derived serial-fact recording protocol (identical input for both variants): when
retaining an important supplied serial-numbered fact in persistent notes, use
a compact JSON object with exactly four keys: s (subject string), r (relation
string), o (object/value string), n (the original integer fact serial number).
Preserve names and the direction of the relation; use the source relation or a
short conventional equivalent. In MemWeave put each card in a Fact with its real
source evidence. When a newer serial replaces that same subject/relation, retire
the older active card before relying on the new value. Do not invent serials or
store every unrelated sentence. No extra model calls are requested.
'''.strip()


def _fact(s,r,o,n,aliases):return {'card':{'s':s,'r':r,'o':o,'n':n},'relation_aliases':aliases}


FACTS={
 'MAB-01':[_fact('Microsoft','chief executive officer','Steve Jobs',188,['CEO'])],
 'MAB-02':[_fact('Christianity','founded city','Taipei',475,['founded in the city of','founded in','origin']),
    _fact('Bagratuni Dynasty','religion','Christianity',1924,['affiliated with the religion of','religion affiliation'])],
 'MAB-03':[_fact('cornerback','sport','field hockey',7164,['associated with the sport of','associated sport']),
    _fact('field hockey','created country','Philippines',7774,['created in the country of','origin','country']),
    _fact('Christian Abbiati','position','cornerback',10906,['plays the position of','plays position'])],
 'MAB-05':[_fact('The New York Times','language','Ancient Greek',4102,['written in the language of','written language'])]}


def _norm(value):return ' '.join(value.casefold().split())


def fact_snapshot(texts,contract):
    if texts is None:return {'all_current_relations':None,'no_competing_current_relation':None}
    cards=[]
    for text in texts:
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('duplicate key')
                value[key]=item
            return value
        try:card=json.loads(text,object_pairs_hook=unique)
        except (ValueError,TypeError):continue
        if isinstance(card,dict)and set(card)=={'s','r','o','n'}and all(isinstance(card[k],str)for k in ('s','r','o')) \
                and type(card['n'])is int and card['n']>0:
            cards.append({**{k:_norm(card[k])for k in ('s','r','o')},'n':card['n']})
    correct=True;competing=False
    for fact in contract['facts']:
        gold=fact['card'];relations={_norm(v)for v in [gold['r'],*fact['relation_aliases']]}
        same=[c for c in cards if c['s']==_norm(gold['s'])and c['r']in relations]
        correct &= any(c['o']==_norm(gold['o'])and c['n']==gold['n']for c in same)
        competing |= any(c['o']!=_norm(gold['o'])or c['n']!=gold['n']for c in same)
    return {'all_current_relations':bool(correct),'no_competing_current_relation':not competing}


def grade_fact_cards(texts,contract,*,before,correct_action):
    checks=fact_snapshot(texts,contract)
    checks.update(snapshot_precedes_dependency=before,action_uses_current_value=correct_action)
    return dict(checkpoint_verdict({'id':VERSION,'required_assertions':list(checks)},checks),
        scope='Controlled JSON fact grammar, exact subject/relation/object/serial and active alternatives; not a universal semantic parser.')
