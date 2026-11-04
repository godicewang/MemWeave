import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from memweave_eval.budget_guard import initialize

NODE = os.environ.get("MEMWEAVE_EVAL_TEST_NODE") or shutil.which("node") or "node"
GUARD = Path(__file__).parents[1] / "src/memweave_eval/fetch_guard.mjs"


@pytest.mark.parametrize('failure',[False,True])
def test_metadata_observation_preserves_real_fetch_and_never_bills_chat(tmp_path,failure):
    script="""
import fs from 'node:fs';import{installGuard}from GUARD;
let calls=0;const upstream=async()=>{calls++;if(FAILURE)throw Object.assign(new TypeError('private diagnostic'),{cause:{code:'ENOTFOUND'}});return new Response('{"data":[]}',{status:200});};
const fetch=installGuard({ledger:LEDGER,trace:TRACE,deadline:Date.now()/1000+60,variant:'fixture',fetchImpl:upstream});
try{const r=await fetch('https://api.deepseek.com/models');if(await r.text()!=='{"data":[]}')throw Error('changed bytes');}catch(e){if(!FAILURE)throw e;}
if(calls!==1||fs.existsSync(LEDGER))throw Error('unexpected dispatch/accounting');
"""
    for key,value in {'GUARD':str(GUARD),'LEDGER':str(tmp_path/'no-ledger.json'),'TRACE':str(tmp_path/'trace.jsonl')}.items():
        script=script.replace(key,json.dumps(value))
    script=script.replace('FAILURE',str(failure).lower())
    run=subprocess.run([NODE,'--input-type=module','-e',script],capture_output=True,text=True,timeout=10,check=False)
    assert run.returncode==0,run.stderr
    rows=[json.loads(s)for s in (tmp_path/'trace.jsonl').read_text().splitlines()]
    assert [r['event']for r in rows]==['metadata_request_start','metadata_request_error'if failure else'metadata_request_end']
    assert 'private diagnostic'not in (tmp_path/'trace.jsonl').read_text()
    if failure:assert rows[-1]['error_class']=='TypeError'and rows[-1]['cause_code']=='ENOTFOUND'
    else:assert rows[-1]['http_status']==200


def test_settlement_rejection_preserves_reservation_and_safe_reason(tmp_path):
    ledger=tmp_path/'quota.json';initialize(ledger,1.,time.time()+60)
    trace=tmp_path/'trace.jsonl'
    script="""import {installGuard} from GUARD;
const f=installGuard({ledger:LEDGER,trace:TRACE,deadline:DEADLINE,variant:'fixture',quotaScript:QUOTA,
fetchImpl:async()=>new Response('data: {"usage":{"prompt_tokens":100,"completion_tokens":20}}\\n\\ndata: [DONE]\\n\\n')});
await(await f('https://api.deepseek.com/chat/completions',{method:'POST',body:JSON.stringify({model:'deepseek-flash',stream:true,max_tokens:10,messages:[]})})).text();
"""
    for key,value in {'GUARD':str(GUARD),'LEDGER':str(ledger),'TRACE':str(trace),'QUOTA':str(GUARD.with_name('budget_guard.py'))}.items():
        script=script.replace(key,json.dumps(value))
    script=script.replace('DEADLINE',str(time.time()+60))
    result=subprocess.run([NODE,'--input-type=module','-e',script],capture_output=True,text=True,timeout=10,check=False)
    assert result.returncode==0,result.stderr
    events=[json.loads(line)for line in trace.read_text().splitlines()]
    detail=next(e for e in events if e['event']=='quota_operation_rejected')
    assert detail['operation']=='settle'and detail['error_class']=='ValueError'
    assert detail['reason']=='usage outside reserved bounds; reservation retained'
    assert next(iter(json.loads(ledger.read_text())['requests'].values()))['status']=='reserved'


