import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from memweave_eval.budget_guard import initialize
from memweave_eval.quota_service import apply_scoped


def config():
    return {'protocol':2,'token':'secret-fixture-only','arm':'a','episode':'e','id_prefix':'e:a:',
        'deadline':2000,'max_output':128,'episode_budget':.9,'max_requests':2}


def test_scope_deadline_output_retry_and_unknown_reservation(tmp_path):
    ledger=tmp_path/'quota.json';initialize(ledger,1.,2000)
    c=config();operation={'action':'reserve','id':'e:a:r','max_output':128,'arm':'a','episode':'e'}
    request={'token':c['token'],'operation':operation}
    assert apply_scoped(ledger,c,request,now=1000)['status']=='reserved'
    for bad in [dict(request,token='wrong'),dict(request,operation=dict(operation,id='foreign:a:r')),
                dict(request,operation=dict(operation,id='e:a:other',arm='b')),
                dict(request,operation=dict(operation,id='e:a:other',max_output=129))]:
        with pytest.raises(ValueError):apply_scoped(ledger,c,bad,now=1000)
    with pytest.raises(ValueError):apply_scoped(ledger,c,request,now=1000)
    with pytest.raises(ValueError):apply_scoped(ledger,c,dict(request,operation=dict(operation,id='e:a:late')),now=2000)
    settle={'token':c['token'],'operation':{'action':'settle','id':'e:a:r','input':100,'output':1,'cache_input':0}}
    assert apply_scoped(ledger,c,settle,now=1001)['status']=='settled'
    assert apply_scoped(ledger,c,settle,now=1002)['status']=='settled'


