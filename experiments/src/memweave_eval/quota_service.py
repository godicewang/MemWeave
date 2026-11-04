"""Single-VM writer for the existing ledger; cross-kernel flock is not a lock."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from .budget_guard import INPUT_LIMIT, INPUT_USD, OUTPUT_USD, change
except ImportError:  # Copied verbatim beside budget_guard.py in the isolated VM.
    from budget_guard import INPUT_LIMIT, INPUT_USD, OUTPUT_USD, change


def write_json(path,value):
    temporary=path.with_name(path.name+'.partial')
    with temporary.open('w')as stream:
        json.dump(value,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    temporary.chmod(0o644);temporary.replace(path)


def apply_scoped(ledger,config,request,*,now=None,admission_paused=False):
    if not hmac.compare_digest(str(request.get('token','')),config['token']):
        raise ValueError('channel_authentication_failed')
    operation=request.get('operation')
    if not isinstance(operation,dict)or operation.get('action')not in {'reserve','settle'}:
        raise ValueError('invalid_quota_operation')
    identity=operation.get('id')
    if not isinstance(identity,str)or not identity.startswith(config['id_prefix']):
        raise ValueError('channel_request_identity_mismatch')
    if operation['action']=='reserve':
        if admission_paused:raise ValueError('authority_admission_paused')
        if operation.get('arm')!=config['arm']or operation.get('episode')!=config['episode']:
            raise ValueError('reservation_scope_mismatch')
        if (time.time()if now is None else now)>=config['deadline']:
            raise ValueError('channel_deadline_reached')
        if type(operation.get('max_output'))is not int or not 0<operation['max_output']<=config['max_output']:
            raise ValueError('channel_output_limit_reached')
        operation=dict(operation,arm=config['arm'],episode=config['episode'],
            episode_budget=config.get('episode_budget'),max_requests=config.get('max_requests'))
        if config['arm']in {'pi-native','pi-memweave'}and config['episode'].startswith('fixed35-formal:'):
            judge=config['episode'].endswith(':judge');limit=1. if judge else 7.99
            previous=json.loads(ledger.read_text())['requests'].values()
            spent=sum(r['charge_usd']for r in previous if r.get('arm')==config['arm']and
                r.get('episode','').startswith('fixed35-formal:')and r['episode'].endswith(':judge')==judge)
            if spent+INPUT_LIMIT*INPUT_USD+operation['max_output']*OUTPUT_USD>limit:
                raise ValueError('protected_judge_or_work_subbudget_reached')
    else:
        previous=json.loads(ledger.read_text())['requests'].get(identity)
        if not previous or previous.get('arm')!=config['arm']or previous.get('episode')!=config['episode']:
            raise ValueError('settlement_scope_mismatch')
    return change(ledger,operation,now=now)


def serve(root:Path,service_id):
    ledger=root/'ledger/quota.json';configs=root/'configs';channels=root/'channels'
    journal=root/'service-audit.jsonl';last_heartbeat=0
    hard_stop=json.loads(ledger.read_text())['deadline']+1200
    while not (root/'stop').exists() and time.time()<hard_stop:
        for source in sorted(configs.glob('*.json')):
            if source.is_symlink():raise ValueError('redirected private quota config')
            try:config=json.loads(source.read_text())
            except FileNotFoundError:
                write_json(root/'configuration-read-fault.json',{'reason':'private_config_temporarily_missing',
                    'channel_id':source.stem,'timestamp':time.time()})
                continue  # No authorization/default config; this channel stays closed.
            identity=source.stem
            if not re.fullmatch(r'[a-f0-9]{32}',identity)or config['service_id']!=service_id:
                raise ValueError('invalid private quota scope')
            if config.get('protocol')!=2:raise ValueError('unsupported private quota protocol')
            channel=channels/identity
            ready=channel/'ready.json'
            if not ready.exists():write_json(ready,{'service_id':service_id,'channel_id':identity,'protocol':2})
            for incoming in sorted((channel/'requests').glob('*.json')):
                nonce=incoming.stem;response=channel/'responses'/incoming.name
                if response.exists():continue
                before=hashlib.sha256(ledger.read_bytes()).hexdigest()
                request={}
                try:
                    payload=incoming.with_suffix('.payload')
                    if not re.fullmatch(r'[a-f0-9-]{36}',nonce)or incoming.is_symlink()or incoming.stat().st_size!=0:
                        raise ValueError('invalid_quota_IPC_request')
                    if payload.is_symlink()or not 0<payload.stat().st_size<=32768:
                        raise ValueError('invalid_quota_IPC_payload')
                    parsed=json.loads(payload.read_text())
                    if not isinstance(parsed,dict):raise TypeError('invalid_quota_IPC_object')
                    request=parsed
                    if request.get('nonce')!=nonce:raise ValueError('request_nonce_mismatch')
                    marker=root/'admission-paused.json'
                    result=apply_scoped(ledger,config,request,
                        admission_paused=marker.exists()or marker.is_symlink())
                    out={'ok':True,'record':result}
                except (ValueError,KeyError,TypeError,TimeoutError,OSError)as error:
                    # All errors originate in the small, evaluator-only quota protocol.
                    out={'ok':False,'error_class':type(error).__name__,
                        'reason':str(error)if isinstance(error,(ValueError,TimeoutError))else'quota_storage_or_protocol_failure'}
                out.update(nonce=nonce,service_id=service_id)
                audit={'channel_id':identity,'nonce':nonce,'operation':request.get('operation',{}).get('action'),
                    'request_id':request.get('operation',{}).get('id'),'ok':out['ok'],
                    'ledger_before_sha256':before,'ledger_after_sha256':hashlib.sha256(ledger.read_bytes()).hexdigest(),
                    'timestamp':time.time()}
                with journal.open('a')as stream:
                    stream.write(json.dumps(audit)+'\n');stream.flush();os.fsync(stream.fileno())
                write_json(response,out)
        if time.time()-last_heartbeat>=1:
            write_json(root/'heartbeat.json',{'service_id':service_id,'timestamp':time.time()});last_heartbeat=time.time()
        time.sleep(.01)
    write_json(root/'service-exit.json',{'service_id':service_id,'timestamp':time.time(),
        'reason':'requested_stop'if (root/'stop').exists()else'hard_deadline'})


if __name__=='__main__':
    serve(Path(sys.argv[1]),sys.argv[2])
