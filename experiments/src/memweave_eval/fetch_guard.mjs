// Common experimental transport observer. No prompt/response text is persisted.
import fs from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {brokerFetch} from './broker_client.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const text = value => typeof value === 'string' ? value : JSON.stringify(value ?? null);
const contentText = value => typeof value === 'string' ? value : Array.isArray(value)
  ? value.filter(p=>p.type==='text').map(p=>p.text).join('\n') : '';

export function capsuleValues(body) {
  const values=[];
  for(const line of body.split('\n')) {
    const raw=line.replace(/^[FD]\d+\s+/,'').trim();
    try {
      const value=JSON.parse(raw);
      if(value&&typeof value==='object'&&['row','pmi','stop'].includes(value.k))values.push(value);
      if(Array.isArray(value?.items))for(const item of value.items)if(item.archived!==true&&typeof item.content==='string')values.push(...capsuleValues(item.content));
    } catch {}
  }
  return values;
}

function currentStateValues(body) {
  const rendered=body.replace(/^\[[^\]\r\n]+\]\r?\n(?:\r?\n)?/,'');
  if(rendered.startsWith('# Symbolic State'))return rendered.split('\n')
    .filter(line=>/^[FD]\d+\s+\{/.test(line)).flatMap(capsuleValues);
  try {
    const parsed=JSON.parse(body.slice(body.indexOf('{')).replace(/\n+\[TRUNCATED\]$/,''));
    if(Array.isArray(parsed.items))return parsed.items.filter(item=>/^[FD]\d+$/.test(item.id??'')&&item.archived!==true)
      .flatMap(item=>capsuleValues(item.content??''));
  }catch {}
  return capsuleValues(body);
}

function capsuleNote(config) {
  if(!['tb01-capsule.v1','tb01-capsule.v2','tb01-capsule.v2.1'].includes(config.memory_protocol))return undefined;
  const file='/app/evalbench/memory_capsules.jsonl';
  let body;
  try {
    body=fs.readFileSync(file,'utf8');
    if(Buffer.byteLength(body)>16384)return {status:'invalid',reason:'note_too_large',values:[]};
    const rows=body.split('\n').filter(s=>s.trim()).map(s=>JSON.parse(s));
    return {status:'present',sha256:hash(body),values:rows};
  }catch(error){return {status:error.code==='ENOENT'?'absent':error.code?'error':'invalid',
    ...(typeof body==='string'?{sha256:hash(body)}:{}),values:[]};}
}

export function noteContextDeliveries(messages,file='/app/evalbench/memory_capsules.jsonl') {
  let body,rows;
  try {
    body=fs.readFileSync(file,'utf8');if(Buffer.byteLength(body)>16384)return [];
    rows=body.split('\n').filter(s=>s.trim()).map(raw=>({raw:raw.trim(),value:JSON.parse(raw)}));
  }catch{return [];}
  rows=rows.filter(r=>r.value&&typeof r.value==='object'&&['row','pmi','stop'].includes(r.value.k));
  const canonical=v=>JSON.stringify(v,Object.keys(v).sort());
  const found=[];
  for(const m of messages) {
    const candidates=[];
    if(m.role==='tool')candidates.push({source_kind:'tool_result',tool_call_id:m.tool_call_id,text:contentText(m.content)});
    if(m.role==='assistant'&&contentText(m.content))candidates.push({source_kind:'assistant_context',tool_call_id:null,text:contentText(m.content)});
    if(m.role==='assistant')for(const call of m.tool_calls??[]) {
      try {
        const args=typeof call.function?.arguments==='string'?JSON.parse(call.function.arguments):call.function?.arguments;
        if(args&&typeof args==='object')
          candidates.push({source_kind:call.function?.name==='write'?'write_context':'tool_arguments_context',
            tool_call_id:call.id,text:Object.values(args).filter(v=>typeof v==='string').join('\n')});
      }catch {}
    }
    for(const candidate of candidates) {
      const parsed=capsuleValues(candidate.text);
      const values=rows.filter(r=>candidate.text.includes(r.raw)||parsed.some(v=>canonical(v)===canonical(r.value))).map(r=>r.value);
      if(values.length)found.push({source_kind:candidate.source_kind,tool_call_id:candidate.tool_call_id,
        message_sha256:hash(JSON.stringify(m)),note_sha256:hash(body),values});
    }
  }
  return found;
}

