"""Read-only evaluator-side capture using Harbor's public sidecar interface."""
from __future__ import annotations

import json

from .pi_agent import ExperimentPi
from .storage import atomic_json, file_digest


class WarrantyEvidenceMixin:
    async def capture_warranty(self,environment,phase):
        if self.options.evaluation_case_id!='TB-02':raise ValueError('warranty sidecar collector scoped to TB-02')
        folder=self.logs_dir/'warranty-evidence';folder.mkdir(exist_ok=True)
        script='''import json
from pathlib import Path
values={}
for name in ['decisions.json','decision_events.jsonl']:
 p=Path('/audit')/name
 try:
  stat=p.stat();values[name]={'status':'file'if p.is_file()and not p.is_symlink()else'unsupported','bytes':stat.st_size}
 except FileNotFoundError:values[name]={'status':'absent'}
 except OSError as error:values[name]={'status':'error','error_class':type(error).__name__}
print(json.dumps(values))
'''
        from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
        record={'phase':phase,'service':'warranty-portal','status':'UNKNOWN','files':{},
            'harbor_session_id':environment.session_id,
            'compose_project':_sanitize_docker_compose_project_name(environment.session_id)}
        try:
            import shlex
            result=await environment.service_exec('python3 -c '+shlex.quote(script),service='warranty-portal',timeout_sec=15)
            if result.return_code!=0:raise ValueError('sidecar stat failed')
            values=json.loads(result.stdout)
            if set(values)!={'decisions.json','decision_events.jsonl'}:raise ValueError('sidecar stat schema invalid')
            record.update(status='CAPTURED',files=values)
            for name,value in values.items():
                if value['status']=='file':
                    target=folder/(phase+'-'+name)
                    await environment.service_download_file('/audit/'+name,target,service='warranty-portal')
                    value.update(sha256=file_digest(target),local_file=target.name)
        except Exception as error:  # noqa: BLE001 — observation failure is explicit UNKNOWN, never success or an actor mutation
            record.update(status='UNKNOWN',error_class=type(error).__name__)
        atomic_json(folder/(phase+'-presence.json'),record,immutable=True)

    async def run(self,instruction,environment,context):
        await self.capture_warranty(environment,'initial')
        try:return await super().run(instruction,environment,context)
        finally:await self.capture_warranty(environment,'final')


class WarrantyPi(WarrantyEvidenceMixin,ExperimentPi):
    """Same Pi execution with observation only; no extra models or actor inputs."""
