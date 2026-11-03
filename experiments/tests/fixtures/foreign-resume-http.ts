// Two real Pi Sessions, full Rule/tools, local HTTP only; no real credentials.
import assert from'node:assert/strict';
import {createServer}from'node:http';
import {mkdir,writeFile,readFile,copyFile}from'node:fs/promises';
import path from'node:path';
import test from'node:test';
import {SessionManager}from'@earendil-works/pi-coding-agent';
import {nativeSession}from'../../../tests/fixtures/native-session.ts';
import {registerMemweave}from'../../../src/extension/register.ts';
import {memoryPaths}from'../../../src/storage/paths.ts';
import {DEFAULT_CONFIG}from'../../../src/config/schema.ts';
import {attachBoundaries,boundaryKey}from'../../src/memweave_eval/request_boundary.ts';
import {contentEvidence}from'../../src/memweave_eval/content_evidence.mjs';

test('foreign Task resume is reconstructed from frozen source and actual HTTP across two Pi Sessions',async t=>{
 const out=process.env.MEMWEAVE_LIFECYCLE_FIXTURE_OUTPUT;assert.ok(out&&path.isAbsolute(out));await mkdir(out);
 const trial=path.join(out,'trial'),sessions=path.join(trial,'agent','sessions');await mkdir(sessions,{recursive:true});
 const memory=path.join(out,'memory');await mkdir(memory);const paths=memoryPaths(memory);
 await writeFile(paths.config,JSON.stringify({...DEFAULT_CONFIG,recent_turns:20,evict_turns:4}));
 await writeFile(paths.rule,await readFile(new URL('../../../resources/rule.md',import.meta.url)));
 process.env.MEMWEAVE_EVAL_CONTENT_STORE=path.join(trial,'agent','request-content');
 t.after(()=>{delete process.env.MEMWEAVE_EVAL_CONTENT_STORE;});
 let current:any,taskId='';const records:any[]=[],errors:string[]=[];
 const factory=(pi:any)=>{attachBoundaries(pi,{memoryRoot:memory});registerMemweave(pi,{paths,verifyCapacity:async model=>model.contextWindow,
  embedder:async texts=>({vectors:texts.map(()=>Array(384).fill(0)),truncated:texts.map(()=>false)}),
  report:error=>errors.push(String(error))});};
 const a=await nativeSession(t,[factory],false,512,[],undefined,true);current=a;
 const server=createServer(async(req,res)=>{
  assert.equal(req.url,'/v1/chat/completions');let raw='';for await(const b of req)raw+=String(b);
  const payload=JSON.parse(raw),prepared=structuredClone((globalThis as any)[boundaryKey]);
  const window=current.manager.getBranch().findLast((e:any)=>e.type==='custom'&&e.customType==='memweave.window.v1')?.data;
  records.push({payload,prepared,observed_window:structuredClone(window),requested_at:new Date().toISOString()});
  const evidence=contentEvidence();evidence.event('request_ready',{request_id:'local-fixture-'+records.length,
   payload_ref:evidence.put(raw),prepared_boundary:prepared});
  const n=records.length;let delta:any={role:'assistant',content:'local source checkpoint '+n},finish='stop';
  if(n===1||n===3){
   const name=n===1?'task_create':'task_resume';
   const input=n===1?{title:'Source Task',goal:'Preserve the original source constraint while continuing this project.',
    project_name:'Lifecycle fixture',summary:'Source continuation control',keywords:['source']}:{task_id:taskId};
   delta={role:'assistant',tool_calls:[{index:0,id:n===1?'source-create':'target-resume',type:'function',
    function:{name,arguments:JSON.stringify(input)}}]};finish='tool_calls';
  }
  res.writeHead(200,{'content-type':'text/event-stream'});
  for(const item of[{delta,finish_reason:null},{delta:{},finish_reason:finish}])
   res.write('data: '+JSON.stringify({id:'local-foreign',choices:[{index:0,...item}]})+'\n\n');
  res.end('data: [DONE]\n\n');
 });
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));});
 const address=server.address();assert.ok(address&&typeof address!=='string');
 async function model(h:any){h.runtime.registerProvider('foreign-local-http',{baseUrl:'http://127.0.0.1:'+address.port+'/v1',
  apiKey:'local-test-only',api:'openai-completions',models:[{id:'probe',name:'probe',input:['text'],reasoning:false,
   cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1_048_576,maxTokens:128}]});
  await h.session.setModel(h.runtime.getModel('foreign-local-http','probe'));}
 await model(a);await a.session.prompt('Source constraint: preserve the public reference files for this ongoing project.');
 assert.equal(records.length,2);taskId=JSON.parse(await readFile(paths.index,'utf8'))[0].task_id;assert.ok(taskId);
 const originals=a.manager.getBranch().filter((e:any)=>e.type==='message');
 const manager=SessionManager.create(a.cwd,path.dirname(a.manager.getSessionFile()!));
 const b=await nativeSession(t,[factory],false,512,[],manager,true);current=b;await model(b);
 await b.session.prompt('Continue the earlier source Task in this fresh Session.');
 assert.equal(records.length,4);assert.deepEqual(errors,[]);assert.deepEqual(a.errors,[]);assert.deepEqual(b.errors,[]);
 const receipt=b.manager.getBranch().findLast((e:any)=>e.type==='custom'&&e.customType==='memweave.resume.v1');
 assert.equal(receipt.data.source_session_id,a.manager.getSessionId());assert.equal(receipt.data.task_id,taskId);
 for(const e of originals)assert.deepEqual(a.manager.getBranch().find((r:any)=>r.id===e.id),e);
 for(const h of[a,b])await copyFile(h.manager.getSessionFile()!,path.join(sessions,path.basename(h.manager.getSessionFile()!)));
 for(const r of records){const tools=new Set(r.payload.tools.map((t:any)=>t.function.name));
  for(const name of['bash','read','write','edit','task_create','task_resume','state_append','memory_read'])assert.ok(tools.has(name));
  assert.match(JSON.stringify(r.payload.messages[0]),/pi_long_task_rule/);}
 await writeFile(path.join(out,'frames.json'),JSON.stringify({fixture_only:true,real_model_requests:0,
  full_rule_and_tools:true,originals_unchanged:true,source_session_id:a.manager.getSessionId(),target_session_id:b.manager.getSessionId(),records},null,2));
});
