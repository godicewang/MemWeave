import json

import pytest

from memweave_eval.fixed35_fact_cards import FACTS, fact_snapshot, grade_fact_cards


@pytest.mark.parametrize('identity',list(FACTS))
def test_each_fact_case_requires_relationship_current_serial_and_action(identity):
    contract={'facts':FACTS[identity]}
    cards=[json.dumps(f['card'])for f in FACTS[identity]]
    assert grade_fact_cards(cards,contract,before=True,correct_action=True)['score']==100
    changed=json.loads(cards[0]);changed['r']='unrelated association'
    assert grade_fact_cards([json.dumps(changed),*cards[1:]],contract,before=True,correct_action=True)['score']==0
    changed=json.loads(cards[0]);changed['o']='a different entity'
    assert grade_fact_cards([json.dumps(changed),*cards[1:]],contract,before=True,correct_action=True)['score']==0
    # Obsolete current facts cannot hide beside a correct record.
    assert grade_fact_cards([*cards,json.dumps(changed)],contract,before=True,correct_action=True)['score']==0
    assert grade_fact_cards(cards,contract,before=False,correct_action=True)['score']==0
    assert grade_fact_cards(cards,contract,before=True,correct_action=False)['score']==0
    assert grade_fact_cards(None,contract,before=True,correct_action=True)['score']is None
    assert grade_fact_cards(cards,contract,before=None,correct_action=True)['score']is None
    assert not fact_snapshot([' '.join(str(v)for v in f['card'].values())for f in FACTS[identity]],contract)['all_current_relations']


def test_duplicate_json_keys_or_unsupported_serial_cannot_pass():
    contract={'facts':FACTS['MAB-01']}
    c=FACTS['MAB-01'][0]['card']
    for n in (True,'188',187,189):
        assert not fact_snapshot([json.dumps(dict(c,n=n))],contract)['all_current_relations']
    assert not fact_snapshot(['{"s":"other","s":"Microsoft","r":"CEO","o":"Steve Jobs","n":188}'],contract)['all_current_relations']
