// Preparation only: full Pi/package request conversion using in-memory HTTP responses.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {installGuard} from './fetch_guard.mjs';
const [sdkPath,agentDir,entry,variant,capText,barrier]=process.argv.slice(2);
const primary=capText==='default',cap=primary?null:Number(capText),enabled=variant==='pi-memweave';
const sdk=await import(sdkPath);
const trace='/logs/agent/mock-request-trace.jsonl';
const ledger='/logs/agent/mock-quota.json';
await fs.writeFile(ledger,JSON.stringify({schema_version:1,maximum_usd:1,
  deadline:Date.now()/1000+120,exposure_usd:0,requests:{},arm_limits:{}}));
const bodies=[];
globalThis.fetch=installGuard({ledger,trace,deadline:Date.now()/1000+120,variant,
  quotaScript:path.join(path.dirname(new URL(import.meta.url).pathname),process.env.MEMWEAVE_EVAL_QUOTA_BACKEND==='node'?'budget_guard.mjs':'budget_guard.py'),
  fetchImpl:async (url,init)=>{
    if(new URL(typeof url==='string'||url instanceof URL?url:url.url).hostname!=='api.deepseek.com')throw Error('Unexpected probe endpoint');
    if((init?.method??'GET').toUpperCase()==='GET')return Response.json({data:[{
      id:'deepseek-flash',name:'DeepSeek V4.1 Flash',context_length:1000000,
      context_window:1000000,max_input_tokens:1000000,max_output_tokens:384000}]});
    bodies.push(JSON.parse(init.body));
    if(bodies.length>3)throw Error('Unexpected additional mock request');
    const tool=enabled && bodies.length===1;
    const delta=tool ? {role:'assistant',tool_calls:[{index:0,id:'probe-create',type:'function',function:{
      name:'task_create',arguments:JSON.stringify({title:'probe',goal:'Verify current request State',
      project_name:'probe',summary:'offline request verification',keywords:['probe']})}}]} :
      {role:'assistant',content:'Offline probe complete.'};
    await new Promise(resolve=>setTimeout(resolve,600)); // Make the paired smoke overlap observable.
    const frames=[{id:'fixture',model:'deepseek-flash',choices:[{index:0,delta,finish_reason:null}]},
      {id:'fixture',choices:[{index:0,delta:{},finish_reason:tool?'tool_calls':'stop'}],
      usage:{prompt_tokens:100,completion_tokens:50}}];
    return new Response(new ReadableStream({start(controller){
      for(const frame of frames)controller.enqueue(new TextEncoder().encode('data: '+JSON.stringify(frame)+'\n\n'));
      controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));
    }}),{headers:{'content-type':'text/event-stream'}});
  }});
const settings=sdk.SettingsManager.create(process.cwd(),agentDir);
const loader=new sdk.DefaultResourceLoader({cwd:process.cwd(),agentDir,settingsManager:settings,
  additionalExtensionPaths:[path.join(path.dirname(new URL(import.meta.url).pathname),'checkpoint_observer.ts'),...(enabled?[entry]:[])]});
await loader.reload();
const runtime=await sdk.ModelRuntime.create({authPath:agentDir+'/auth.json',modelsPath:agentDir+'/models.json',
  allowModelNetwork:false,refreshOnCreate:false});
const nativeModel=runtime.getModel('deepseek','deepseek-flash');
if(primary) {
  if(!nativeModel)throw Error('primary_default native model catalog entry missing');
  runtime.registerProvider('deepseek',{apiKey:'fixture-only'});
} else runtime.registerProvider('deepseek',{baseUrl:'https://api.deepseek.com',apiKey:'fixture-only',api:'openai-completions',
  models:[{id:'deepseek-flash',name:'DeepSeek V4.1 Flash',reasoning:true,input:['text'],
  contextWindow:1000000,maxTokens:384000,samplingParams:{max_tokens:cap},
  cost:{input:.3,output:1.2,cacheRead:.006,cacheWrite:0}}]});
const {session,extensionsResult}=await sdk.createAgentSession({agentDir,settingsManager:settings,
  resourceLoader:loader,modelRuntime:runtime,model:runtime.getModel('deepseek','deepseek-flash'),...(primary?{}:{thinkingLevel:'off'})});
const errors=[];
try {
  await session.bindExtensions({onError:e=>errors.push(e.error)});
  assert.equal(extensionsResult.errors.length,0);
  if(barrier && barrier!=='-') {
    await fs.writeFile(path.join(barrier,variant+'.ready'),'ready');
    const until=Date.now()+120000;
    while(true){
      try{await fs.stat(path.join(barrier,(enabled?'pi-native':'pi-memweave')+'.ready'));break;}catch{}
      if(Date.now()>until)throw Error('Paired smoke barrier timed out');
      await new Promise(resolve=>setTimeout(resolve,100));
    }
  }
  await session.prompt('Create a persistent verification task and check its current State.');
  assert.equal(errors.length,0,JSON.stringify(errors));
  const records=(await fs.readFile(trace,'utf8')).trim().split('\n').map(JSON.parse);
  const ready=records.filter(e=>e.event==='request_ready');
  assert.equal(ready.length,enabled?2:1);
  assert.equal(ready[0].rule_block_count,enabled?1:0);
  assert.ok(ready.every(e=>e.tool_names.includes('read')&&e.tool_names.includes('bash')));
  assert.equal(ready.at(-1).tool_names.includes('task_create'),enabled);
  assert.equal(Boolean(ready.at(-1).state_blocks.length),enabled);
  if(primary)assert.ok(ready.every(e=>Number.isSafeInteger(e.max_output)&&e.max_output>0&&e.max_output<=nativeModel.maxTokens));
  else assert.ok(ready.every(e=>e.max_output===cap));
  assert.ok(ready.every(e=>e.prepared_messages_sha256&&Array.isArray(e.prepared_messages)));
  if(enabled){assert.equal(ready.at(-1).expected_version_at_prepare,ready.at(-1).state_blocks[0].version);
    assert.equal(ready.at(-1).expected_task_id,ready.at(-1).state_blocks[0].task_id);}
  if(primary&&enabled)assert.ok(ready.at(-1).rendered_budget_snapshots.some(b=>b?.recent_turns===200&&b.evict_turns===40&&b.state_event_max_chars===100));
  await fs.writeFile('/logs/agent/mock-request-result.json',JSON.stringify({
    mock:true,real_model_requests:0,transport_attempts:bodies.length,
    rule_block_count:ready.at(-1).rule_block_count,state_blocks:ready.at(-1).state_blocks,
    max_output:cap,actual_output_limits:ready.map(e=>e.max_output),primary_default:primary,model_catalog_max_output:nativeModel?.maxTokens,
    thinking_level:session.thinkingLevel,thinking_payloads:ready.map(e=>e.thinking),
    actual_rendered_budgets:ready.map(e=>e.rendered_budget_snapshots),tools:ready.at(-1).tool_names}));
} finally {session.dispose();}
