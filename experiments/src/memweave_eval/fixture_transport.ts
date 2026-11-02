// Only uploaded to preparation containers; never present in a paid Trial.
import fs from 'node:fs';
import http from 'node:http';
import {spawnSync}from'node:child_process';
export default function fixture(pi:any) {
  let calls=0;
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
    if(process.env.MEMWEAVE_EVAL_HANG_FIXTURE==='1')return new Promise(()=>setInterval(()=>{},1000));
    const create=process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave' && calls===1;
    const domain=Boolean(process.env.MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR) &&
      calls===(process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave'?2:1);
    const domainProbe=domain?JSON.parse(fs.readFileSync(process.env.MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR!,'utf8')).probe:null;
    const query=process.env.MEMWEAVE_EVAL_SEALED==='1' && calls===(process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave'?2:1);
    const command=process.env.MEMWEAVE_EVAL_EXECUTION_NEGATIVE==='1'?"node -e 'process.exit(0)'":
      "which python3 || true; command -v python3 || true; printf '%s\\n' 'python|perl' | grep -E 'python|perl'; cat > /tmp/cli-probe.c <<'EOF'\n"+
      "typedef struct Node node;\nnode *root;\nEOF\ncc -fsyntax-only /tmp/cli-probe.c && test -s /tmp/cli-probe.c";
    const delta=domain?{role:'assistant',tool_calls:[{index:0,id:'cli-domain-read',type:'function',function:{name:domainProbe.name,arguments:JSON.stringify(domainProbe.arguments)}}]}:query?{role:'assistant',tool_calls:[{index:0,id:'cli-query',type:'function',function:{name:'bash',arguments:JSON.stringify({command})}}]}:create?{role:'assistant',tool_calls:[{index:0,id:'cli-create',type:'function',function:{
      name:'task_create',arguments:JSON.stringify({title:'CLI probe',goal:'Verify CLI State delivery',
        project_name:'probe',summary:'offline CLI smoke',keywords:['probe']})}}]}:{role:'assistant',content:'OK'};
    const frames=[{id:'cli-fixture',model:'deepseek-flash',choices:[{index:0,delta,finish_reason:null}]},
      {id:'cli-fixture',choices:[{index:0,delta:{},finish_reason:(create||query||domain)?'tool_calls':'stop'}],
      usage:{prompt_tokens:100,completion_tokens:50}}];
    return deliver(frames.map(f=>'data: '+JSON.stringify(f)+'\n\n').join('')+'data: [DONE]\n\n','text/event-stream',init);
  };
  globalThis.fetch=fake;
  if(process.env.MEMWEAVE_EVAL_DROP_GUARD==='1')pi.on('before_provider_request',()=>{globalThis.fetch=fake;});
}
