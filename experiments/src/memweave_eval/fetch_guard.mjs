// Common experimental transport observer. No prompt/response text is persisted.
import fs from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {contentEvidence} from './content_evidence.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const text = value => typeof value === 'string' ? value : JSON.stringify(value ?? null);
const contentText = value => typeof value === 'string' ? value : Array.isArray(value)
  ? value.filter(p=>p.type==='text').map(p=>p.text).join('\n') : '';

export function protectedConstraint(content) {
  const lines=content.split('\n').filter(line=>/^[FD]\d+\s/.test(line));
  const values=['spec.rs','main.rs'].map(file=>{
    const candidates=lines.filter(line=>line.includes(file));
    let recognized=false,ambiguous=false;
    for(const line of candidates) {
      const negative=/不得|禁止|不可|只读|不修改|不要修改|保持.{0,20}不变|do not|must not|never|unchanged/i.test(line);
      const positive=/允许修改|可以修改|may modify|can modify|must modify/i.test(line);
      if(positive && !negative)return false;
      if(positive && negative)ambiguous=true;
      if(negative && !positive)recognized=true;
    }
    return ambiguous ? null : recognized ? true : null;
  });
  return values.includes(false) ? false : values.every(value=>value===true) ? true : null;
}

export function requestSummary(payload, originalInstruction) {
  const messages = payload.messages ?? [];
  let config={};try{config=JSON.parse(process.env.MEMWEAVE_EVAL_WORKSPACE??'{}');}catch{}
  const states = messages.filter(m => contentText(m.content).startsWith('# Symbolic State'));
  return {
    payload_sha256: hash(JSON.stringify(payload)),
    payload_bytes: Buffer.byteLength(JSON.stringify(payload)),
    model: payload.model,
    thinking:payload.thinking ?? payload.reasoning_effort ?? payload.reasoning ?? null,
    max_output: payload.max_tokens ?? payload.max_completion_tokens ?? null,
    message_count: messages.length,
    messages: messages.map(m => ({role:m.role, sha256:hash(JSON.stringify(m)),
      bytes:Buffer.byteLength(JSON.stringify(m)), tool_call_id:m.tool_call_id ?? null, tool_calls:(m.tool_calls??[]).map(t=>t.id)})),
    tool_names:(payload.tools ?? []).map(t => t.function?.name).filter(Boolean),
    request_kind:(payload.tools ?? []).some(t=>t.function?.name==='bash') ? 'agent' : 'auxiliary_or_unknown',
    system_hashes:messages.filter(m => m.role === 'system').map(m => hash(text(m.content))),
    rule_block_count:messages.filter(m=>m.role==='system').reduce((n,m)=>n+contentText(m.content).split('# 长程任务记忆协议').length-1,0),
    state_blocks:states.map(m => ({sha256:hash(contentText(m.content)),
      task_id:contentText(m.content).match(/task_id: (\S+)/)?.[1] ?? null,
      version:Number(contentText(m.content).match(/state_version: (\d+)/)?.[1]) || null})),
    state_constraint_bits:Object.fromEntries(Object.entries(config.state_constraints??{}).map(([key,pattern])=>{
      const body=states.map(m=>contentText(m.content)).join('\n');
      return [key,body && new RegExp(pattern,'i').test(body)?true:null];
    })),
    state_protected_constraint:states.length ? protectedConstraint(states.map(m=>contentText(m.content)).join('\n')) : null,
    original_instruction_visible:originalInstruction ? messages.some(m=>
      !contentText(m.content).startsWith('# Symbolic State') && contentText(m.content).includes(originalInstruction)) : null,
    unresolved_template:messages.some(m => m.role==='system' && /\{\{(?:recent_turns|batch_size|state_[a-z_]+)\}\}/.test(text(m.content))),
    process_usage:process.resourceUsage(),
    process_rss_bytes:process.memoryUsage().rss,
  };
}

export function workspaceSummary(root='/app/interpreter') {
  let config={};try{config=JSON.parse(process.env.MEMWEAVE_EVAL_WORKSPACE??'{}');}catch{}
  root=config.root??root;
  const files={},file_status={};
  for (const name of (config.files??['src/spec.rs','src/main.rs','src/runtime.rs','src/decode.rs','src/types.rs','Cargo.toml'])) {
    try { files[name]=hash(fs.readFileSync(path.join(root,name)));file_status[name]={status:'present'}; }
    catch(error) { files[name]=null;file_status[name]={status:error?.code==='ENOENT'?'absent':'unreadable',error_class:error?.code??'Error'}; }
  }
  let cargo=null;
  try { cargo=fs.readFileSync(path.join(root,'Cargo.toml'),'utf8'); } catch {}
  return {files,file_status,cargo}; // Small task-specific configuration; never source or answers.
}

