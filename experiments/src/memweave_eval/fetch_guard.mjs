// Common experimental transport observer. No prompt/response text is persisted.
import fs from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {brokerFetch} from './broker_client.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
// Transport identity only: no task gold, State truth, or derived scoring.
export function requestSummary(payload) {
  const messages = payload.messages ?? [];
  return {
    payload_sha256: hash(JSON.stringify(payload)),
    payload_bytes: Buffer.byteLength(JSON.stringify(payload)),
    model: payload.model,
    max_output: payload.max_tokens ?? payload.max_completion_tokens ?? null,
    message_count: messages.length,
    messages: messages.map(m => ({role:m.role, sha256:hash(JSON.stringify(m)),
      bytes:Buffer.byteLength(JSON.stringify(m)), tool_call_id:m.tool_call_id ?? null,
      tool_calls:(m.tool_calls??[]).map(t=>t.id)})),
    tool_names:(payload.tools ?? []).map(t => t.function?.name).filter(Boolean),
  };
}

export function installGuard({ledger,trace,deadline,variant,quotaScript,credentialFile,fetchImpl=globalThis.fetch}) {
  if (!ledger || !trace || !Number.isFinite(deadline)) throw Error('Incomplete evaluation guard');
  const record = value => fs.appendFileSync(trace, JSON.stringify({timestamp:new Date().toISOString(),
    variant,...value})+'\n');
  const brokerPath=process.env.MEMWEAVE_EVAL_BROKER_CONFIG;
  if(process.env.MEMWEAVE_EVAL_PRIMARY_DEFAULT==='1'&&!brokerPath)throw Error('Primary transport authority missing');
  const broker=brokerPath?brokerFetch({configPath:brokerPath,record,fetchImpl,summarize:requestSummary}):null;
  const quota = operation => {
    const node=quotaScript.endsWith('.mjs');
    const executable=node?'flock':'python3';
    const args=node?['-w','2',ledger.replace(/\.[^/.]+$/,'.lock'),process.execPath,quotaScript,ledger,'--lock-held']:[quotaScript,ledger];
    const result=spawnSync(executable,args,{input:JSON.stringify(operation),encoding:'utf8',timeout:4000,
      env:{...process.env,NODE_OPTIONS:''}});
    if (result.status !== 0) throw Error('Evaluation quota admission/settlement rejected');
    return JSON.parse(result.stdout);
  };
  function authorized(input,init) {
    const headers=new Headers(init?.headers ?? input?.headers);
    // Control transport must not invoke the task-forbidden Zstd decoder.
    headers.set('accept-encoding','identity');
    if(!credentialFile)return {...init,headers};
    const auth=JSON.parse(fs.readFileSync(credentialFile,'utf8')).deepseek;
    if(auth?.type!=='api_key' || typeof auth.key!=='string' || !auth.key)throw Error('Guard credential unavailable');
    headers.set('authorization','Bearer '+auth.key);
    return {...init,headers};
  }
  return async function guardedFetch(input,init) {
    const url=new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
    const method=(init?.method ?? input?.method ?? 'GET').toUpperCase();
    if(url.hostname==='api.deepseek.com' && method==='GET' && /\/(?:v1\/)?models\/?$/.test(url.pathname)) {
      if(url.protocol!=='https:')throw Error('Guard credential endpoint rejected');
      if(broker)return broker(input,init);
      return fetchImpl(input,authorized(input,init));
    }
    if (url.hostname !== 'api.deepseek.com' || method !== 'POST') return fetchImpl(input,init);
    if(url.protocol!=='https:')throw Error('Guard credential endpoint rejected');
    if (url.pathname !== '/chat/completions' && url.pathname !== '/v1/chat/completions') {
      throw Error('Unregistered paid provider endpoint');
    }
    const raw=typeof init?.body === 'string' ? init.body : await input.clone().text();
    const payload=JSON.parse(raw);
    if (payload.model !== 'deepseek-flash' || payload.stream !== true) throw Error('Unbounded provider request');
    const arm=process.env.MEMWEAVE_EVAL_BUDGET_ARM??variant;
    const id=(process.env.MEMWEAVE_EVAL_RUN_ID ?? 'fixture')+':'+arm+':'+randomUUID();
    const maxOutput=payload.max_tokens ?? payload.max_completion_tokens;
    const configured=Number(process.env.MEMWEAVE_EVAL_MAX_OUTPUT ?? 384000);
    if (maxOutput>configured) throw Error('Output exceeds frozen experiment setting');
    if(broker)return broker(input,init);
    try { const reserved=quota({action:'reserve',id,arm,max_output:maxOutput,
      episode:process.env.MEMWEAVE_EVAL_RUN_ID ?? 'fixture',
      episode_budget:Number(process.env.MEMWEAVE_EVAL_EPISODE_BUDGET)||null,
      max_requests:Number(process.env.MEMWEAVE_EVAL_REQUEST_LIMIT)||null});
      record({event:'budget_reserved',request_id:id,charge_usd:reserved.charge_usd}); }
    catch (error) { record({event:'request_denied',request_id:id,reason:'quota_or_deadline'}); throw error; }
    record({event:'request_ready',request_id:id,...requestSummary(payload)});
    const controller=new AbortController();
    const remaining=deadline*1000-Date.now();
    if (remaining<=0) {record({event:'request_expired',request_id:id});throw Error('Evaluation deadline');}
    const timer=setTimeout(()=>controller.abort(),remaining);
    timer.unref();
    const signal=init?.signal ?? (typeof input === 'object' ? input.signal : undefined);
    const combined=signal ? AbortSignal.any([signal,controller.signal]) : controller.signal;
    let response;
    try {
      const requestInit=authorized(input,{...init,signal:combined});
      record({event:'http_attempt',request_id:id});
      response=await fetchImpl(input,requestInit);
      record({event:'http_response',request_id:id,status:response.status});
    } catch (error) {
      clearTimeout(timer);
      record({event:'http_error',request_id:id,error_class:error?.name ?? 'Error'});
      throw error;
    }
    if (!response.ok || !response.body) { clearTimeout(timer); return response; }
    const decoder=new TextDecoder();
    let pending='',usage=null,done=false,ended=false,responseModel=null;
    function finalize() {
      if (ended || !done || !usage) return;
      ended=true;
      clearTimeout(timer);
      let settled=false;
      try {const billed=quota({action:'settle',id,input:usage.input,output:usage.output,
        cache_input:Number.isInteger(usage.cache_hit)?usage.cache_hit:0});settled=true;
        record({event:'budget_settled',request_id:id,charge_usd:billed.charge_usd});}
      catch {record({event:'settlement_rejected',request_id:id});}
      record({event:'request_end',request_id:id,usage,settled,stream_done:done,response_model:responseModel});
    }
    function consume(line) {
      if (!line.startsWith('data:')) return;
      const data=line.slice(5).trim();
      if (data==='[DONE]') {done=true;finalize();return;}
      try {
        const item=JSON.parse(data);
        if (typeof item.model==='string') responseModel=item.model;
        if (Number.isInteger(item.usage?.prompt_tokens) && Number.isInteger(item.usage?.completion_tokens)) {
          usage={input:item.usage.prompt_tokens,output:item.usage.completion_tokens,
            cache_hit:item.usage.prompt_cache_hit_tokens ?? null,
            reasoning:item.usage.completion_tokens_details?.reasoning_tokens ?? null};
          finalize();
        }
      } catch {} // Provider/SDK validates the original bytes separately.
    }
    const stream=response.body.pipeThrough(new TransformStream({
      transform(chunk,controller) {
        pending+=decoder.decode(chunk,{stream:true});
        let split;
        while ((split=pending.indexOf('\n'))>=0) {
          consume(pending.slice(0,split).replace(/\r$/,'')); pending=pending.slice(split+1);
        }
        if (pending.length>4_000_000) throw Error('Unbounded provider SSE line');
        controller.enqueue(chunk);
      },
      flush() {
        pending+=decoder.decode();if(pending)consume(pending);
        clearTimeout(timer);
        finalize();
        if (!ended) record({event:'request_end',request_id:id,usage,settled:false,stream_done:done});
      },
    }));
    return new Response(stream,{status:response.status,statusText:response.statusText,headers:response.headers});
  };
}

