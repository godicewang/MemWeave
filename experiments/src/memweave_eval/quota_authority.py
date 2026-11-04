"""Lifecycle of this campaign's networkless single-VM quota authority."""
from __future__ import annotations

import fcntl
import json
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from .storage import atomic_json, file_digest

IMAGE='sha256:cb4e0191a826721756232acb2dac5bccf119895449869ce28094d085cd38710f'


def active_authority(root:Path):
    """Keep the first manifest immutable; accept one explicitly bound recovery."""
    base=root/'authority.json';proof=root/'authority-recovery.json'
    if base.is_symlink()or proof.is_symlink():raise ValueError('redirected authority manifest')
    original=json.loads(base.read_text())
    if not proof.exists():return original
    value=json.loads(proof.read_text())
    if value.get('base_authority_sha256')!=file_digest(base):raise ValueError('recovery base manifest differs')
    record=value.get('authority')
    if not isinstance(record,dict)or any(record.get(k)!=original.get(k)for k in
        ['service_id','root','ledger','budget_id','image_id','subbudgets_usd']):
        raise ValueError('recovery identity or money policy differs')
    return record


def recover_authority(root:Path,env):
    """Explicit stopped-writer recovery, same auth and ledger, admission held."""
    original=json.loads((root/'authority.json').read_text())
    old=subprocess.run(['docker','inspect','--format','{{json .State}}',original['container_id']],
        env=env,capture_output=True,text=True,timeout=15,check=False)
    if old.returncode!=1 or not any(s in old.stderr.lower()for s in ['no such object','no such container']):
        raise RuntimeError('old writer absence not confirmed')
    check=subprocess.run(['docker','ps','-a','--filter','label=org.memweave.eval.quota='+original['budget_id'],
        '--format','{{.ID}}'],env=env,capture_output=True,text=True,timeout=15,check=False)
    if check.returncode!=0 or check.stdout.strip():raise RuntimeError('unique writer absence not confirmed')
    if (root/'authority-recovery.json').exists()or(root/'recovery-request.json').exists():
        raise RuntimeError('recovery already requested; reconcile outcome, never duplicate writer')
    if original['image_id']!=IMAGE or not(root/'admission-paused.json').is_file():
        raise ValueError('trusted paused authority required')
    if (root/'stop').exists():raise RuntimeError('prior stop request must be reconciled before recovery')
    ledger=Path(original['ledger'])
    if json.loads(ledger.read_text())['deadline']<=time.time():raise RuntimeError('budget deadline already passed')
    before=file_digest(ledger);directory=root/'recovery-code-v1'
    directory.mkdir(exist_ok=False);hashes={}
    for name in ('quota_service.py','budget_guard.py'):
        shutil.copy2(Path(__file__).with_name(name),directory/name);hashes[name]=file_digest(directory/name)
    if hashes['budget_guard.py']!=original['code_sha256']['budget_guard.py']:
        raise ValueError('recovery must preserve original money logic')
    began=time.time();name='memweave-quota-'+original['service_id'][:12]+'-recovery1'
    atomic_json(root/'recovery-request.json',{'base_authority_sha256':file_digest(root/'authority.json'),
        'container_name':name,'ledger_before_sha256':before,'requested_at':began,'admission_remains_paused':True},immutable=True)
    container=subprocess.check_output(['docker','run','--detach','--platform','linux/amd64','--name',name,
        '--label','org.memweave.eval.quota='+original['budget_id'],'--network','none','--cpus','.25','--memory','128m',
        '--mount','type=bind,source='+str(root)+',target=/control',
        '--mount','type=bind,source='+str(ledger.parent)+',target=/control/ledger',
        IMAGE,'python3','/control/recovery-code-v1/quota_service.py','/control',original['service_id']],env=env,text=True,timeout=30).strip()
    atomic_json(root/'recovery-starting.json',{'container_id':container,'requested_at':began},immutable=True)
    until=time.time()+20
    while time.time()<until:
        heartbeat=json.loads((root/'heartbeat.json').read_text())
        if heartbeat.get('service_id')==original['service_id']and heartbeat.get('timestamp',0)>=began:break
        time.sleep(.05)
    else:raise RuntimeError('recovered authority heartbeat unconfirmed; inspect retained container, do not retry')
    if file_digest(ledger)!=before:raise RuntimeError('ledger changed during held recovery; audit before using')
    record=dict(original,container_id=container,code_sha256=hashes,recovered_at=began,retained_for_diagnostics=True)
    atomic_json(root/'authority-recovery.json',{'base_authority_sha256':file_digest(root/'authority.json'),
        'authority':record,'ledger_unchanged_sha256':before,'auth_identity_unchanged':True,
        'admission_remains_paused':True},immutable=True)
    return record


