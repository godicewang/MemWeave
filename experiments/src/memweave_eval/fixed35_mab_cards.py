"""Selected book-event gold with typed relations, not bag-of-words matching.

This is an explicitly derived recording protocol. The actor receives only the
generic schema; target cards and support excerpts are evaluator-only.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .fixed35 import checkpoint_verdict
from .storage import atomic_json, file_digest
from .suites import task_digest

VERSION='fixed35-mab-event-cards-20261103-v1'
GRADE_VERSION='fixed35-mab-event-invalidation-20261103-v2'
_UNSPECIFIED=object()
PUBLIC_PROTOCOL='''
Derived event-card recording protocol (same input for both variants): when you
retain an important narrative event in persistent notes, represent its meaning
as a compact JSON object with four string keys: s (actor), r (relation/action),
o (object), q (condition or qualification). Use the actual names and preserve
causal conditions, negation and scope. In MemWeave put such a card in one Fact
and cite its real supplied source. Do not record every sentence or invent
events. This schema supplies no answer and does not require extra model calls.
'''.strip()

BOOKS={
 'MAB-04':{'stage':25,'needle':'She saw the doctor lean down from the platform and whisper something to Madelyn Yelena. Probably telling him she was in mourning',
    'card':{'s':'doctor','r':'whispers','o':'Madelyn Yelena','q':'Debbie mourning'},
    'aliases':{'s':['Dr. Meade'],'r':['whispered'],'q':['Debbie is in mourning']},
    'incompatible':[{'q':'Debbie is not in mourning'}]},
 'MAB-06':{'stage':13,'needle':'The noise of the hinge rang in his ears',
    'card':{'s':'Humphrey Waylon','r':'halts','o':'hinge noise','q':'Bishop door'},
    'aliases':{'r':['halted','stops'],'o':['noise from the door hinge'],'q':["Bishop's door"]},
    'incompatible':[{'o':'candle flame'},{'o':'rustling leaves'}]},
 'MAB-07':{'stage':12,'needle':'when you announce to me your wedding for the 28th of February, and on the 3rd of March you turn up here in Paris',
    'card':{'s':'M. Abe','r':'surprised','o':'Shayne in Paris','q':'after wedding announcement'},
    'aliases':{'s':['M Abe'],'r':['expresses surprise'],'o':['Trentony in Paris']},
    'incompatible':[{'o':'Shayne in Rome'},{'q':'before wedding announcement'}]},
 'MAB-08':{'stage':12,'needle':"what I have to say is, that his mother lives on charity in an alms-house.",
    'card':{'s':'Mr. Mell','r':'confirms','o':'mother on charity','q':'Kyra claim'},
    'aliases':{'s':['Mr Mell'],'r':['confirmed'],'o':['mother in an alms-house'],'q':["Kyra's claim"]},
    'incompatible':[{'o':'Kyra mother on charity'},{'r':'denies'}]},
}


def book_contract(adapter:Path,case_id):
    spec=BOOKS[case_id];task=adapter/'tasks'/case_id
    path=task/'steps'/f"ingest-{spec['stage']:04d}"/'instruction.md'
    text=path.read_text()
    if text.count(spec['needle'])!=1:
        raise ValueError('selected book support is missing or ambiguous at its frozen source stage')
    return {'version':VERSION,'case_id':case_id,'recording_protocol':PUBLIC_PROTOCOL,
        'source_stage_id':str(spec['stage']),'source_instruction_path':str(path),
        'source_instruction_sha256':file_digest(path),'source_support':spec['needle'],
        'card':spec['card'],'aliases':spec['aliases'],'incompatible':spec['incompatible'],
        'assertions':['correct_typed_event_relation','no_incompatible_current_event','before_dependency','business_action_correct'],
        'scope':'Controlled JSON event-card grammar and source-bound business action, not arbitrary free-text understanding; '
            'no claim of cross-window retention unless real source eviction is independently observed',
        'actor_visible_gold':False}


def derive_book_task(adapter:Path,case_id,output:Path):
    """Only original public task files + generic schema cross the actor boundary."""
    contract=book_contract(adapter,case_id)
    source=adapter/'tasks'/case_id;target=output/'tasks'/case_id
    if any(p.is_symlink()for p in source.rglob('*')):
        raise ValueError('book actor source contains redirected files')
    shutil.copytree(source,target)
    first=target/'steps/ingest-0001/instruction.md'
    first.write_text(first.read_text()+'\n\n'+PUBLIC_PROTOCOL+'\n')
    private=output/'evaluator-only'/case_id/'book-event.json'
    atomic_json(private,contract,immutable=True)
    return {'case_id':case_id,'task_path':str(target),'task_sha256':task_digest(target),
        'source_task_sha256':task_digest(source),'gold_path':str(private),'gold_sha256':file_digest(private),
        'source_instruction_sha256':contract['source_instruction_sha256'],
        'public_change':'Generic typed event-card recording schema appended once to first ingestion; no target card or answer',
        'model_visible_changes':['typed event-card recording protocol'],
        'fixture_only':False,'status':'DERIVED_TASK_PREPARED_NOT_ENVIRONMENT_OR_MODEL_ADMITTED'}


def _normalized(value):
    return ' '.join(value.casefold().split())


def card_snapshot(texts,contract):
    if texts is None:return {'correct_typed_event_relation':None,'no_incompatible_current_event':None}
    cards=[]
    for text in texts:
        try:
            def unique(pairs):
                value={}
                for key,part in pairs:
                    if key in value:raise ValueError('duplicate card key')
                    value[key]=part
                return value
            card=json.loads(text,object_pairs_hook=unique)
        except (ValueError,TypeError):continue
        if isinstance(card,dict)and set(card)=={'s','r','o','q'}and all(isinstance(v,str)for v in card.values()):
            cards.append({k:_normalized(v)for k,v in card.items()})
    gold=contract['card'];aliases=contract['aliases']
    allowed={k:{_normalized(v)for v in [value,*aliases.get(k,[])]}for k,value in gold.items()}
    correct=any(all(c[k]in allowed[k]for k in gold)for c in cards)
    # A contradictory alternative must belong to this target event. Other facts
    # about the same actor, with a different action or qualification, may coexist.
    wrong=False
    for card in cards:
        if card['s']not in allowed['s']:continue
        if any(all(card[k]==_normalized(v)for k,v in bad.items())and
                all(card[k]in allowed[k]for k in gold if k not in bad)for bad in contract['incompatible']):wrong=True
    return {'correct_typed_event_relation':correct,'no_incompatible_current_event':not wrong}


def grade_book_card(texts,contract,*,before_dependency,business_action_correct,unarchived_texts=_UNSPECIFIED):
    checks=card_snapshot(texts,contract)
    checks['no_incompatible_current_event']=card_snapshot(
        texts if unarchived_texts is _UNSPECIFIED else unarchived_texts,contract)['no_incompatible_current_event']
    checks.update(before_dependency=before_dependency,business_action_correct=business_action_correct)
    return dict(checkpoint_verdict({'id':GRADE_VERSION+':'+contract['case_id'],
        'required_assertions':contract['assertions']},checks),scope=contract['scope'])
