import json

import pytest

from memweave_eval.fixed35_fact_cards import FACTS, grade_fact_cards
from memweave_eval.fixed35_mab import active_text
from memweave_eval.fixed35_mab_cards import BOOKS, grade_book_card


def journal(current,old,*,archive=False):
    values=[{'op_id':'g','op':'update_goal','goal':'finite memory oracle'},
        {'op_id':'a','op':'append_fact','id':'F1','fact':old}]
    values.append({'op_id':'b','op':'modify_fact','archive':['F1'],'append_fact':{'content':current}}
        if archive else{'op_id':'b','op':'append_fact','id':'F2','fact':current})
    values.append({'op_id':'w','op':'slide_window','evicted_range':{'from':2,'to':2},'retained_ids':[]})
    return values


@pytest.mark.parametrize('case',list(FACTS))
def test_hidden_unarchived_fact_conflict_cannot_pass_but_archived_history_can(case):
    from memweave_eval.fixed35_mab import state_text_projection
    facts=FACTS[case];cards=[json.dumps(f['card'])for f in facts]
    old=json.dumps(dict(facts[0]['card'],o='obsolete object',n=1))
    j=journal(cards[0],old);projection=state_text_projection(j)
    visible=projection['visible']+cards[1:];unarchived=projection['unarchived']+cards[1:]
    assert active_text(j)==[cards[0]]
    point=grade_fact_cards(visible,{'facts':facts},before=True,correct_action=True,unarchived_texts=unarchived)
    assert point['score']==0 and point['assertions']['no_competing_current_relation']['value']is False
    p=state_text_projection(journal(cards[0],old,archive=True))
    assert grade_fact_cards(p['visible']+cards[1:],{'facts':facts},before=True,correct_action=True,
        unarchived_texts=p['unarchived']+cards[1:])['score']==100


@pytest.mark.parametrize('case',list(BOOKS))
def test_book_incompatible_hidden_event_is_not_retired_by_window(case):
    spec=dict(BOOKS[case],case_id=case,scope='unit source-specific event grammar',assertions=[
        'correct_typed_event_relation','no_incompatible_current_event','before_dependency','business_action_correct'])
    good=json.dumps(spec['card']);bad=json.dumps(dict(spec['card'],**spec['incompatible'][0]))
    p=grade_book_card([good],spec,before_dependency=True,business_action_correct=True,unarchived_texts=[good,bad])
    assert p['score']==0
    assert grade_book_card([good],spec,before_dependency=True,business_action_correct=True,unarchived_texts=[good])['score']==100


def test_unknown_semantic_projection_and_hidden_good_card_do_not_get_success():
    c={'facts':FACTS['MAB-01']};good=json.dumps(c['facts'][0]['card'])
    assert grade_fact_cards([good],c,before=True,correct_action=True,unarchived_texts=None)['score']is None
    assert grade_fact_cards([],c,before=True,correct_action=True,unarchived_texts=[good])['score']==0


def test_one_source_literal_correction_needs_both_projections():
    from memweave_eval.fixed35_mab import grade_correction
    c={'required_relation_sets':[[['Microsoft','Steve Jobs']]],'forbidden_relations':[['Microsoft','Satya Nadella']]}
    assert grade_correction(['Microsoft CEO Steve Jobs'],c,correct_action=True,snapshot_before_action=True,
        unarchived_texts=['Microsoft CEO Steve Jobs','Microsoft CEO Satya Nadella'])['score']==0
    assert grade_correction(['Microsoft CEO Steve Jobs'],c,correct_action=True,snapshot_before_action=True,
        unarchived_texts=None)['score']is None
