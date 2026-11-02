
import pytest

from memweave_eval.fixed35_campaign import validate_admission
from memweave_eval.fixed35_collection import unique_sessions


def test_cumulative_session_copies_count_once_and_require_prefix(tmp_path):
    a=tmp_path/'one/sessions';b=tmp_path/'two/sessions';a.mkdir(parents=True);b.mkdir(parents=True)
    (a/'session.jsonl').write_text('one\n')
    (b/'session.jsonl').write_text('one\ntwo\n')
    assert unique_sessions(tmp_path)==[b/'session.jsonl']
    (a/'session.jsonl').write_text('wrong\n')
    with pytest.raises(ValueError,match='conflicting'):
        unique_sessions(tmp_path)


def test_no_admission_without_frozen_real_preflight_and_contract():
    with pytest.raises(ValueError,match='missing admission'):
        validate_admission({'case_id':'MAB-01'})
