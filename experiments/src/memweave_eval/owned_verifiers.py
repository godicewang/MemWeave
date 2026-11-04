"""Read-only discovery of unlabeled verifiers from a frozen formal admission.

Never discovers arbitrary host processes or adopts a project merely by prefix.
Only Harbor's exact trial configuration, source stage and declared image qualify.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

from .storage import file_digest


def running_containers(root,run_id,command):
    root=Path(root)
    invoke=command
    def command(args):
        try:return invoke(args)
        except (OSError,subprocess.SubprocessError):return SimpleNamespace(returncode=124,stdout='')
    selected=command(['ps','--filter','label=org.memweave.eval.run='+run_id,'--format','{{.ID}}'])
    actors=selected.stdout.split()if selected.returncode==0 else None
    result={'complete':actors is not None,'identities':actors,'actor_identities':actors,'verifier_proofs':[]}
    if actors is None:return dict(result,reason='run-label Docker query failed')
    admission=root/'admission.json'
    if not admission.exists():return result  # Existing explicitly run-labelled controls.
    try:
        lock=root/'experiment.lock.json'
        if root.name!=run_id or admission.is_symlink()or lock.is_symlink()or \
                json.loads(lock.read_text()).get('admission_sha256')!=file_digest(admission):
            raise ValueError('formal run/admission lock identity differs')
        record=json.loads(admission.read_text());case=record['case_id'];task=Path(record['task_path'])
        if not isinstance(case,str)or not re.fullmatch('[A-Za-z0-9_-]+',case)or not task.is_absolute():
            raise ValueError('formal case/task identity invalid')
        declaration=tomllib.loads((task/'task.toml').read_text());base=declaration.get('verifier',{})
        stages=declaration.get('steps')or[{'name':'trial'}];projects={}
        for arm in ['pi-native','pi-memweave']:
            job=root/'harbor'/(case.lower()+'-'+arm)
            for path in sorted(job.glob('*/config.json')):
                if path.is_symlink()or not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError('redirected trusted trial configuration')
                config=json.loads(path.read_text());name=config.get('trial_name');options=config.get('agent',{}).get('kwargs',{})
                if name!=path.parent.name or not isinstance(name,str)or not re.fullmatch('[A-Za-z0-9_-]+',name)or \
                        not name.startswith(task.name+'__')or config.get('task',{}).get('path')!=str(task)or \
                        options.get('variant')!=arm or options.get('evaluation_case_id')!=case or \
                        options.get('evaluation_run_id')!='fixed35-formal:'+run_id+':'+case:
                    raise ValueError('trusted trial identity differs from frozen admission')
                for stage in stages:
                    override=stage.get('verifier',{});mode=override.get('environment_mode',base.get('environment_mode','same'))
                    if mode!='separate':continue
                    stage_name=stage['name']
                    if not isinstance(stage_name,str)or not re.fullmatch('[A-Za-z0-9_-]+',stage_name):
                        raise ValueError('source verifier stage identity invalid')
                    environment=override.get('environment')or base.get('environment')or declaration['environment']
                    image=environment.get('docker_image')
                    if not isinstance(image,str)or not image:raise ValueError('declared verifier image unavailable')
                    projects[name.lower()+'__verifier__'+stage_name.lower()]={
                        'image':image,'trial_config':str(path),'trial_config_sha256':file_digest(path)}
        identities=set(actors);proofs=[]
        for project,proof in projects.items():
            found=command(['ps','--filter','label=com.docker.compose.project='+project,
                '--filter','label=com.docker.compose.service=main','--format','{{.ID}}'])
            if found.returncode:raise ValueError('verifier Docker query failed')
            for identity in found.stdout.split():
                response=command(['inspect',identity])
                if response.returncode:raise ValueError('verifier Docker inspect failed')
                data=json.loads(response.stdout)
                if not isinstance(data,list)or len(data)!=1:raise ValueError('nonunique verifier inspection')
                container=data[0];labels=container.get('Config',{}).get('Labels',{})
                if not container.get('Id','').startswith(identity)or labels.get('com.docker.compose.project')!=project or \
                        labels.get('com.docker.compose.service')!='main'or container.get('Config',{}).get('Image')!=proof['image']:
                    raise ValueError('verifier project/service/image ownership mismatch')
                running=container.get('State',{}).get('Running')
                if type(running)is not bool:raise ValueError('verifier running state unavailable')
                if running:
                    identities.add(identity);proofs.append(dict(proof,project=project,container_id=container['Id'],
                        actual_image_id=container.get('Image')))
        return dict(result,identities=sorted(identities),verifier_proofs=proofs)
    except (OSError,ValueError,TypeError,KeyError)as error:
        return dict(result,complete=False,identities=None,reason=str(error))
