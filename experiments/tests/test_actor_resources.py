import pytest

from memweave_eval.actor_resources import verify_actor_limits


def test_actual_limits_must_match_each_frozen_arm():
    expected={'cpus':4,'memory_mb':16384}
    host={'NanoCpus':4_000_000_000,'Memory':16*1024**3}
    assert verify_actor_limits(host,expected)['verified_before_credentials']is True
    for change in [{'NanoCpus':0},{'Memory':24*1024**3},{'NanoCpus':5_000_000_000},
        {'NanoCpus':False},{'Memory':None}]:
        with pytest.raises(ValueError):verify_actor_limits(dict(host,**change),expected)
    for wrong in [None,{},dict(expected,cpus=True),dict(expected,memory_mb=0)]:
        with pytest.raises(ValueError):verify_actor_limits(host,wrong)
