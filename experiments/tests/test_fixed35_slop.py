from pathlib import Path

import pytest

from memweave_eval.fixed35_slop import checkpoint_outcome, sequential_outcome, slop_task


def report(passed=5,total=5,**changes):
    return dict(infrastructure_failure=False,pytest_exit_code=0 if passed==total else 1,
        pytest_collected=total,pass_counts={'Core':passed},total_counts={'Core':total},**changes)


def test_checkpoint_and_whole_problem_require_every_test_and_stage():
    assert checkpoint_outcome(report())['score']==100
    assert checkpoint_outcome(report(4))['score']==0
    assert checkpoint_outcome(report(4))['partial_score']==80
    result=sequential_outcome({'a':report(),'b':report(4)},['a','b'])
    assert result['score']==0 and result['partial_score']==90 and result['collection_complete']
    result=sequential_outcome({'a':report()},['a','b'])
    assert result['score']is None and not result['collection_complete']
    assert sequential_outcome({'a':report(0)},['a','b'])['score']==0
    for value in [None,{},dict(report(),infrastructure_failure=True),report(0,0),
                  dict(report(),pass_counts={'Core':None}),dict(report(),pytest_exit_code=125)]:
        assert checkpoint_outcome(value)['score']is None


def test_actor_task_contains_only_all_public_rendered_stages(tmp_path):
    prompts=tmp_path/'prompts';prompts.mkdir()
    for i in range(1,9):(prompts/f'part_{i}.md').write_text('public specification '+str(i))
    record=slop_task({'upstream_case_id':'circuit_eval','pack_case_id':'SCB-01','source_revision':'a'*40},
        prompts,tmp_path/'actor',base_image='slop-code:fixed35-python3.12',snapshot_excludes=['.venv/*'])
    task=Path(record['task_path']);assert len(record['stages'])==8
    assert all((task/'steps'/f'checkpoint_{i}'/'instruction.md').read_bytes()==(prompts/f'part_{i}.md').read_bytes()for i in range(1,9))
    assert not (task/'solution').exists()and not list(task.rglob('test_checkpoint*'))
    import tomllib
    config=tomllib.loads((task/'task.toml').read_text())
    assert config['steps'][0]['artifacts'][0]['destination']=='submission'
    assert config['environment']['memory_mb']==8192


def test_missing_or_unrendered_public_stage_cannot_be_admitted(tmp_path):
    prompts=tmp_path/'prompts';prompts.mkdir()
    with pytest.raises(ValueError,match='checkpoint missing'):
        slop_task({'upstream_case_id':'database_migration','pack_case_id':'SCB-02'},prompts,tmp_path/'out',base_image='image:tag',snapshot_excludes=[])


def test_only_fixed_source_checkpoint_conditional_skip_excluded_original_counts_preserved():
    value=dict(report(86,87),pytest_exit_code=0,problem_name='database_migration',checkpoint_name='checkpoint_3',
        tests={'checkpoint_1-Regression':{'skipped':['test_foreign_keys_disabled_during_drop_column']}})
    point=checkpoint_outcome(value)
    assert point['score']==100 and point['passed']==point['total']==86
    assert point['original_reported_total']==87 and point['original_all_reported_tests_score']==0
    assert checkpoint_outcome(dict(value,tests={}))['score']==0
    assert checkpoint_outcome(dict(value,tests={'checkpoint_1-Regression':{'skipped':['other_skip']}}))['score']==0
    assert checkpoint_outcome({k:v for k,v in value.items()if k!='tests'})['score']is None
    assert checkpoint_outcome(dict(value,checkpoint_name='checkpoint_2'))['score']==0


def test_original_reward_never_falls_back_to_derived_applicable_score():
    from memweave_eval.fixed35_slop import score_channels
    with pytest.raises(TypeError):score_channels(None)
    value=score_channels({'score':100,'original_all_reported_tests_AND':0,'collection_complete':True})
    assert value['original_strict']['score']==0 and value['derived_applicable']['score']==100
    value=score_channels({'score':100,'collection_complete':True})
    assert value['original_strict']['score']is None and value['original_strict']['status']=='MISSING_EVIDENCE'
    assert value['derived_applicable']['score']==100


@pytest.mark.parametrize('bad',[True,-1,101,50,float('nan'),float('inf'),'100'])
def test_slop_binary_score_channels_reject_invalid_values(bad):
    from memweave_eval.fixed35_slop import score_channels
    with pytest.raises(ValueError):score_channels({'score':bad,'original_all_reported_tests_AND':0})
    with pytest.raises(ValueError):score_channels({'score':100,'original_all_reported_tests_AND':bad})


