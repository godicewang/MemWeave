// Only uploaded to preparation containers; never present in a paid Trial.
import fs from 'node:fs';
export default function fixture(pi:any) {
  let calls=0;
  const fake=async(input:any,init:any)=>{
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
    if(url.hostname!=='api.deepseek.com')throw Error('Unexpected fixture endpoint');
    if((init?.method??'GET').toUpperCase()!=='GET')fs.appendFileSync('/logs/agent/cli-fake-upstream.jsonl',JSON.stringify({
      event:'mock_dispatch_invoked',timestamp:new Date().toISOString(),pid:process.pid,title:process.title})+'\n');
    if(new Headers(init?.headers).get('authorization')!=='Bearer fixture-only')throw Error('Guard credential broker missing');
    if((init?.method??'GET').toUpperCase()==='GET')return Response.json({data:[{
      id:'deepseek-flash',name:'DeepSeek V4.1 Flash',context_window:1000000,max_output_tokens:384000}]});
    calls++;
    if(process.env.MEMWEAVE_EVAL_HANG_FIXTURE==='1')return new Promise(()=>setInterval(()=>{},1000));
    const create=process.env.MEMWEAVE_EVAL_VARIANT==='pi-memweave' && calls===1;
    const delta=create?{role:'assistant',tool_calls:[{index:0,id:'cli-create',type:'function',function:{
      name:'task_create',arguments:JSON.stringify({title:'CLI probe',goal:'Verify CLI State delivery',
        project_name:'probe',summary:'offline CLI smoke',keywords:['probe']})}}]}:{role:'assistant',content:'OK'};
    const frames=[{id:'cli-fixture',model:'deepseek-flash',choices:[{index:0,delta,finish_reason:null}]},
      {id:'cli-fixture',choices:[{index:0,delta:{},finish_reason:create?'tool_calls':'stop'}],
      usage:{prompt_tokens:100,completion_tokens:50}}];
    return new Response(new ReadableStream({start(c){for(const f of frames)c.enqueue(new TextEncoder().encode(
      'data: '+JSON.stringify(f)+'\n\n'));c.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));}}),{
      headers:{'content-type':'text/event-stream'}});
  };
  globalThis.fetch=fake;
  if(process.env.MEMWEAVE_EVAL_DROP_GUARD==='1')pi.on('before_provider_request',()=>{globalThis.fetch=fake;});
}
