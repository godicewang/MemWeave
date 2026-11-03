import json

import pytest
from harbor.models.job.config import JobConfig

from memweave_eval.fixed35_execution import can_pair, job_config


def test_resource_admission_cannot_pair_48_gib_on_41_gib():
    assert not can_pair({'cpus':4,'memory_mb':24576},12,42040)
    assert not can_pair({'cpus':8,'memory_mb':16384},12,42040)
    assert can_pair({'cpus':2,'memory_mb':4096},12,42040)


def test_fixed_jobs_keep_real_pi_full_subject_and_harbor_resume(tmp_path):
    plan=tmp_path/'runtime-assets.json';plan.write_text('{}')
    plan.with_name('runtime-assets.lock.json').write_text(json.dumps({'objects':{}}))
    for arm in ['pi-native','pi-memweave']:
        config=job_config(root=tmp_path,task=tmp_path/'MAB-01',case_id='MAB-01',arm=arm,
                          run_id='r',plan=plan,deadline=1793650812.,resources={'cpus':2,'memory_mb':4096})
        parsed=JobConfig.model_validate(config)
        assert parsed.agents[0].resume_trajectory
        options=parsed.agents[0].kwargs
        assert options['protocol']=='fixed35' and options['evaluation_progress_after_returns']==0
        assert options['evaluation_content_evidence'] and options['evaluation_case_id']=='MAB-01'
        assert 'source_revision' not in options and 'gold' not in options
        assert options['auth_path'].endswith('/auth.json')


def test_requested_resources_are_enforced_by_public_harbor_overrides_not_only_logged(tmp_path):
    plan=tmp_path/'runtime-assets.json';plan.write_text('{}')
    cfg=job_config(root=tmp_path,task=tmp_path/'source-default-four-cpus',case_id='INT-06',arm='pi-native',
        run_id='free',plan=plan,deadline=3000,prepare_only=True,
        resources={'cpus':1,'memory_mb':2048,'storage_mb':10240})
    environment=JobConfig.model_validate(cfg).environment
    assert environment.override_cpus==1
    assert environment.override_memory_mb==2048
    assert environment.override_storage_mb==10240


def test_long_episode_uses_frozen_source_timeout_not_an_unrelated_45_minute_cap(tmp_path):
    from memweave_eval.fixed35_campaign import validate_episode_policy
    (tmp_path/'task.toml').write_text('[agent]\ntimeout_sec=28800\n')
    validate_episode_policy({'task_path':str(tmp_path),'seconds':28800,'episode_budget':.5})
    (tmp_path/'task.toml').write_text('[agent]\ntimeout_sec=900\n')
    with pytest.raises(ValueError):validate_episode_policy({'task_path':str(tmp_path),'seconds':901,'episode_budget':.5})
    validate_episode_policy({'task_path':str(tmp_path),'seconds':900,'episode_budget':.5})


@pytest.mark.parametrize('field,value',[('seconds',float('nan')),('seconds',float('inf')),('seconds',True),
    ('episode_budget',float('nan')),('episode_budget',False)])
def test_episode_policy_rejects_invalid_values(tmp_path,field,value):
    from memweave_eval.fixed35_campaign import validate_episode_policy
    (tmp_path/'task.toml').write_text('[agent]\ntimeout_sec=900\n')
    with pytest.raises(ValueError):validate_episode_policy(
        {'task_path':str(tmp_path),'seconds':900,'episode_budget':.5,field:value})


def test_source_stage_policy_preserves_each_stage_and_sum(tmp_path):
    from memweave_eval.fixed35_campaign import validate_episode_policy
    from memweave_eval.fixed35_execution import source_stage_budgets
    (tmp_path/'task.toml').write_text('[agent]\ntimeout_sec=900\n[[steps]]\nname="first"\n[[steps]]\nname="second"\n[steps.agent]\ntimeout_sec=300\n')
    assert source_stage_budgets(tmp_path)==[900,300]
    record={'task_path':str(tmp_path),'seconds':1200,'episode_budget':.5,'time_policy':'source-per-stage'}
    validate_episode_policy(record)
    with pytest.raises(ValueError):validate_episode_policy(dict(record,seconds=900))
    plan=tmp_path/'plan.json';plan.write_text('{}')
    plan.with_name('runtime-assets.lock.json').write_text(json.dumps({'objects':{}}))
    cfg=job_config(root=tmp_path,task=tmp_path,case_id='Switch',arm='pi-native',run_id='r',
        plan=plan,deadline=3000,seconds=1200,resources={'cpus':2,'memory_mb':4096},time_policy='source-per-stage')
    assert 'override_timeout_sec'not in cfg['agents'][0]
    assert cfg['agents'][0]['kwargs']['evaluation_stage_timeouts']==[900,300]
    assert cfg['agents'][0]['kwargs']['evaluation_task_timeouts']=={tmp_path.name:1200}
