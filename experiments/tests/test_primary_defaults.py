import pytest

from memweave_eval.pi_agent import (
    PiExperimentOptions,
    product_initialization_script,
    profile_configurations,
)


def options(**changes):
    return PiExperimentOptions(node_version='24.22.0',variant='pi-memweave',package_path='/tmp/subject.tgz',package_sha256='a'*64,auth_path='',protocol='tb4',evaluation_primary_default=True,evaluation_progress_after_returns=0,evaluation_output_tokens=384000,**changes)


def test_primary_defaults_do_not_write_model_or_compaction_overrides():
    o=options();assert profile_configurations(o)=={}
    legacy=PiExperimentOptions(node_version='24.22.0',variant='pi-memweave',package_path='/tmp/subject.tgz',package_sha256='a'*64,auth_path='',protocol='tb4',thinking='off',evaluation_deadline=1234)
    files=profile_configurations(legacy)
    assert files['settings.json']['compaction']['enabled']is False
    assert files['models.json']['providers']['deepseek']['modelOverrides']['deepseek-flash']['samplingParams']['max_tokens']==16384


def test_initialized_product_mode_uses_its_own_transaction_and_an_isolated_profile():
    script=product_initialization_script('/isolated/package','/isolated/profile','/app')
    assert 'completeSetup(paths,\\"/isolated/profile\\",loadDefaultRule' in script
    assert 'disableGlobalCompaction(\\"/app\\",\\"/isolated/profile\\")'in script
    assert 'DefaultResourceLoader'in script and 'session.prompt'not in script and '.local/share/memweave-dev'not in script


@pytest.mark.parametrize('field,value',[('thinking','off'),('evaluation_progress_after_returns',80),('evaluation_output_tokens',8192),('evaluation_task_timeouts',{'task':900}),('evaluation_task_configs',{'task':{'memweave_config':{'recent_turns':2}}})])
def test_primary_defaults_reject_hidden_experimental_overrides(field,value):
    baseline=options().model_dump();baseline[field]=value
    with pytest.raises(ValueError,match='primary_default'):PiExperimentOptions(**baseline)


def test_existing_job_builder_passes_primary_mode_without_implicit_sampling_parameters(tmp_path):
    from test_spec import configuration

    from memweave_eval.runner import build_job_config
    from memweave_eval.spec import Experiment
    c=configuration(tmp_path)
    c['model']['thinking']=None
    c['evaluation']={'gold':str(tmp_path/'gold.json'),'deadline_utc':'2026-11-06T00:00:00+00:00','admission_budget_usd':3.,'arm_budget_usd':1.,'budget_id':'unit-only','primary_default':True,'progress_after_returns':0,'output_tokens':384000}
    (tmp_path/'gold.json').write_text('{"tasks":{}}')
    spec=Experiment.model_validate(c);job=build_job_config(spec,tmp_path,'test',[],variant='pi-native',prepare_only=True)
    kwargs=job['agents'][0]['kwargs'];assert kwargs['evaluation_primary_default']is True and kwargs['evaluation_progress_after_returns']==0
    for bad in [('resources',{'cpus':1}),('progress_after_returns',80),('output_tokens',8192)]:
        c['evaluation'][bad[0]]=bad[1]
        with pytest.raises(ValueError,match='primary_default'):Experiment.model_validate(c)
        c['evaluation'].pop(bad[0]);c['evaluation'].update(progress_after_returns=0,output_tokens=384000)


def test_primary_network_probe_respects_the_original_task_policy(tmp_path):
    import asyncio
    import json
    from types import SimpleNamespace

    from memweave_eval.network_probe import check_network

    class Environment:
        async def exec(self,**kwargs):
            return SimpleNamespace(return_code=0,stdout=json.dumps({'model':{'ok':True,'status':401,'error':None},'outside':{'ok':True,'status':200,'error':None}}))

    asyncio.run(check_network(Environment(),'node',tmp_path,general_internet_allowed=True))
    r=json.loads((tmp_path/'network-probe.json').read_text());assert r['passed']and r['expected_general_internet_allowed']
    with pytest.raises(RuntimeError):asyncio.run(check_network(Environment(),'node',tmp_path))


