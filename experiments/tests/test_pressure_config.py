import pytest

from memweave_eval.pressure_config import window_settings


def test_only_explicit_window_pressure_fields_are_accepted():
    assert window_settings({})is None
    assert window_settings({'memory_config':{'recent_turns':2,'evict_turns':1}})=={'recent_turns':2,'evict_turns':1}
    for bad in (False,[],{}, {'recent_turns':2}, {'recent_turns':2,'evict_turns':3},
            {'recent_turns':True,'evict_turns':1}, {'recent_turns':2,'evict_turns':0},
            {'recent_turns':2,'evict_turns':1,'state_max_events':500}):
        with pytest.raises(ValueError):window_settings({'memory_config':bad})
