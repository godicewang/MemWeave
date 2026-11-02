import json

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
