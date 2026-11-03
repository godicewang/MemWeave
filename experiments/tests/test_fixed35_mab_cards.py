import json

import pytest

from memweave_eval.fixed35_mab_cards import BOOKS, PUBLIC_PROTOCOL, book_contract, grade_book_card


def contract(tmp_path,identity):
    spec=BOOKS[identity];path=tmp_path/'tasks'/identity/'steps'/f"ingest-{spec['stage']:04d}"/'instruction.md'
    path.parent.mkdir(parents=True);path.write_text('Original source before. '+spec['needle']+' After.')
    return book_contract(tmp_path,identity)


@pytest.mark.parametrize('identity',list(BOOKS))
def test_each_book_relation_positive_independent_negative_and_missing(tmp_path,identity):
    gold=contract(tmp_path,identity);card=gold['card']
    def grade(texts,**extra):return grade_book_card(texts,gold,before_dependency=True,business_action_correct=True,**extra)
    assert grade([json.dumps(card)])['score']==100
    # All names present in the wrong relation is not a correct event.
    assert grade([json.dumps(dict(card,r='mentions all these words'))])['score']==0
    assert grade([json.dumps(card),json.dumps(dict(card,**gold['incompatible'][0]))])['score']==0
    assert grade([' '.join(card.values())])['score']==0
    assert grade_book_card([json.dumps(card)],gold,before_dependency=False,business_action_correct=True)['score']==0
    assert grade_book_card([json.dumps(card)],gold,before_dependency=True,business_action_correct=False)['score']==0
    assert grade(None)['score']is None
    assert grade_book_card([json.dumps(card)],gold,before_dependency=None,business_action_correct=True)['score']is None
    assert not grade(None)['collection_complete']


@pytest.mark.parametrize('identity',list(BOOKS))
def test_book_support_is_source_bound_and_gold_not_in_public_protocol(tmp_path,identity):
    gold=contract(tmp_path,identity)
    assert gold['actor_visible_gold']is False
    assert gold['source_support']not in PUBLIC_PROTOCOL
    assert json.dumps(gold['card'])not in PUBLIC_PROTOCOL
    from pathlib import Path
    Path(gold['source_instruction_path']).write_text('unrelated same book')
    with pytest.raises(ValueError,match='missing or ambiguous'):book_contract(tmp_path,identity)


def test_derived_actor_contains_only_public_original_and_generic_schema(tmp_path):
    from memweave_eval.fixed35_mab_cards import derive_book_task
    identity='MAB-06';gold=contract(tmp_path,identity)
    first=tmp_path/'tasks'/identity/'steps/ingest-0001/instruction.md'
    first.parent.mkdir(parents=True);first.write_text('Source first excerpt')
    original=first.read_bytes();output=tmp_path/'derived'
    record=derive_book_task(tmp_path,identity,output)
    from pathlib import Path
    actor=Path(record['task_path'])
    assert (actor/'steps/ingest-0001/instruction.md').read_text()=='Source first excerpt\n\n'+PUBLIC_PROTOCOL+'\n'
    assert first.read_bytes()==original
    assert not (actor/'book-event.json').exists()
    assert json.loads(Path(record['gold_path']).read_text())['card']==gold['card']
    assert json.dumps(gold['card'])not in (actor/'steps/ingest-0001/instruction.md').read_text()