def test_known_missing_required_submission_is_original_failure_without_fabricated_test_counts():
    result=sequential_outcome({'a':{'submission_contract':{'handoff_complete':True,
        'missing_required_files':['requirements.txt']}},'b':report()},['a','b'])
    assert result['score']==result['original_all_reported_tests_AND']==0
    assert result['checkpoints']['a']['passed']is None and result['checkpoints']['a']['total']is None


def test_score_pair_binds_current_campaign_container_clock_and_rejects_missing_or_changed_proof(tmp_path,monkeypatch):
    import json

    from memweave_eval import fixed35_slop
    from memweave_eval.storage import file_digest
    root=tmp_path/'case';root.mkdir();environment=tmp_path/'environment.yaml';environment.write_text('fixture')
    config={'schema_version':1,'budget_id':'new-independent','ledger':str(tmp_path/'new-independent/quota.json'),
        'started_at':1000,'model_cutoff':2000,'judge_cutoff':3000,'container_cutoff':4000,'hard_deadline':5000,
        'maximum_usd':19.,'authorized_usd':20.,'arm_limits':{'pi-native':9.,'pi-memweave':9.,'preflight':1.}}
    campaign=tmp_path/'campaign.json';campaign.write_text(json.dumps(config))
    admission={'case_id':'SCB-02','code_path':str(tmp_path),
        'campaign':{'path':str(campaign),'sha256':file_digest(campaign)},'slop_verifier':{
            'environment':str(environment),'environment_sha256':file_digest(environment),'sources':str(tmp_path/'source'),
            'problem_revision':'f'*40,'runner_source':str(tmp_path/'runner'),'runner_revision':'f'*40,
            'runner':str(tmp_path/'runner/bin/slop'),'problem':'database_migration',
            'stages':[f'checkpoint_{i}'for i in range(1,6)],'image_id':'sha256:fixture'}}
    path=root/'admission.json';path.write_text(json.dumps(admission))
    (root/'pair-result.json').write_text(json.dumps({'arms':[{'arm':arm,'result_path':str(tmp_path/arm/'result.json')}
        for arm in ['pi-native','pi-memweave']]}))
    monkeypatch.setattr('memweave_eval.fixed35_campaign.trusted_environment',lambda _:{})
    monkeypatch.setattr(fixed35_slop.subprocess,'check_output',lambda command,**kw:'f'*40 if command[-1]=='HEAD'else'')
    calls=[]
    def evaluate(trial,**kwargs):
        calls.append(kwargs['deadline']);return {'collection_complete':True,'score':100,'fixture_scores_included':True}
    monkeypatch.setattr(fixed35_slop,'evaluate_trial',evaluate)
    scored=fixed35_slop.score_pair(root,tmp_path/'scored',fixture_only=True)
    assert calls==[4000,4000]
    metadata=json.loads(scored.read_text())
    assert metadata['verifier_deadline_unix']==4000 and metadata['campaign_sha256']==admission['campaign']['sha256']
    changed=json.dumps({});campaign.write_text(changed)
    with pytest.raises(ValueError,match='changed'):fixed35_slop.score_pair(root,tmp_path/'changed',fixture_only=True)
    assert not(tmp_path/'changed').exists()and len(calls)==2
    admission.pop('campaign');path.write_text(json.dumps(admission))
    with pytest.raises(ValueError,match='campaign'):fixed35_slop.score_pair(root,tmp_path/'missing',fixture_only=True)
    assert not(tmp_path/'missing').exists()and len(calls)==2


def test_sdk_resource_adapter_labels_and_caps_only_the_owned_create(tmp_path):
    from types import SimpleNamespace

    from memweave_eval.slop_eval_entry import scoped_create
    calls=[]
    owner=SimpleNamespace(client=SimpleNamespace(api=SimpleNamespace(inspect_image=lambda image:{'Id':'sha256:fixed'})))
    def original(self,*args,**kwargs):
        calls.append((args,kwargs));return SimpleNamespace(id='owned-id',reload=lambda:None,
            attrs={'HostConfig':{'NanoCpus':kwargs['nano_cpus'],'Memory':kwargs['mem_limit']}})
    import time
    create=scoped_create(original,run_id='owned-run',cpus=2,memory_mb=8192,
        expected_image='sha256:fixed',deadline=time.time()+10,audit=tmp_path/'audit.jsonl')
    create(owner,'image:tag',command='sleep infinity')
    assert calls[0][1]['labels']=={'org.memweave.eval.run':'owned-run'}
    assert calls[0][1]['nano_cpus']==2000000000 and calls[0][1]['mem_limit']==8192*1024*1024
    assert calls[0][1]['command']=='sleep infinity'
    with pytest.raises(ValueError,match='conflicting'):create(owner,'image:tag',mem_limit=1)
    owner.client.api.inspect_image=lambda image:{'Id':'sha256:other'}
    with pytest.raises(ValueError,match='image changed'):create(owner,'image:tag')
