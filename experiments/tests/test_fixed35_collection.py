
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


def test_long_qualification_counts_only_successful_unique_main_api_returns():
    from memweave_eval.fixed35_collection import qualified_actor_calls
    request={'tools':[{'function':{'name':'bash'}}]}
    response={'http_status':200,'stream_done':True,'successful_finish':True,'assistant_payload_present':True,
        'provider_error':False,'usage':{'prompt_tokens':100,'completion_tokens':1}}
    assert qualified_actor_calls({'main':request},{'main':response})==['main']
    for change in [{'http_status':500},{'successful_finish':False},{'assistant_payload_present':False},
        {'provider_error':True},{'usage':{'prompt_tokens':0,'completion_tokens':0}},{'stream_done':False}]:
        assert qualified_actor_calls({'main':request},{'main':dict(response,**change)})==[]
    assert qualified_actor_calls({'aux':{'tools':[]}},{'aux':response})==[]