def start_authority(root:Path,ledger:Path,env):
    root.parent.mkdir(parents=True,exist_ok=True)
    # Only Mac controller processes create the service; this lock never guards
    # ledger writes and therefore does not cross a kernel boundary.
    with root.with_suffix('.startup.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _start_authority(root,ledger,env)


def _start_authority(root:Path,ledger:Path,env):
    manifest=root/'authority.json'
    if manifest.exists():
        record=active_authority(root)
        actual=json.loads(subprocess.check_output(['docker','inspect',record['container_id']],env=env,text=True,timeout=15))[0]
        if record['ledger']!=str(ledger)or not actual['State']['Running']or actual['Image']!=IMAGE or actual['Config']['Labels'].get('org.memweave.eval.quota')!=record.get('budget_id','fixed35-20261102'):
            raise RuntimeError('quota authority identity or lifecycle mismatch')
        heartbeat=json.loads((root/'heartbeat.json').read_text())
        if heartbeat['service_id']!=record['service_id']or not -5<time.time()-heartbeat['timestamp']<10:
            raise RuntimeError('quota authority heartbeat is stale or inconsistent')
        for name,digest in record['code_sha256'].items():
            if file_digest(Path(__file__).with_name(name))!=digest:
                raise RuntimeError('quota authority version differs; stop and audit before replacing a live writer')
        return record
    root.mkdir(parents=True,exist_ok=False)
    for name in ['configs','channels','code']:(root/name).mkdir()
    hashes={}
    for name in ('quota_service.py','budget_guard.py'):
        shutil.copy2(Path(__file__).with_name(name),root/'code'/name)
        hashes[name]=file_digest(root/'code'/name)
    identity=uuid4().hex;budget_id=ledger.parent.name
    container=subprocess.check_output(['docker','run','--rm','--detach','--platform','linux/amd64',
        '--name','memweave-quota-'+identity[:12],'--label','org.memweave.eval.quota='+budget_id,
        '--network','none','--cpus','.25','--memory','128m',
        '--mount','type=bind,source='+str(root)+',target=/control',
        '--mount','type=bind,source='+str(ledger.parent)+',target=/control/ledger',
        IMAGE,'python3','/control/code/quota_service.py','/control',identity],env=env,text=True,timeout=30).strip()
    atomic_json(root/'starting.json',{'container_id':container,'service_id':identity,'image_id':IMAGE},immutable=True)
    deadline=time.time()+20
    while time.time()<deadline:
        heartbeat=root/'heartbeat.json'
        if heartbeat.exists()and json.loads(heartbeat.read_text()).get('service_id')==identity:break
        time.sleep(.05)
    else:
        raise RuntimeError('quota authority has no verified startup heartbeat')
    account=json.loads(ledger.read_text())
    record={'service_id':identity,'container_id':container,'root':str(root),'ledger':str(ledger),'budget_id':budget_id,
        'image_id':IMAGE,'code_sha256':hashes,'network':'none','single_writer_kernel':'Docker VM',
        'started_at':time.time(),'subbudgets_usd':{'arm_limits':account['arm_limits'],
            'all_operations_hard_limit':account['maximum_usd']}}
    atomic_json(manifest,record,immutable=True)
    return record


def add_channel(authority,*,arm,episode,max_output,deadline,episode_budget=None,max_requests=None,role='actor'):
    root=Path(authority['root']);identity=uuid4().hex;channel=root/'channels'/identity
    channel.mkdir()
    for name in ('requests','responses'):
        directory=channel/name;directory.mkdir();directory.chmod(0o1777)
    client={'service_id':authority['service_id'],'channel_id':identity,'token':secrets.token_hex(32),'protocol':2}
    atomic_json(channel/'client.json',client,immutable=True);(channel/'client.json').chmod(0o644)
    config={**client,'arm':arm,'episode':episode,'id_prefix':episode+':'+arm+':',
        'max_output':max_output,'deadline':deadline,'episode_budget':episode_budget,
        'max_requests':max_requests,'role':role}
    atomic_json(root/'configs'/(identity+'.json'),config,immutable=True)
    until=time.time()+20
    while time.time()<until:
        ready=channel/'ready.json'
        if ready.exists()and json.loads(ready.read_text())=={'service_id':authority['service_id'],'channel_id':identity,'protocol':2}:
            return {'host_path':str(channel),'container_path':'/opt/memweave-eval-control',
                'service_id':authority['service_id'],'channel_id':identity}
        time.sleep(.05)
    raise RuntimeError('quota channel handshake unavailable; no model admission permitted')


def stop_authority(authority,env):
    root=Path(authority['root']);identity=authority['container_id']
    actual=json.loads(subprocess.check_output(['docker','inspect',identity],env=env,text=True,timeout=15))[0]
    if actual['Config']['Labels'].get('org.memweave.eval.quota')!=authority.get('budget_id','fixed35-20261102'):
        raise ValueError('refusing to stop an unrelated container')
    (root/'stop').touch()
    stopped=False
    for _ in range(40):
        check=subprocess.run(['docker','ps','--filter','id='+identity,'--format','{{.ID}}'],env=env,
            capture_output=True,text=True,timeout=10,check=False)
        if check.returncode==0 and not check.stdout.strip():stopped=True;break
        time.sleep(.1)
    if not stopped:
        subprocess.run(['docker','stop','--time','5',identity],env=env,capture_output=True,text=True,timeout=15,check=False)
        check=subprocess.run(['docker','ps','--filter','id='+identity,'--format','{{.ID}}'],env=env,
            capture_output=True,text=True,timeout=10,check=False)
        stopped=check.returncode==0 and not check.stdout.strip()
    atomic_json(root/'stop-proof.json',{'container_id':identity,'confirmed_stopped':stopped,'timestamp':time.time()},immutable=True)
    if not stopped:raise RuntimeError('quota authority stop unconfirmed')
