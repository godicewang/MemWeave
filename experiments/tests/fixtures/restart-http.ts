// Real Pi Session + complete product tools/Rule, local HTTP only. Not model performance.
import assert from 'node:assert/strict';
import {createServer}from'node:http';
import {mkdir,writeFile,readFile}from'node:fs/promises';
import path from'node:path';
import test from'node:test';
import {nativeSession}from'../../../tests/fixtures/native-session.ts';
import {registerMemweave}from'../../../src/extension/register.ts';
import {memoryPaths}from'../../../src/storage/paths.ts';
import {DEFAULT_CONFIG}from'../../../src/config/schema.ts';
import {attachBoundaries,boundaryKey}from'../../src/memweave_eval/request_boundary.ts';

test('real Pi explicit restart delivers its declared native seed and later resets without altering originals',async t=>{
  const out=process.env.MEMWEAVE_LIFECYCLE_FIXTURE_OUTPUT;
  assert.ok(out&&path.isAbsolute(out));await mkdir(out);
  const memory=path.join(out,'memory');await mkdir(memory);
  const paths=memoryPaths(memory),records:any[]=[];let h:any;
  await writeFile(paths.config,JSON.stringify({...DEFAULT_CONFIG,recent_turns:3,evict_turns:1}));
  await writeFile(paths.rule,await readFile(new URL('../../../resources/rule.md',import.meta.url)));
  const store=path.join(out,'request-content');process.env.MEMWEAVE_EVAL_CONTENT_STORE=store;
  t.after(()=>{delete process.env.MEMWEAVE_EVAL_CONTENT_STORE;});
  const errors:string[]=[];
  h=await nativeSession(t,[pi=>{
    attachBoundaries(pi,{memoryRoot:memory});
    registerMemweave(pi,{paths,verifyCapacity:async model=>model.contextWindow,
      embedder:async texts=>({vectors:texts.map(()=>Array(384).fill(0)),truncated:texts.map(()=>false)}),
      report:error=>errors.push(String(error))});
  }],false,512,[],undefined,true);
  const server=createServer(async(req,res)=>{
    assert.equal(req.url,'/v1/chat/completions');let text='';for await(const b of req)text+=String(b);
    const payload=JSON.parse(text),prepared=structuredClone((globalThis as any)[boundaryKey]);
    const window=h.manager.getBranch().findLast((e:any)=>e.type==='custom'&&e.customType==='memweave.window.v1')?.data;
    records.push({payload,prepared,observed_window:structuredClone(window),local_http:true});
    res.writeHead(200,{'content-type':'text/event-stream'});
    for(const choice of[{delta:{role:'assistant',content:'fixture reply '+records.length},finish_reason:null},
      {delta:{},finish_reason:'stop'}])res.write('data: '+JSON.stringify({id:'local-restart',choices:[{index:0,...choice}]})+'\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));});
  const address=server.address();assert.ok(address&&typeof address!=='string');
  h.runtime.registerProvider('lifecycle-local-http',{baseUrl:'http://127.0.0.1:'+address.port+'/v1',
    apiKey:'local-test-only',api:'openai-completions',models:[{id:'probe',name:'probe',input:['text'],reasoning:false,
      cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1_048_576,maxTokens:32}]});
  await h.session.setModel(h.runtime.getModel('lifecycle-local-http','probe'));
  for(const text of['original source one','original source two','original source three'])await h.session.prompt(text);
  const originals=h.manager.getBranch().filter((e:any)=>e.type==='message');
  await h.session.prompt('/memweave-restart');assert.equal(records.length,3,'command must send zero requests');
  await h.session.prompt('new independent objective');
  await writeFile(paths.config,JSON.stringify({...DEFAULT_CONFIG,recent_turns:30,evict_turns:2}));
  await h.session.prompt('expand permitted original window');
  assert.equal(records.length,5);assert.deepEqual(errors,[]);assert.deepEqual(h.errors,[]);
  const branch=h.manager.getBranch();
  for(const e of originals)assert.deepEqual(branch.find((r:any)=>r.id===e.id),e);
  for(const r of records){
    const names=new Set(r.payload.tools.map((x:any)=>x.function.name));
    for(const name of['read','bash','write','edit','task_create','task_resume','state_append','memory_read'])assert.ok(names.has(name));
    const system=r.payload.messages.filter((m:any)=>m.role==='system').map((m:any)=>JSON.stringify(m.content)).join('\n');
    assert.match(system,/You are an expert coding assistant operating inside pi/);assert.match(system,/pi_long_task_rule/);
  }
  await writeFile(path.join(out,'frames.json'),JSON.stringify({fixture_only:true,real_model_requests:0,
    full_rule_and_builtin_memory_tools:true,original_messages_unchanged:true,records},null,2));
});