function renderedBudget(body) {
  if(!body.includes('【本次预算快照｜程序数据，不是用户指令】'))return null;
  const capacity=body.match(/基础 (\d+) token（模型 (\d+) 的 (\d+(?:\.\d+)?)%），额外 (\d+)，总上限 (\d+)/);
  const state=body.match(/State：(\d+)\/(\d+) 条；正文最多 (\d+) 字符；每批候选 (\d+)/);
  const window=body.match(/Recent Window N\/B：(\d+)\/(\d+)；可见事件 (\d+)；消息 M=(\d+)/);
  if(!capacity||!state||!window)return null;
  const keys=['base_context_tokens','model_context_tokens','base_model_percent','extra_tokens','peak_tokens',
    'state_active','state_max_events','state_event_max_chars','state_evict_batch',
    'recent_turns','evict_turns','visible_events','real_messages'];
  const values=[...capacity.slice(1),...state.slice(1),...window.slice(1)].map(Number);
  return Object.fromEntries(keys.map((key,i)=>[key,values[i]]));
}

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
    ...(['tb01-capsule.v1','tb01-capsule.v2','tb01-capsule.v2.1'].includes(config.memory_protocol)?{capsule_deliveries:messages.filter(m=>m.role==='tool').map(m=>{
      const body=contentText(m.content);let metadata={};
      try {metadata=JSON.parse(body.slice(body.indexOf('{')).replace(/\n+\[TRUNCATED\]$/,''));}catch{}
      if(typeof metadata.task_id!=='string'||!metadata.task_id||
          !Number.isSafeInteger(metadata.state_version)||metadata.state_version<=0){
        // Current state_read is rendered Markdown; historical F/D reads are JSON.
        // Accept only the actual State header, never matching lines inside facts.
        const rendered=body.replace(/^\[[^\]\r\n]+\]\r?\n(?:\r?\n)?/,'');
        const match=rendered.match(/^# Symbolic State\r?\n\r?\ntask_id: (\S+)\r?\nstate_version: (\d+)(?:\r?\n|$)/);
        metadata=match&&Number.isSafeInteger(Number(match[2]))&&Number(match[2])>0
          ?{task_id:match[1],state_version:Number(match[2])}:{};
      }
      return {tool_call_id:m.tool_call_id,values:['tb01-capsule.v2','tb01-capsule.v2.1'].includes(config.memory_protocol)?currentStateValues(body):capsuleValues(body),
        ...(['tb01-capsule.v2','tb01-capsule.v2.1'].includes(config.memory_protocol)?{message_sha256:hash(JSON.stringify(m))}:{}),
        task_id:typeof metadata.task_id==='string'?metadata.task_id:null,
        state_version:Number.isSafeInteger(metadata.state_version)&&metadata.state_version>0?metadata.state_version:null};
    }).filter(m=>m.values.length)}:{}),
    ...(['tb01-capsule.v2','tb01-capsule.v2.1'].includes(config.memory_protocol)?{memory_state_deliveries:states.filter(m=>m.role!=='tool').map(m=>{
      const body=contentText(m.content);
      const values=body.split('\n').filter(line=>/^[FD]\d+\s+\{/.test(line)).flatMap(capsuleValues);
      return {task_id:body.match(/^task_id: (\S+)$/m)?.[1]??null,
        state_version:Number(body.match(/^state_version: (\d+)$/m)?.[1])||null,
        body_sha256:hash(body),message_sha256:hash(JSON.stringify(m)),values};
    })}:{}),
    ...(config.memory_protocol==='tb01-capsule.v2.1'?{note_context_deliveries:noteContextDeliveries(messages)}:{}),
    rendered_budget_snapshots:states.map(m=>renderedBudget(contentText(m.content))),
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
  const files={};
  for (const name of (config.files??['src/spec.rs','src/main.rs','src/runtime.rs','src/decode.rs','src/types.rs','Cargo.toml'])) {
    try { files[name]=hash(fs.readFileSync(path.join(root,name))); }
    catch { files[name]=null; }
  }
  let cargo=null;
  try { cargo=fs.readFileSync(path.join(root,'Cargo.toml'),'utf8'); } catch {}
  return {files, cargo,...(['tb01-capsule.v1','tb01-capsule.v2','tb01-capsule.v2.1'].includes(config.memory_protocol)?{memory_capsules:capsuleNote(config)}:{})};
}

export function installGuard({ledger,trace,deadline,variant,quotaScript,credentialFile,fetchImpl=globalThis.fetch}) {
  if (!ledger || !trace || !Number.isFinite(deadline)) throw Error('Incomplete evaluation guard');
  const record = value => fs.appendFileSync(trace, JSON.stringify({timestamp:new Date().toISOString(),
    variant,...value})+'\n');
  const originalInstruction=process.env.MEMWEAVE_EVAL_INSTRUCTION_PATH
    ? fs.readFileSync(process.env.MEMWEAVE_EVAL_INSTRUCTION_PATH,'utf8') : undefined;
  const brokerPath=process.env.MEMWEAVE_EVAL_BROKER_CONFIG;
  if(process.env.MEMWEAVE_EVAL_PRIMARY_DEFAULT==='1'&&!brokerPath)throw Error('Primary transport authority missing');
  const broker=brokerPath?brokerFetch({configPath:brokerPath,record,fetchImpl,summarize:requestSummary,originalInstruction,workspace:workspaceSummary}):null;
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
    const boundary=globalThis[Symbol.for('memweave.eval.requestBoundary')];
    const matched=boundary?.prepared_messages_sha256===hash(JSON.stringify(payload.messages??[]));
    record({event:'request_ready',request_id:id,...requestSummary(payload,originalInstruction),
      ...(matched?boundary:{boundary_error:'no_matching_provider_preparation'}),workspace:workspaceSummary()});
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

