"""Free oracle/nop controls with synchronous trusted-container resource receipts.

This wraps original Harbor controls without changing their solution or verifier.
There is no model provider, credential or background polling race here.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from harbor.agents.nop import NopAgent
from harbor.agents.oracle import OracleAgent
from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
from harbor.models.trial.paths import TrialPaths

from .actor_resources import verify_actor_limits
from .storage import atomic_json


async def capture_limits(environment,logs_dir,expected,image_id,run_id):
    project=_sanitize_docker_compose_project_name(environment.session_id)
    raw=await asyncio.to_thread(subprocess.check_output,['docker','ps','--filter',
        'label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=main',
        '--format','{{.ID}}'],text=True,timeout=15)
    candidates=raw.splitlines()
    if len(candidates)!=1 or not re.fullmatch(r'[a-f0-9]{12,64}',candidates[0]):
        raise ValueError('unique control main container identity unavailable')
    actual=json.loads(await asyncio.to_thread(subprocess.check_output,
        ['docker','inspect',candidates[0]],text=True,timeout=15))[0]
    labels=actual.get('Config',{}).get('Labels',{})
    if labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.service')!='main' \
            or labels.get('org.memweave.eval.run')!=run_id:
        raise ValueError('control container labels differ from trusted run')
    if actual.get('Image')!=image_id:raise ValueError('control actual image differs from frozen image')
    limits=verify_actor_limits(actual.get('HostConfig'),expected)
    record={'timestamp':datetime.now(UTC).isoformat(),'phase':'before_original_control',
        'container_id':actual['Id'],'image_id':actual['Image'],'run_id':run_id,
        'actual_limits':limits['actual'],'expected_limits':limits['expected'],
        'trusted_project':project,'real_model_requests':0}
    atomic_json(logs_dir/'actual-resource-limits.json',record)
    return record


class ResourceMixin:
    def __init__(self,*,control_resources,control_image_id,control_run_id,**kwargs):
        self._control_resources=control_resources;self._control_image_id=control_image_id
        self._control_run_id=control_run_id
        super().__init__(**kwargs)

    async def setup(self,environment):
        await capture_limits(environment,self.logs_dir,self._control_resources,
            self._control_image_id,self._control_run_id)
        await super().setup(environment)


class ResourceOracle(ResourceMixin,OracleAgent):
    def __init__(self,*,control_task_path,logs_dir,**kwargs):
        # Harbor only adds these arguments for its built-in `oracle` name,
        # whereas this wrapper is selected by import_path. Recover them from
        # the explicit source task and Harbor's trusted agent log directory.
        logs_dir=Path(logs_dir)
        if logs_dir.name!='agent' or not Path(control_task_path).is_absolute():
            raise ValueError('trusted control task and trial paths required')
        super().__init__(logs_dir=logs_dir,task_dir=Path(control_task_path),
            trial_paths=TrialPaths(logs_dir.parent),**kwargs)


class ResourceNop(ResourceMixin,NopAgent):
    pass
