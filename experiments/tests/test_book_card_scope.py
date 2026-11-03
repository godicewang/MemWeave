import json
from copy import deepcopy

import pytest

from memweave_eval.fixed35_mab_cards import BOOKS, card_snapshot


@pytest.mark.parametrize('identity',BOOKS)
def test_known_contradiction_is_scoped_to_the_same_event_and_condition(identity):
    spec=BOOKS[identity];contract={k:spec[k]for k in ['card','aliases','incompatible']}
    correct=deepcopy(spec['card']);bad=deepcopy(correct);bad.update(spec['incompatible'][0])
    assert card_snapshot([json.dumps(correct),json.dumps(bad)],contract)['no_incompatible_current_event']is False
    unrelated=deepcopy(bad)
    available=[k for k in correct if k not in spec['incompatible'][0]and k!='s']
    unrelated[available[0]]='a distinct event outside the target condition'
    grade=card_snapshot([json.dumps(correct),json.dumps(unrelated)],contract)
    assert grade['correct_typed_event_relation']and grade['no_incompatible_current_event']
    bad['s']='a different person'
    assert card_snapshot([json.dumps(correct),json.dumps(bad)],contract)['no_incompatible_current_event']
