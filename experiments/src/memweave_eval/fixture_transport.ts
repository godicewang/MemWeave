// Only uploaded to preparation containers; never present in a paid Trial.
import fs from 'node:fs';
import http from 'node:http';
import {spawnSync}from'node:child_process';
export default function fixture(pi:any) {
  let calls=0,originalTask:string|null=null;
  const networkFetch=globalThis.fetch;
  const queued=new Map<string,{body:string,type:string}>();
  const server=http.createServer((request,response)=>{
    request.resume();
    const value=queued.get(request.url!);if(!value){response.writeHead(404);response.end();return;}
    queued.delete(request.url!);
    const identity=request.headers['accept-encoding']==='identity';
    let body=Buffer.from(value.body);
    if(!identity){
      const encoded=spawnSync(process.execPath,['--input-type=module','-e',
        "import fs from 'node:fs';import zlib from 'node:zlib';process.stdout.write(zlib.zstdCompressSync(fs.readFileSync(0)));"],
        {input:body,timeout:5000,env:{...process.env,NODE_OPTIONS:''}});
      if(encoded.status!==0)throw Error('Fixture encoder failed');
      body=encoded.stdout;response.setHeader('content-encoding','zstd');
    }
    response.setHeader('content-type',value.type);
    fs.appendFileSync('/logs/agent/cli-http-encoding.jsonl',JSON.stringify({
      accepted_encoding:request.headers['accept-encoding']??null,response_encoding:identity?'identity':'zstd',
      real_model_requests:0})+'\n');
    response.end(body);request.socket.unref();
  });
  const listening=new Promise<void>(resolve=>server.listen(0,'127.0.0.1',()=>{server.unref();resolve();}));
  const deliver=async(body:string,type:string,init:any)=>{
    await listening;
    const key='/fixture-'+queued.size+'-'+Math.random();queued.set(key,{body,type});
    const headers=new Headers(init?.headers);
    if(process.env.MEMWEAVE_EVAL_COMPRESSED_FIXTURE_NEGATIVE==='1')headers.delete('accept-encoding');
    return networkFetch('http://127.0.0.1:'+(server.address()as any).port+key,
      {method:'POST',body:init?.body??'',headers});
  };
  const fake=async(input:any,init:any)=>{
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
    if(url.hostname!=='api.deepseek.com')throw Error('Unexpected fixture endpoint');
    if((init?.method??'GET').toUpperCase()!=='GET')fs.appendFileSync('/logs/agent/cli-fake-upstream.jsonl',JSON.stringify({
      event:'mock_dispatch_invoked',timestamp:new Date().toISOString(),pid:process.pid,title:process.title})+'\n');
    if(new Headers(init?.headers).get('authorization')!=='Bearer fixture-only')throw Error('Guard credential broker missing');
    if((init?.method??'GET').toUpperCase()==='GET')return deliver(JSON.stringify({data:[{
      id:'deepseek-flash',name:'DeepSeek V4.1 Flash',context_window:1000000,max_output_tokens:384000}]}),'application/json',init);
    calls++;
    const body=JSON.parse(init.body);
    for(const message of body.messages??[]){
      if(message.role!=='tool'||typeof message.content!=='string')continue;
      try{const value=JSON.parse(message.content.replace(/^\[(?:task_[^:\]]+:)?[UTAR]\d+\]\s*/,''));
        for(const item of Array.isArray(value)?value:[value])if(item.goal==='Verify CLI State delivery'&&typeof item.task_id==='string')originalTask=item.task_id;
      }catch{}
    }
    if(process.env.MEMWEAVE_EVAL_FIXTURE_DELAY_MS)await new Promise(resolve=>setTimeout(resolve,Number(process.env.MEMWEAVE_EVAL_FIXTURE_DELAY_MS)));
    if(process.env.MEMWEAVE_EVAL_HANG_FIXTURE==='1')return new Promise(()=>setInterval(()=>{},1000));
    const create=process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave' && calls===1;
    const domain=Boolean(process.env.MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR) &&
      calls===(process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave'?2:1);
    const domainProbe=domain?JSON.parse(fs.readFileSync(process.env.MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR!,'utf8')).probe:null;
    const query=process.env.MEMWEAVE_EVAL_SEALED==='1' && calls===(process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave'?2:1);
    const command=process.env.MEMWEAVE_EVAL_EXECUTION_NEGATIVE==='1'?"node -e 'process.exit(0)'":
      "which python3 || true; command -v python3 || true; printf '%s\\n' 'python|perl' | grep -E 'python|perl'; cat > /tmp/cli-probe.c <<'EOF'\n"+
      "typedef struct Node node;\nnode *root;\nEOF\ncc -fsyntax-only /tmp/cli-probe.c && test -s /tmp/cli-probe.c";
    const readonly=process.env.MEMWEAVE_EVAL_READONLY_FIXTURE==='1';
    const remember=readonly && process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave' && calls===2;
    const change=readonly && calls===(process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave'?3:1);
    const routes=Boolean(process.env.MEMWEAVE_EVAL_TASK_ROUTES_FIXTURE)&&process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave';
    let route=routes?(calls===3?{name:'task_create',id:'route-distractor',args:{title:'Independent diagnostics',goal:'Investigate separate telemetry diagnostics',project_name:'other',summary:'independent fixture distractor',keywords:['telemetry']}}:
      calls===4?{name:'task_find',id:'route-find',args:{query:'Verify CLI State delivery',limit:3}}:
      calls===5?{name:'task_resume',id:'route-resume',args:{task_id:originalTask}}:
      calls===6?{name:'write',id:'route-action',args:{path:'/app/app/events.py',content:fs.readFileSync('/app/app/events.py','utf8')+'\n# offline observer probe\n'}}:null):null;
    let routed=routes&&calls>=3;
    const fixtureStage=Number(process.env.MEMWEAVE_EVAL_STAGE_ID);
    const ephemeral=process.env.MEMWEAVE_EVAL_TASK_ROUTES_FIXTURE==='multi'&&fixtureStage===4;
    if(routes&&process.env.MEMWEAVE_EVAL_TASK_ROUTES_FIXTURE==='multi'){
      const stage=fixtureStage;
      routed=stage===1?calls>=3:true;
      route=stage===2&&calls===1?{name:'task_create',id:'route-distractor',args:{title:'Independent diagnostics',goal:'Investigate separate telemetry diagnostics',project_name:'other',summary:'independent fixture distractor',keywords:['telemetry']}}:
        stage===3&&calls===1?{name:'task_find',id:'route-find',args:{query:'Verify CLI State delivery',limit:3}}:
        stage===3&&calls===2?{name:'task_resume',id:'route-resume',args:{task_id:originalTask}}:
        stage===3&&calls===3?{name:'memory_read',id:'route-read',args:{items:[{ref:'U1'}],max_total_chars:1000}}:
        (stage===3&&calls===4||stage===5&&calls===1)?{name:'write',id:stage===5?'return-action':'route-action',args:{path:'/app/app/events.py',content:fs.readFileSync('/app/app/events.py','utf8')+'\n# offline observer probe\n'}}:null;
    }
    if(routes&&route?.name==='task_resume'&&!originalTask)throw Error('Real Task creation/search result missing from actual context');
    const scenario=process.env.MEMWEAVE_EVAL_SCENARIO_PATH?JSON.parse(fs.readFileSync(process.env.MEMWEAVE_EVAL_SCENARIO_PATH,'utf8')):null;
    const scripted=scenario?.steps?.[calls-1];
    if(scenario&&!scripted)throw Error('Offline scenario has no response at this request');
    const delta=scripted?(scripted.tool?{role:'assistant',tool_calls:[{index:0,id:'scenario-'+calls,type:'function',function:{name:scripted.tool,arguments:JSON.stringify(scripted.arguments)}}]}:{role:'assistant',content:scripted.text}):ephemeral?{role:'assistant',content:'12'}:routed?(route?{role:'assistant',tool_calls:[{index:0,id:route.id,type:'function',function:{name:route.name,arguments:JSON.stringify(route.args)}}]}:{role:'assistant',content:'OK'}):remember?{role:'assistant',tool_calls:[{index:0,id:'cli-remember',type:'function',function:{name:'state_append',arguments:JSON.stringify({items:['types.py','DESIGN.md','__init__.py'].map(name=>({type:'fact',content:'READ_ONLY /app/app/'+name,evidence:{U1:'Explicit source constraint'}}))})}}]}:change?{role:'assistant',tool_calls:[{index:0,id:'cli-change',type:'function',function:{name:'write',arguments:JSON.stringify({path:'/app/app/events.py',content:fs.readFileSync('/app/app/events.py','utf8')+'\n# offline observer probe\n'})}}]}:domain?{role:'assistant',tool_calls:[{index:0,id:'cli-domain-read',type:'function',function:{name:domainProbe.name,arguments:JSON.stringify(domainProbe.arguments)}}]}:query?{role:'assistant',tool_calls:[{index:0,id:'cli-query',type:'function',function:{name:'bash',arguments:JSON.stringify({command})}}]}:create?{role:'assistant',tool_calls:[{index:0,id:'cli-create',type:'function',function:{
      name:'task_create',arguments:JSON.stringify({title:'CLI probe',goal:'Verify CLI State delivery',
        project_name:'probe',summary:'offline CLI smoke',keywords:['probe']})}}]}:{role:'assistant',content:'OK'};
    const frames=[{id:'cli-fixture',model:'deepseek-flash',choices:[{index:0,delta,finish_reason:null}]},
      {id:'cli-fixture',choices:[{index:0,delta:{},finish_reason:(scripted?Boolean(scripted.tool):!ephemeral&&(routed?Boolean(route):(create||query||domain||remember||change)))?'tool_calls':'stop'}],
      usage:{prompt_tokens:100,completion_tokens:50}}];
    return deliver(frames.map(f=>'data: '+JSON.stringify(f)+'\n\n').join('')+'data: [DONE]\n\n','text/event-stream',init);
  };
  globalThis.fetch=fake;
  if(process.env.MEMWEAVE_EVAL_DROP_GUARD==='1')pi.on('before_provider_request',()=>{globalThis.fetch=fake;});
}