def test_full_original_timeout_is_required_before_any_paid_authority_starts(tmp_path):
    from memweave_eval.runner import require_primary_time
    (tmp_path/'task.toml').write_text('[agent]\ntimeout_sec=28800\n[verifier]\ntimeout_sec=900\n')
    require_primary_time([tmp_path],30000,31080,now=0)
    with pytest.raises(ValueError,match='original primary actor'):
        require_primary_time([tmp_path],29000,31080,now=0)
    with pytest.raises(ValueError,match='original primary actor'):
        require_primary_time([tmp_path],30000,31079,now=0)


def test_symmetric_task_time_adaptation_requires_case_versioned_explicit_authorization(tmp_path):
    import json
    from types import SimpleNamespace as NS

    from memweave_eval.spec import primary_actor_seconds

    p=tmp_path/'contract.json';spec=NS(evaluation=NS(primary_default=True,primary_contract=p),limits=NS(max_elapsed_seconds=10800))
    p.write_text('{}');assert primary_actor_seconds(spec)is None
    contract={'case_id':'TB-01','formal_run_allowed':True,'budget_authorization':{'maximum_run_seconds':10800,'evidence_reference':'unit fixture'},
        'execution_policy':{'kind':'authorized_symmetric_time_adaptation','source_actor_seconds':28800,'actor_seconds':7200,'reason':'explicit user 3h cap'}}
    p.write_text(json.dumps(contract));assert primary_actor_seconds(spec)==7200
    for value in (0,28801,True):
        p.write_text(json.dumps(contract|{'execution_policy':contract['execution_policy']|{'actor_seconds':value}}))
        with pytest.raises(ValueError,match='symmetric time'):primary_actor_seconds(spec)
    p.write_text(json.dumps(contract|{'budget_authorization':{}}))
    with pytest.raises(ValueError,match='symmetric time'):primary_actor_seconds(spec)


def test_tb01_paid_design_hold_is_distinct_from_historical_report_recalculation():
    import json
    from pathlib import Path

    from memweave_eval.primary_report import validate_contract
    from memweave_eval.spec import require_primary_design_ready

    historical=json.loads((Path(__file__).parents[1]/'cases/TB-01/1.3.3/scoring.json').read_text())
    # Historical formulas remain readable, even though their construct is incomplete.
    validate_contract(historical)
    with pytest.raises(ValueError,match='State truth.*timely.*downstream'):
        require_primary_design_ready(historical)
    # A metadata flag is not evidence that an implementation/real CLI test exists.
    asserted=historical|{'design_ready':True,'collector_ready':True,'controls_passed':True,
        'behavior_adapter':'unimplemented-state-adapter','case_version':'1.4.0'}
    with pytest.raises(ValueError,match='TB-01 design hold'):
        require_primary_design_ready(asserted)
    with pytest.raises(ValueError,match='TB-01 design hold'):
        require_primary_design_ready(asserted|{'case_id':'renamed-label'})


def test_real_run_entry_blocks_incomplete_design_before_credential_access(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace as NS

    from memweave_eval import runner

    historical=Path(__file__).parents[1]/'cases/TB-01/1.3.3/scoring.json'
    p=tmp_path/'contract.json';p.write_text(json.dumps(json.loads(historical.read_text())))
    spec=NS(evaluation=NS(primary_default=True,primary_contract=p))
    def forbidden():raise AssertionError('credential access before design admission')
    monkeypatch.setattr(runner,'auth_file',forbidden)
    with pytest.raises(ValueError,match='TB-01 design hold'):
        runner.run_experiment(spec,None,None)
