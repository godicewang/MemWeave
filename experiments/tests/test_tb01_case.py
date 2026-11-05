import json

import pytest

from memweave_eval.primary_score import behavior_score
from memweave_eval.tb01_case import DERIVED_ID, DERIVED_TEST, SOURCE_HASHES, WRAPPER


def test_repeat_bundle_requires_correctness_as_well_as_stability():
    opportunity=[{'id':'repeat','required_assertions':['equal','oracle']}]
    stable_wrong=json.loads('{"metrics":{"accuracy":0}}');same_wrong=json.loads('{"metrics":{"accuracy":0}}');gold={'metrics':{'accuracy':1}}
    assert stable_wrong==same_wrong and stable_wrong!=gold
    result=behavior_score(opportunity,{'repeat':{'equal':'pass','oracle':'fail'}})
    assert result['score']==0 and result['denominator']==1
    assert behavior_score(opportunity,{'repeat':{'equal':'pass'}})['score']is None
    assert behavior_score(opportunity,{'repeat':{'equal':'pass','oracle':'pass'}})['score']==100


def test_adapter_preserves_original_reward_and_tests_and_protects_gold():
    assert len(SOURCE_HASHES)==3 and 'test_repeat_fixture_matches_independent_oracle'in DERIVED_ID
    assert 'original.assert_result_matches(actual,expected)'in DERIVED_TEST
    assert 'original.evaluate_dataset(examples)'in DERIVED_TEST
    assert WRAPPER.index('chmod 700 /tests')<WRAPPER.index('bash /tests/test.original.sh')
    assert 'reward.txt'not in WRAPPER and 'reward.json'not in WRAPPER


def test_primary_control_requires_real_adapter_artifacts_not_only_original_reward(tmp_path):
    from memweave_eval.tb01_case import control_evidence_ok
    v=tmp_path/'verifier';v.mkdir()
    assert not control_evidence_ok(tmp_path,True)
    (v/'isolation-ready.json').write_text('{"isolation_ready":true}')
    (v/'derived-ctrf.json').write_text(json.dumps({'results':{'tests':[{'name':DERIVED_ID,'status':'passed'}]}}))
    assert control_evidence_ok(tmp_path,True)and not control_evidence_ok(tmp_path,False)
    (v/'isolation-ready.json').write_text('{"isolation_ready":false}')
    assert not control_evidence_ok(tmp_path,True)


@pytest.mark.parametrize('seconds',[5400,7200,28800])
def test_time_adaptation_updates_visible_instruction_from_same_effective_timer(tmp_path,seconds):
    from memweave_eval.storage import file_digest
    from memweave_eval.tb01_case import align_primary_time_instruction

    original='Original problem and constraints.\nYou have 28800 seconds to complete this task. Do not cheat.\n'
    (tmp_path/'task.toml').write_text(f'[agent]\ntimeout_sec={seconds}\n')
    (tmp_path/'instruction.md').write_text(original)
    evidence=align_primary_time_instruction(tmp_path)
    actual=(tmp_path/'instruction.md').read_text()
    assert f'You have {seconds} seconds to complete this task.'in actual
    assert actual==original.replace('28800',str(seconds))
    assert evidence['actor_seconds']==seconds and evidence['source_actor_seconds']==28800
    assert evidence['effective_instruction_sha256']==file_digest(tmp_path/'instruction.md')
    assert evidence['model_visible_task_changed']is(seconds!=28800)


@pytest.mark.parametrize('text',[
    'Problem without a visible timer.',
    'You have 28800 seconds to complete this task.\nYou have 28800 seconds to complete this task.',
    'You have 7200 seconds to complete this task.',
])
def test_visible_clock_missing_duplicate_or_changed_is_rejected_without_mutation(tmp_path,text):
    from memweave_eval.tb01_case import align_primary_time_instruction

    (tmp_path/'task.toml').write_text('[agent]\ntimeout_sec=5400\n')
    instruction=tmp_path/'instruction.md';instruction.write_text(text)
    with pytest.raises(ValueError,match='source time declaration'):
        align_primary_time_instruction(tmp_path)
    assert instruction.read_text()==text


@pytest.mark.parametrize('seconds',[0,-1,28801,'true','5400.0'])
def test_visible_timer_rejects_invalid_or_nonintegral_effective_cap(tmp_path,seconds):
    from memweave_eval.tb01_case import align_primary_time_instruction

    (tmp_path/'task.toml').write_text(f'[agent]\ntimeout_sec={seconds}\n')
    instruction=tmp_path/'instruction.md';text='You have 28800 seconds to complete this task.';instruction.write_text(text)
    with pytest.raises(ValueError,match='effective actor timer'):
        align_primary_time_instruction(tmp_path)
    assert instruction.read_text()==text
