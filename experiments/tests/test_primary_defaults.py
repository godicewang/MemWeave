import pytest

from memweave_eval.pi_agent import (
    PiExperimentOptions,
    product_initialization_script,
    profile_configurations,
)


def options(**changes):
    return PiExperimentOptions(node_version='24.22.0',variant='pi-memweave',package_path='/tmp/subject.tgz',package_sha256='a'*64,auth_path='',protocol='tb4',evaluation_primary_default=True,evaluation_output_tokens=384000,**changes)


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


@pytest.mark.parametrize('field,value',[('thinking','off'),('evaluation_output_tokens',8192)])
def test_primary_defaults_reject_hidden_experimental_overrides(field,value):
    baseline=options().model_dump();baseline[field]=value
    with pytest.raises(ValueError,match='primary_default'):PiExperimentOptions(**baseline)




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