def test_fetch_bytes_split_usage_error_and_unknown_reservations(tmp_path):
    ledger = tmp_path / "quota.json"
    initialize(ledger, 29.0, time.time() + 60)
    script = """
import fs from 'node:fs';
import {installGuard} from GUARD;
const body=JSON.stringify({model:'deepseek-flash',stream:true,max_tokens:1000,messages:[]});
const bytes='data: {"choices":[{"delta":{"content":"秘密"}}]}\\r\\n\\r\\n'+
 'data: {"usage":{"prompt_tokens":123,"completion_tokens":45}}\\n\\n'+'data: [DONE]\\n\\n';
let calls=0;
const fake=async (url,init)=>{if(init.body!==body)throw Error('body changed');if(new Headers(init.headers).get('accept-encoding')!=='identity')throw Error('control encoding changed');calls++;
if(calls===2)throw Object.assign(new TypeError('sensitive upstream detail'),{cause:{code:'UND_ERR_CONNECT_TIMEOUT'}});
return new Response(new ReadableStream({start(c){const b=new TextEncoder().encode(bytes);
for(let i=0;i<b.length;i+=7)c.enqueue(b.slice(i,i+7));c.close();}}));};
const fetch=installGuard({ledger:LEDGER,trace:TRACE,deadline:DEADLINE,variant:'native',
quotaScript:QUOTA,fetchImpl:fake});
const output=await(await fetch('https://api.deepseek.com/chat/completions',{method:'POST',body})).text();
if(output!==bytes)throw Error('response bytes changed');
try{await fetch('https://api.deepseek.com/chat/completions',{method:'POST',body});}catch{}
console.log(calls);
"""
    import_source = str(GUARD.resolve()).replace("\\", "\\\\")
    script = script.replace("GUARD", json.dumps(import_source)).replace(
        "LEDGER", json.dumps(str(ledger))
    )
    script = script.replace("TRACE", json.dumps(str(tmp_path / "trace.jsonl")))
    script = script.replace("DEADLINE", str(time.time() + 60)).replace(
        "QUOTA", json.dumps(str(GUARD.with_name("budget_guard.py").resolve()))
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(ledger.read_text())
    assert len(data["requests"]) == 2
    assert sorted(r["status"] for r in data["requests"].values()) == ["reserved", "settled"]
    assert data["exposure_usd"] == pytest.approx((123 * 0.3 + 45 * 1.2) / 1_000_000 + 0.3012)
    trace = (tmp_path / "trace.jsonl").read_text()
    assert "秘密" not in trace
    assert trace.count('"event":"http_attempt"') == 2
    failed=next(json.loads(s)for s in trace.splitlines()if json.loads(s)['event']=='http_error')
    assert failed['cause_code']=='UND_ERR_CONNECT_TIMEOUT'
    assert failed['upstream_signal_aborted']is False and failed['evaluation_signal_aborted']is False
    assert 'sensitive upstream detail'not in trace


def test_real_openai_sdk_done_cancellation_and_internal_retry(tmp_path):
    ledger = tmp_path / "quota.json"
    initialize(ledger, 29.0, time.time() + 60)
    script = r"""
import OpenAI from OPENAI;
import {installGuard} from GUARD;
let calls=0;
const fake=async()=>{
 calls++;
 if(calls===1)return new Response(JSON.stringify({error:{message:'fixture retry'}}),
    {status:503,headers:{'content-type':'application/json','retry-after':'0'}});
 const frame='data: '+JSON.stringify({id:'fixture',model:'deepseek-flash',choices:[{index:0,
    delta:{content:'ok'},finish_reason:null}]})+'\n\n'+
    'data: '+JSON.stringify({id:'fixture',choices:[{index:0,delta:{},finish_reason:'stop'}],
    usage:{prompt_tokens:100,completion_tokens:20}})+'\n\n'+'data: [DONE]\n\n';
 // Intentionally never EOF: the real SDK stops at [DONE] and cancels the body.
 return new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode(frame));}}),
    {headers:{'content-type':'text/event-stream'}});
};
globalThis.fetch=installGuard({ledger:LEDGER,trace:TRACE,deadline:DEADLINE,variant:'sdk',
    quotaScript:QUOTA,fetchImpl:fake});
const client=new OpenAI({apiKey:'not-a-real-key',baseURL:'https://api.deepseek.com',maxRetries:1});
const stream=await client.chat.completions.create({model:'deepseek-flash',stream:true,
    max_tokens:1000,messages:[{role:'user',content:'fixture'}]});
for await(const chunk of stream){}
console.log(calls);
"""
    replacements = {
        "OPENAI": str(GUARD.parents[3] / "node_modules/openai/index.mjs"),
        "GUARD": str(GUARD.resolve()),
        "LEDGER": str(ledger),
        "TRACE": str(tmp_path / "trace.jsonl"),
        "QUOTA": str(GUARD.with_name("budget_guard.py").resolve()),
    }
    for key, value in replacements.items():
        script = script.replace(key, json.dumps(value))
    script = script.replace("DEADLINE", str(time.time() + 60))
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2"
    data = json.loads(ledger.read_text())
    assert sorted(r["status"] for r in data["requests"].values()) == ["reserved", "settled"]
    trace = (tmp_path / "trace.jsonl").read_text()
    assert trace.count('"event":"request_end"') == 1
    assert trace.count('"event":"http_attempt"') == 2


def test_sdk_repeated_real_local_sse_sockets_settle_without_waiting_for_eof(tmp_path):
    """Socket/stream regression only: no real provider and no full-Pi claim."""
    ledger=tmp_path/'quota.json';initialize(ledger,19,time.time()+60)
    script=r"""
import http from 'node:http';import fs from 'node:fs';import OpenAI from OPENAI;
import{installGuard}from GUARD;
let calls=0;const server=http.createServer((req,res)=>{
 calls++;req.resume();res.writeHead(200,{'content-type':'text/event-stream'});
 const frame={id:'mock',model:'deepseek-flash',choices:[{index:0,delta:{content:'ok'},finish_reason:'stop'}],usage:{prompt_tokens:100,completion_tokens:2,prompt_cache_hit_tokens:0}};
 res.write('data: '+JSON.stringify(frame)+'\n\n'+'data: [DONE]\n\n');
 const timer=setInterval(()=>res.write(': keepalive\n\n'),1000);res.on('close',()=>clearInterval(timer));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const actual=globalThis.fetch.bind(globalThis),port=server.address().port;
globalThis.fetch=installGuard({ledger:LEDGER,trace:TRACE,deadline:Date.now()/1000+30,variant:'local-fixture',quotaScript:QUOTA,
 fetchImpl:(_input,init)=>actual('http://127.0.0.1:'+port+'/chat/completions',init)});
try{
 const client=new OpenAI({apiKey:'fixture-not-a-real-key',baseURL:'https://api.deepseek.com',maxRetries:0});
 const owner=new AbortController();
 for(let i=0;i<8;i++){
  const stream=await client.chat.completions.create({model:'deepseek-flash',stream:true,max_tokens:128,messages:[{role:'user',content:'fixture'}]},{signal:owner.signal});
  for await(const _chunk of stream){}
  if(owner.signal.aborted)throw Error('caller signal was changed');
 }
 const ledger=JSON.parse(fs.readFileSync(LEDGER));if(calls!==8||Object.values(ledger.requests).some(r=>r.status!=='settled'))throw Error('lost settlement or unwanted retry');
 console.log(calls);
}finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
"""
    replacements={'OPENAI':str(GUARD.parents[3]/'node_modules/openai/index.mjs'),'GUARD':str(GUARD),
        'LEDGER':str(ledger),'TRACE':str(tmp_path/'trace.jsonl'),'QUOTA':str(GUARD.with_name('budget_guard.py'))}
    for key,value in replacements.items():script=script.replace(key,json.dumps(value))
    run=subprocess.run([NODE,'--input-type=module','-e',script],capture_output=True,text=True,timeout=20,check=False)
    assert run.returncode==0,run.stderr
    assert run.stdout.strip()=='8'
    rows=[json.loads(s)for s in (tmp_path/'trace.jsonl').read_text().splitlines()]
    assert not any(r['event']=='http_error'for r in rows)
    assert sum(r['event']=='request_end'for r in rows)==8
