// Actor-side bounded capability client. Never receives the provider API key or ledger.
import fs from 'node:fs';
import {randomUUID} from 'node:crypto';
export function brokerFetch({configPath,record,fetchImpl,summarize}) {
  const config=JSON.parse(fs.readFileSync(configPath,'utf8'));
  const base=new URL(config.url);
  if(base.protocol!=='http:'||base.hostname!=='memweave-broker.internal'||!Number.isInteger(Number(base.port))||!config.capability||!config.arm||!config.episode)throw Error('Invalid trusted broker client configuration');
  const headers=()=>new Headers({'authorization':'Bearer '+config.capability,'content-type':'application/json'});
  return async function forward(input,init) {
    const original=new URL(typeof input==='string'||input instanceof URL?input:input.url);
    const method=(init?.method??input?.method??'GET').toUpperCase();
    const target=new URL(original.pathname,base);
    if(method==='GET')return fetchImpl(target,{...init,headers:headers()});
    const raw=typeof init?.body==='string'?init.body:await input.clone().text(),payload=JSON.parse(raw);
    const id=config.episode+':'+config.arm+':'+randomUUID();const h=headers();h.set('x-memweave-request-id',id);
    let response;
    try{response=await fetchImpl(target,{...init,headers:h,body:raw});}
    catch(error){record({event:'broker_ipc_error',request_id:id,error_class:error?.name??'Error'});throw error;}
    if(response.headers.get('x-memweave-request-id')!==id) {
      record({event:'request_denied',request_id:id,reason:'trusted_broker_rejected'});return response;
    }
    record({event:'budget_reserved',request_id:id,charge_usd:Number(response.headers.get('x-memweave-reserved-usd'))});
    record({event:'request_ready',request_id:id,...summarize(payload)});
    record({event:'http_attempt',request_id:id,timestamp_scope:'broker_ack_client_observation'});
    record({event:'http_response',request_id:id,status:response.status});
    if(!response.body)return response;
    let pending='',usage=null,done=false,ended=false,model=null;const decoder=new TextDecoder();
    async function finish() {
      if(ended)return;ended=true;let settled=false;
      if(done&&usage)try {
        const receipt=await fetchImpl(new URL('/v1/receipts/'+encodeURIComponent(id),base),{headers:headers()});
        if(receipt.ok){const r=await receipt.json();settled=r.status==='settled';if(settled)record({event:'budget_settled',request_id:id,charge_usd:r.charge_usd});}
      }catch{}
      record({event:'request_end',request_id:id,usage,settled,stream_done:done,response_model:model,authority:'external_broker'});
    }
    async function line(value) {
      if(!value.startsWith('data:'))return;
      const body=value.slice(5).trim();if(body==='[DONE]'){done=true;await finish();return;}
      try{const item=JSON.parse(body);if(typeof item.model==='string')model=item.model;
        if(Number.isInteger(item.usage?.prompt_tokens)&&Number.isInteger(item.usage?.completion_tokens))usage={input:item.usage.prompt_tokens,output:item.usage.completion_tokens,cache_hit:item.usage.prompt_cache_hit_tokens??null};
      }catch{}
    }
    const stream=response.body.pipeThrough(new TransformStream({
      async transform(chunk,controller){pending+=decoder.decode(chunk,{stream:true});let i;while((i=pending.indexOf('\n'))>=0){await line(pending.slice(0,i).replace(/\r$/,''));pending=pending.slice(i+1);}if(pending.length>4_000_000)throw Error('Unbounded broker SSE line');controller.enqueue(chunk);},
      async flush(){pending+=decoder.decode();if(pending)await line(pending);await finish();},
    }));
    return new Response(stream,{status:response.status,statusText:response.statusText,headers:response.headers});
  };
}