def test_node_ipc_uses_single_writer_and_absent_service_dispatches_zero(tmp_path):
    from uuid import uuid4

    from memweave_eval.storage import atomic_json
    code=Path(__file__).parents[1]/'src/memweave_eval'
    for d in ('ledger','configs','channels'):(tmp_path/d).mkdir()
    ledger=tmp_path/'ledger/quota.json';initialize(ledger,1.,time.time()+60)
    identity=uuid4().hex;channel=tmp_path/'channels'/identity;channel.mkdir()
    for d in ('requests','responses'):(channel/d).mkdir()
    c=dict(config(),deadline=time.time()+60,service_id='fixture-service',channel_id=identity)
    atomic_json(tmp_path/'configs'/(identity+'.json'),c)
    atomic_json(channel/'client.json',{k:c[k]for k in ('token','service_id','channel_id','protocol')})
    script="""import {installGuard} from GUARD;
let dispatches=0;const f=installGuard({ledger:CHANNEL,trace:TRACE,deadline:DEADLINE,variant:'a',quotaScript:IPC,
fetchImpl:async()=>{dispatches++;return new Response('data: {"usage":{"prompt_tokens":100,"completion_tokens":1}}\\n\\ndata: [DONE]\\n\\n');}});
try{await(await f('https://api.deepseek.com/chat/completions',{method:'POST',body:JSON.stringify({model:'deepseek-flash',stream:true,max_tokens:128,messages:[]})})).text();}catch{}
console.log(dispatches);
"""
    for key,value in {'GUARD':str(code/'fetch_guard.mjs'),'CHANNEL':str(channel),'TRACE':str(tmp_path/'trace.jsonl'),'IPC':str(code/'quota_ipc.mjs')}.items():script=script.replace(key,json.dumps(value))
    script=script.replace('DEADLINE',str(time.time()+60))
    env=dict(os.environ,MEMWEAVE_EVAL_RUN_ID='e')
    absent=subprocess.run(['node','--input-type=module','-e',script],env=env,capture_output=True,text=True,timeout=5,check=False)
    assert absent.returncode==0 and absent.stdout.strip()=='0'
    assert not json.loads(ledger.read_text())['requests']
    service=subprocess.Popen([sys.executable,str(code/'quota_service.py'),str(tmp_path),'fixture-service'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        until=time.time()+3
        while not (channel/'ready.json').exists()and time.time()<until:time.sleep(.01)
        # A completely written but unpublished payload must not be admitted.
        orphan=channel/'requests'/(str(uuid4())+'.payload')
        orphan.write_text(json.dumps({'operation':{'action':'reserve','id':'e:a:orphan'}}))
        time.sleep(.05)
        assert not json.loads(ledger.read_text())['requests']
        positive=subprocess.run(['node','--input-type=module','-e',script],env=env,capture_output=True,text=True,timeout=5,check=False)
        assert positive.returncode==0,positive.stderr
        assert positive.stdout.strip()=='1'
        assert next(iter(json.loads(ledger.read_text())['requests'].values()))['status']=='settled'
    finally:
        (tmp_path/'stop').touch();service.communicate(timeout=5)


def test_formal_judge_pool_is_reserved_independently_of_work(tmp_path):
    ledger=tmp_path/'quota.json';initialize(ledger,19.,2000,arm_limits={'pi-native':9.})
    account=json.loads(ledger.read_text())
    account['requests']={'old':{'status':'settled','charge_usd':7.8,'arm':'pi-native','episode':'fixed35-formal:work'}}
    ledger.write_text(json.dumps(account))
    work=dict(config(),arm='pi-native',episode='fixed35-formal:e',id_prefix='fixed35-formal:e:pi-native:')
    request={'token':work['token'],'operation':{'action':'reserve','id':work['id_prefix']+'r',
        'max_output':128,'arm':'pi-native','episode':work['episode']}}
    with pytest.raises(ValueError,match='protected_judge'):apply_scoped(ledger,work,request,now=1000)
    judge=dict(work,episode='fixed35-formal:e:judge',id_prefix='fixed35-formal:e:judge:pi-native:')
    request['operation'].update(id=judge['id_prefix']+'r',episode=judge['episode'])
    assert apply_scoped(ledger,judge,request,now=1000)['status']=='reserved'


@pytest.mark.parametrize('method,phase',[('fsyncSync','sync_request'),('marker','publish_request')])
def test_ipc_filesystem_failure_identifies_phase_and_never_publishes(tmp_path,method,phase):
    code=Path(__file__).parents[1]/'src/memweave_eval/quota_ipc.mjs'
    for folder in ('requests','responses'):(tmp_path/folder).mkdir()
    for name in ('client','ready'):
        (tmp_path/(name+'.json')).write_text(json.dumps({'protocol':2,'service_id':'s','channel_id':'c','token':'fixture'}))
    hook=tmp_path/'fault.mjs'
    patch=("const open=fs.openSync;fs.openSync=(p,...a)=>{if(String(p).endsWith('.json'))throw Object.assign(Error('fixture failure'),{code:'EPERM'});return open(p,...a)};"
        if method=='marker'else"fs.fsyncSync=()=>{throw Object.assign(Error('fixture failure'),{code:'EPERM'});};")
    hook.write_text("import fs from 'node:fs';"+patch)
    result=subprocess.run(['node','--import',str(hook),str(code),str(tmp_path)],
        input=json.dumps({'action':'settle','id':'fixture'}),capture_output=True,text=True,check=False,timeout=5)
    assert result.returncode==2 and not result.stdout
    assert json.loads(result.stderr)=={'error_class':'EPERM','reason':'quota_IPC_unavailable_or_invalid','phase':phase}
    assert not list((tmp_path/'requests').glob('*.json'))
    assert len(list((tmp_path/'requests').glob('*.payload')))==1
    assert 'fixture failure'not in result.stderr and 'token'not in result.stderr


def test_client_rejects_old_handshake_without_publishing_or_dispatch(tmp_path):
    code=Path(__file__).parents[1]/'src/memweave_eval/quota_ipc.mjs'
    for folder in ('requests','responses'):(tmp_path/folder).mkdir()
    (tmp_path/'client.json').write_text(json.dumps({'service_id':'s','channel_id':'c','protocol':2}))
    (tmp_path/'ready.json').write_text(json.dumps({'service_id':'s','channel_id':'c'}))
    result=subprocess.run(['node',str(code),str(tmp_path)],input='{}',text=True,capture_output=True,check=False,timeout=5)
    assert result.returncode==2 and json.loads(result.stderr)['phase']=='read_handshake'
    assert not list((tmp_path/'requests').iterdir())