export function installGuard({ledger,trace,deadline,variant,quotaScript,credentialFile,fetchImpl=globalThis.fetch}) {
  if (!ledger || !trace || !Number.isFinite(deadline)) throw Error('Incomplete evaluation guard');
  const record = value => fs.appendFileSync(trace, JSON.stringify({timestamp:new Date().toISOString(),
    variant,...value})+'\n');
  const originalInstruction=process.env.MEMWEAVE_EVAL_INSTRUCTION_PATH
    ? fs.readFileSync(process.env.MEMWEAVE_EVAL_INSTRUCTION_PATH,'utf8') : undefined;
  const quota = operation => {
    const ipc=quotaScript.endsWith('/quota_ipc.mjs');
    const node=quotaScript.endsWith('.mjs');
    const executable=ipc?process.execPath:node?'flock':'python3';
    const args=ipc?[quotaScript,ledger]:node?['-w','2',ledger.replace(/\.[^/.]+$/,'.lock'),process.execPath,quotaScript,ledger,'--lock-held']:[quotaScript,ledger];
    const result=spawnSync(executable,args,{input:JSON.stringify(operation),encoding:'utf8',timeout:ipc?13000:4000,
      env:{...process.env,NODE_OPTIONS:''}});
    if (result.status !== 0) {
      let detail;try{detail=JSON.parse(result.stderr);}catch{}
      const failure={operation:operation.action,exit_status:result.status,signal:result.signal??null,
        error_class:detail?.error_class??result.error?.code??'QuotaSubprocessError',
        reason:detail?.reason??'quota_subprocess_failed'};
      record({event:'quota_operation_rejected',request_id:operation.id,...failure});
      throw Object.assign(Error('Evaluation quota admission/settlement rejected'),{quota_failure:failure});
    }
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
    if(Date.now()/1000>=deadline){
      record({event:'request_denied',request_id:id,reason:'local_deadline_before_reservation'});
      throw Error('Evaluation deadline');
    }
    const evidence=contentEvidence();
    // Capture before reservation: a local write failure must dispatch zero upstream requests.
    const payloadRef=evidence?.put(raw);
    const maxOutput=payload.max_tokens ?? payload.max_completion_tokens;
    const configured=Number(process.env.MEMWEAVE_EVAL_MAX_OUTPUT ?? 384000);
    if (maxOutput>configured) throw Error('Output exceeds frozen experiment setting');
    try { const reserved=quota({action:'reserve',id,arm,max_output:maxOutput,
      episode:process.env.MEMWEAVE_EVAL_RUN_ID ?? 'fixture',
      episode_budget:Number(process.env.MEMWEAVE_EVAL_EPISODE_BUDGET)||null,
      max_requests:Number(process.env.MEMWEAVE_EVAL_REQUEST_LIMIT)||null});
      record({event:'budget_reserved',request_id:id,charge_usd:reserved.charge_usd}); }
    catch (error) { record({event:'request_denied',request_id:id,reason:'quota_or_deadline'}); throw error; }
    const boundary=globalThis[Symbol.for('memweave.eval.requestBoundary')];
    const matched=boundary?.prepared_messages_sha256===hash(JSON.stringify(payload.messages??[]));
    const workspace=workspaceSummary();
    record({event:'request_ready',request_id:id,...requestSummary(payload,originalInstruction),
      ...(matched?boundary:{boundary_error:'no_matching_provider_preparation'}),
      ...(payloadRef?{payload_ref:payloadRef}:{}),workspace});
    evidence?.event('request_ready',{request_id:id,payload_ref:payloadRef,prepared_boundary:matched?boundary:null,workspace});
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
      evidence?.event('http_response',{request_id:id,status:response.status,
        provider_request_id:response.headers.get('x-request-id')??response.headers.get('request-id')});
    } catch (error) {
      clearTimeout(timer);
      record({event:'http_error',request_id:id,error_class:error?.name ?? 'Error'});
      throw error;
    }
    if (!response.ok || !response.body) {
      if(evidence)evidence.event('provider_error_receipt',{request_id:id,status:response.status,
        body_ref:evidence.put(Buffer.from(await response.clone().arrayBuffer()))});
      clearTimeout(timer); return response;
    }
    const decoder=new TextDecoder();
    let pending='',usage=null,done=false,ended=false,responseModel=null,chunkIndex=0;
    function finalize() {
      if (ended || !done || !usage) return;
      ended=true;
      clearTimeout(timer);
      let settled=false;
      try {const billed=quota({action:'settle',id,input:usage.input,output:usage.output,
        cache_input:Number.isInteger(usage.cache_hit)?usage.cache_hit:0});settled=true;
        record({event:'budget_settled',request_id:id,charge_usd:billed.charge_usd});}
      catch(error) {record({event:'settlement_rejected',request_id:id,
        quota_failure:error?.quota_failure??{reason:'quota_response_not_valid_JSON'}});}
      record({event:'request_end',request_id:id,usage,settled,stream_done:done,response_model:responseModel});
      evidence?.event('provider_receipt',{request_id:id,usage,settled,stream_done:done,response_model:responseModel,chunks:chunkIndex});
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
        if(evidence)evidence.event('response_chunk',{request_id:id,ordinal:++chunkIndex,chunk_ref:evidence.put(Buffer.from(chunk))});
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

