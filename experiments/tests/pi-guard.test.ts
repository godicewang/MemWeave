import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {nativeSession} from '../../tests/fixtures/native-session.ts';
import {installGuard} from '../src/memweave_eval/fetch_guard.mjs';

test('full native Pi requests, provider retry and native compaction share admission',async t=>{
  const h=await nativeSession(t,[],true,512,[],undefined,true);
  const ledger=path.join(h.root,'quota.json'),trace=path.join(h.root,'trace.jsonl');
  const deadline=Date.now()/1000+60;
  fs.writeFileSync(ledger,JSON.stringify({schema_version:1,maximum_usd:29,deadline,exposure_usd:0,requests:{}}));
  const bodies: any[]=[];
  const previous=globalThis.fetch;
  globalThis.fetch=installGuard({ledger,trace,deadline,variant:'native',
    quotaScript:fileURLToPath(new URL('../src/memweave_eval/budget_guard.py',import.meta.url)),
    fetchImpl:async (_url: any,init: any)=>{
      if(init?.method!=='POST')throw Error('Unexpected network request in fixture');
      bodies.push(JSON.parse(init.body));
      if(bodies.length===1)return new Response(JSON.stringify({error:{message:'fixture retry'}}),{
        status:503,headers:{'content-type':'application/json','retry-after':'0'}});
      const output='data: '+JSON.stringify({id:'fixture',model:'deepseek-flash',choices:[{
        index:0,delta:{role:'assistant',content:'Fixture summary and completed action.'},finish_reason:null}]})+'\n\n'+
        'data: '+JSON.stringify({id:'fixture',choices:[{index:0,delta:{},finish_reason:'stop'}],
        usage:{prompt_tokens:100,completion_tokens:20}})+'\n\n'+'data: [DONE]\n\n';
      return new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode(output));}}),{
        headers:{'content-type':'text/event-stream'}});
    }});
  t.after(()=>{globalThis.fetch=previous;});
  h.runtime.registerProvider('guard-fixture',{baseUrl:'https://api.deepseek.com',apiKey:'fixture-only',
    api:'openai-completions',models:[{id:'deepseek-flash',name:'fixture',reasoning:false,input:['text'],
      contextWindow:1_000_000,maxTokens:1000,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]});
  h.settings.applyOverrides({retry:{enabled:false,provider:{maxRetries:1}}});
  await h.session.setModel(h.runtime.getModel('guard-fixture','deepseek-flash')!);
  await h.session.prompt('Complete this controlled fixture. '+ 'context '.repeat(200));
  const before=bodies.length;
  assert.equal(before,2);
  assert.ok(h.session.getActiveToolNames().includes('bash'));
  assert.ok(!h.session.getActiveToolNames().includes('task_create'));
  await h.session.prompt('Second controlled turn. '+ 'context '.repeat(200));
  await h.session.prompt('Third controlled turn. '+ 'context '.repeat(200));
  const beforeCompaction=bodies.length;
  await h.session.compact();
  assert.ok(bodies.length>beforeCompaction,'native compaction made a captured model request');
  const records=fs.readFileSync(trace,'utf8').trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(records.filter(e=>e.event==='http_attempt').length,bodies.length);
  const quota=JSON.parse(fs.readFileSync(ledger,'utf8'));
  assert.equal(Object.values(quota.requests).filter((r: any)=>r.status==='settled').length,bodies.length-1);
});


test('retired progress environment cannot steer an original task',async t=>{
  const previous=process.env.MEMWEAVE_EVAL_PROGRESS_AFTER;
  process.env.MEMWEAVE_EVAL_PROGRESS_AFTER='1';
  t.after(()=>{
    if(previous===undefined)delete process.env.MEMWEAVE_EVAL_PROGRESS_AFTER;
    else process.env.MEMWEAVE_EVAL_PROGRESS_AFTER=previous;
  });
  const observer=fileURLToPath(new URL('../src/memweave_eval/checkpoint_observer.ts',import.meta.url));
  const h=await nativeSession(t,[],false,512,[observer],undefined,true);
  const {fauxAssistantMessage}=await import('@earendil-works/pi-ai/providers/faux');
  h.faux.setResponses([fauxAssistantMessage('Controlled response.')]);
  await h.session.prompt('Original task input.');
  const users=h.manager.getEntries().filter((e:any)=>e.type==='message'&&e.message.role==='user');
  assert.equal(users.length,1);
  assert.ok(!JSON.stringify(users).includes('请简短汇报进度'));
  assert.ok(!h.session.getActiveToolNames().includes('task_create'));
});
