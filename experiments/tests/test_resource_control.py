import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from memweave_eval.resource_control import capture_limits


def test_control_identity_and_limits_are_observed_before_the_fast_reference_exits(tmp_path):
    expected={'cpus':5,'memory_mb':16384}
    actual={'Id':'a'*64,'Image':'sha256:frozen','HostConfig':{'NanoCpus':5_000_000_000,'Memory':16*1024**3},
        'Config':{'Labels':{'com.docker.compose.project':'trusted','com.docker.compose.service':'main',
            'org.memweave.eval.run':'only-this-run'}}}
    def command(args,**kwargs):
        if args[1]=='ps':
            assert 'label=com.docker.compose.project=trusted'in args and'label=com.docker.compose.service=main'in args
            return 'a'*64+'\n'
        return json.dumps([actual])
    env=SimpleNamespace(session_id='trusted')
    with patch('memweave_eval.resource_control.subprocess.check_output',side_effect=command):
        proof=asyncio.run(capture_limits(env,tmp_path,expected,'sha256:frozen','only-this-run'))
        assert proof['actual_limits']==actual['HostConfig']
        for mutate in [lambda a:a.update(Image='sha256:sidecar'),
            lambda a:a['HostConfig'].update(Memory=8*1024**3),
            lambda a:a['Config']['Labels'].update({'org.memweave.eval.run':'other-run'})]:
            original=json.loads(json.dumps(actual));mutate(actual)
            with pytest.raises(ValueError):asyncio.run(capture_limits(env,tmp_path,expected,'sha256:frozen','only-this-run'))
            actual=original


def test_custom_oracle_receives_explicit_source_task_and_trusted_trial_paths(tmp_path):
    from harbor.agents.factory import AgentFactory
    from harbor.models.trial.config import AgentConfig

    task=tmp_path/'task';task.mkdir();(task/'instruction.md').write_text('Public control task.')
    (task/'task.toml').write_text('schema_version="1.4"\n')
    (task/'tests').mkdir();(task/'tests/test.sh').write_text('exit 1\n')
    (task/'environment').mkdir();(task/'environment/Dockerfile').write_text('FROM scratch\n')
    log=tmp_path/'trial/agent';log.mkdir(parents=True)
    config=AgentConfig(import_path='memweave_eval.resource_control:ResourceOracle',kwargs={
        'control_task_path':str(task),'control_resources':{'cpus':5,'memory_mb':16384},
        'control_image_id':'sha256:frozen','control_run_id':'only-this-run'})
    agent=AgentFactory.create_agent_from_config(config,logs_dir=log)
    assert agent._task.paths.task_dir==task
    assert agent._trial_paths.agent_dir==log
