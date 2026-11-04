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
if(calls===2)throw Error('network');
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
