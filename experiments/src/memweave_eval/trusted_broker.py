"""Task-scoped host controller for the credential-isolated Linux authority."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .storage import atomic_json, file_digest


class TrustedBroker:
    def __init__(self,root,control,run_id,image,env):
        self.root=Path(root);self.control=Path(control);self.run_id=run_id;self.image=image;self.env=env;self.process=None;self.container_id=None;self._stop_result=None
    def docker(self,args,*,timeout=20):
        return subprocess.run(['docker',*args],env=self.env,text=True,capture_output=True,timeout=timeout,check=False)
    def start(self,credential,principals,*,fixture=False):
        try:return self._start(credential,principals,fixture=fixture)
        except BaseException:
            if self.process is not None:self.stop()
            raise
    def _start(self,credential,principals,*,fixture=False):
        self.root.mkdir(parents=True,exist_ok=False);self.control.mkdir(parents=True,exist_ok=True)
        code=self.root/'code/memweave_eval';code.mkdir(parents=True);(code/'__init__.py').write_text('')
        for name in ('primary_transport.py','budget_guard.py','storage.py','container_deadline.py'):shutil.copyfile(Path(__file__).with_name(name),code/name)
        capabilities={secrets.token_urlsafe(32):p for p in principals};self.clients={}
        self.stdout=(self.root/'service-console.log').open('wb');cid=self.root/'container.cid'
        args=['docker','run','--rm','--init','--interactive','--network','host','--cpus','.5','--memory','256m','--ulimit','core=0','--platform','linux/amd64',
              '--label','org.memweave.eval.broker_run='+self.run_id,'--cidfile',str(cid),'-v',str(code.parent)+':/eval:ro','-v',str(self.control.resolve())+':/control:rw',
              '--env','PYTHONPATH=/eval','--entrypoint','python3',self.image,'-m','memweave_eval.primary_transport']
        self.process=subprocess.Popen(args,env=self.env,stdin=subprocess.PIPE,stdout=self.stdout,stderr=subprocess.STDOUT,start_new_session=True)
        atomic_json(self.root/'controller-start.json',{'controller_pid':os.getpid(),'child_pid':self.process.pid,'child_group':self.process.pid,'run_id':self.run_id,
            'image':self.image,'fixture':fixture,'code_sha256':{n.name:file_digest(n)for n in code.glob('*.py')}},immutable=True)
        payload={'control':'/control','api_key':credential,'capabilities':capabilities,'fixture':fixture}
        self.process.stdin.write(json.dumps(payload).encode()+b'\n');self.process.stdin.flush();self.process.stdin.close()
        until=time.monotonic()+45
        while time.monotonic()<until:
            if self.process.poll()is not None:raise RuntimeError('trusted authority startup failed; inspect sanitized local console')
            if (self.control/'broker-ready.json').is_file()and cid.is_file():break
            time.sleep(.1)
        else:raise TimeoutError('trusted authority readiness timed out')
        self.container_id=cid.read_text().strip();q=self.docker(['inspect',self.container_id])
        if q.returncode:raise RuntimeError('trusted authority identity unavailable')
        d=json.loads(q.stdout)[0]
        if d['Config']['Labels'].get('org.memweave.eval.broker_run')!=self.run_id or d['HostConfig'].get('PidMode')=='host':raise ValueError('authority scope or PID namespace mismatch')
        ready=json.loads((self.control/'broker-ready.json').read_text())
        if ready['pid']<=1:raise ValueError('trusted authority must have an independently addressable child PID')
        self.url='http://memweave-broker.internal:'+str(ready['port'])
        for capability,p in capabilities.items():
            client={'url':self.url,'capability':capability,'arm':p['arm'],'episode':p['episode']}
            path=self.root/('client-'+str(len(self.clients))+'.json');atomic_json(path,client,immutable=True);path.chmod(0o600);self.clients[(p['episode'],p['arm'])]=path
        atomic_json(self.root/'service-identity.json',{'container_id':d['Id'],'image_id':d['Image'],'pid_mode':d['HostConfig'].get('PidMode'),
            'network_mode':d['HostConfig']['NetworkMode'],'provider_secret_in_environment':any(credential in s for s in d['Config'].get('Env',[])),
            'provider_secret_in_arguments':credential in json.dumps(d['Config'].get('Cmd')),'port':ready['port']},immutable=True)
        return self
    def stop(self):
        if self._stop_result is not None:return dict(self._stop_result)
        result={'stopped':False,'terminal_available':False}
        (self.control/'STOP_REQUESTED').touch()
        try:
            cid=self.root/'container.cid'
            if self.container_id is None and cid.is_file():
                candidate=cid.read_text().strip();query=self.docker(['inspect',candidate])
                if query.returncode==0 and json.loads(query.stdout)[0]['Config']['Labels'].get('org.memweave.eval.broker_run')==self.run_id:self.container_id=candidate
            if self.container_id:
                q=self.docker(['stop','--time','15',self.container_id]);result['docker_stop_code']=q.returncode
                check=self.docker(['ps','--filter','id='+self.container_id,'--format','{{.ID}}'])
                result['stopped']=check.returncode==0 and not check.stdout.strip()
                until=time.monotonic()+5
                while time.monotonic()<until:
                    removed=self.docker(['ps','-a','--filter','id='+self.container_id,'--format','{{.ID}}'])
                    if removed.returncode==0 and not removed.stdout.strip():result['removed']=True;break
                    time.sleep(.1)
            elif self.process and self.process.poll()is None:
                os.killpg(self.process.pid,signal.SIGTERM)
            if self.process:
                try:self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
            result['terminal_available']=(self.control/'transport-terminal.json').is_file()
        finally:
            if hasattr(self,'stdout'):self.stdout.close()
            atomic_json(self.root/'controller-end.json',result,immutable=True)
            self._stop_result=dict(result)
        return result
