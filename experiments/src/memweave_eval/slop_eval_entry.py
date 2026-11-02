"""Eval-only SDK configuration adapter; leaves upstream scoring code untouched."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path


def scoped_create(original,*,run_id,cpus,memory_mb,expected_image,deadline,audit):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',run_id)or type(cpus)is not int or type(memory_mb)is not int or cpus<=0 or memory_mb<=0:
        raise ValueError('invalid Slop verifier resource scope')
    def create(owner,*args,**kwargs):
        if time.time()>=deadline:raise TimeoutError('Slop verifier deadline before container creation')
        image=args[0]if args else kwargs.get('image')
        if owner.client.api.inspect_image(image)['Id']!=expected_image:
            raise ValueError('Slop verifier base image changed')
        if any(k in kwargs for k in ('nano_cpus','mem_limit')):raise ValueError('conflicting declared verifier resources')
        labels=dict(kwargs.get('labels')or{})
        if 'org.memweave.eval.run'in labels:raise ValueError('conflicting verifier run identity')
        labels['org.memweave.eval.run']=run_id
        kwargs.update(labels=labels,nano_cpus=cpus*1000000000,mem_limit=memory_mb*1024*1024)
        container=original(owner,*args,**kwargs)
        container.reload()
        actual=container.attrs['HostConfig']
        if actual.get('NanoCpus')!=kwargs['nano_cpus']or actual.get('Memory')!=kwargs['mem_limit']:
            raise ValueError('verifier container did not receive frozen resource limits')
        with audit.open('a')as stream:
            stream.write(json.dumps({'event':'verifier_container_created','container_id':container.id,
                'run_id':run_id,'image_id':expected_image,'cpus':cpus,'memory_mb':memory_mb,
                'actual_nano_cpus':actual['NanoCpus'],'actual_memory_bytes':actual['Memory'],'timestamp':time.time()})+'\n')
            stream.flush();os.fsync(stream.fileno())
        return container
    return create



def scoped_exec(original,build,*,run_id,cpus,memory_mb,expected_image,audit,client,deadline):
    from uuid import uuid4
    def command(owner,env):
        if time.time()>=deadline:raise TimeoutError('Slop verifier deadline before CLI dispatch')
        args=build(owner,env)
        if args[1:3]!=['run','--rm']:raise ValueError('unexpected pinned Docker CLI shape')
        if client.api.inspect_image(owner._image)['Id']!=expected_image:raise ValueError('Slop verifier image changed')
        owner._memweave_cidfile=audit.parent/(uuid4().hex+'.cid')
        return args[:2]+['--label','org.memweave.eval.run='+run_id,'--cpus',str(cpus),
            '--memory',str(memory_mb)+'m','--cidfile',str(owner._memweave_cidfile)]+args[3:]
    def execute(owner,*args,**kwargs):
        try:return original(owner,*args,**kwargs)
        finally:
            path=getattr(owner,'_memweave_cidfile',None)
            if path and path.exists():
                identity=path.read_text().strip()
                if not re.fullmatch(r'[a-f0-9]{64}',identity):raise ValueError('invalid verifier container ID')
                container=client.containers.get(identity);container.reload();actual=container.attrs
                if actual['Config']['Labels'].get('org.memweave.eval.run')!=run_id:raise ValueError('verifier container scope mismatch')
                limits=actual['HostConfig']
                if limits.get('NanoCpus')!=cpus*1000000000 or limits.get('Memory')!=memory_mb*1024*1024:
                    raise ValueError('verifier actual CLI resource caps missing')
                with audit.open('a')as stream:
                    stream.write(json.dumps({'event':'verifier_container_observed','backend':'actual Docker CLI',
                        'container_id':identity,'run_id':run_id,'image_id':actual['Image'],
                        'actual_nano_cpus':limits['NanoCpus'],'actual_memory_bytes':limits['Memory'],
                        'status':actual['State']['Status'],'timestamp':time.time()})+'\n')
                    stream.flush();os.fsync(stream.fileno())
                container.remove(force=True)
    return command,execute


def main():
    if sys.argv[1:3]!=['--quiet','eval-snapshot']:
        raise ValueError('This entry point permits only official offline eval-snapshot, never an agent/model command')
    import docker
    from docker.models.containers import ContainerCollection
    from slop_code.entrypoints.cli import app
    from slop_code.execution.docker_runtime.exec import DockerExecRuntime
    policy={'run_id': os.environ['MEMWEAVE_SLOP_VERIFIER_RUN'],'cpus': int(os.environ['MEMWEAVE_SLOP_VERIFIER_CPUS']),
        'memory_mb': int(os.environ['MEMWEAVE_SLOP_VERIFIER_MEMORY_MB']),'expected_image': os.environ['MEMWEAVE_SLOP_VERIFIER_IMAGE'],
        'audit': Path(os.environ['MEMWEAVE_SLOP_VERIFIER_AUDIT'])}
    ContainerCollection.create=scoped_create(ContainerCollection.create,**policy,
        deadline=float(os.environ['MEMWEAVE_SLOP_VERIFIER_DEADLINE']))
    DockerExecRuntime._build_docker_run_command,DockerExecRuntime.execute=scoped_exec(
        DockerExecRuntime.execute,DockerExecRuntime._build_docker_run_command,**policy,client=docker.from_env(),deadline=float(os.environ['MEMWEAVE_SLOP_VERIFIER_DEADLINE']))
    try:return app()
    finally:
        if not policy['audit'].exists():raise RuntimeError('official evaluator ran without actual container-scope proof')


if __name__=='__main__':main()
