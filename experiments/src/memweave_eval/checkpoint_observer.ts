// Common evaluation-only extension: observes public tool events, adds no tools/prompts.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {workspaceSummary} from './fetch_guard.mjs';
import {attachBoundaries,captureCommittedState} from './request_boundary.ts';
import {attachGuard,guardReady} from './guard_bootstrap.mjs';
import {contentEvidence} from './content_evidence.mjs';
import {captureTaskRegistry} from './task_registry.mjs';
import {captureReferenceSources} from './reference_source.ts';
import {installTerminalCapture} from './terminal_capture.mjs';

export default function observe(pi: any) {
  const trace=process.env.MEMWEAVE_EVAL_TRACE;
  if (!trace) throw Error('Missing evaluation trace');
  installTerminalCapture();
  attachBoundaries(pi);
  const evidence=contentEvidence();
  pi.on('input',(event:any)=>{
    if(evidence)evidence.event('actor_input',{record_ref:evidence.put(event)});
  });
  // Public Pi 1.4 events: retain actual inputs/results, including blocked calls.
  // The content store is evaluation-only and never appears in actor context.
  for(const kind of ['tool_call','tool_execution_start','tool_execution_end','tool_result'] as const){
    pi.on(kind,(event:any,ctx:any)=>{
      if(evidence&&kind==='tool_call')evidence.event('task_registry_checkpoint',{
        phase:'before_tool',call_id:event.toolCallId,registry:captureTaskRegistry(),binding:captureCommittedState(ctx)});
      if(evidence&&kind==='tool_call'&&event.toolName==='memory_read')evidence.event('reference_source',{
        call_id:event.toolCallId,source:captureReferenceSources(ctx,event.input)});
      if(evidence)evidence.event(kind,{call_id:event.toolCallId,tool:event.toolName,
        parent_call_id:event.parentToolCallId??null,record_ref:evidence.put(event)});
    });
  }
  if(process.env.MEMWEAVE_EVAL_LEDGER) {
    // CLI dispatcher initialization precedes extension factories and can replace preloads.
    attachGuard();
    pi.on('before_provider_request',(_event:any,ctx:any)=>{
      if(!guardReady()){
        fs.appendFileSync(trace!,JSON.stringify({event:'guard_lost',timestamp:new Date().toISOString(),pid:process.pid})+'\n');
        ctx.abort();throw Error('Evaluation guard lost; request aborted');
      }
    });
  }
  function record(phase: string, call_id?: string) {
    const value={event:'workspace_checkpoint',phase,call_id,
      timestamp:new Date().toISOString(),variant:process.env.MEMWEAVE_EVAL_VARIANT,
      workspace:workspaceSummary()};
    fs.appendFileSync(trace!,JSON.stringify(value)+'\n');
    evidence?.event('workspace_checkpoint',value);
  }
  if(process.env.MEMWEAVE_EVAL_SEALED==='1'){
    const policy=process.env.MEMWEAVE_EVAL_POLICY_FILE;
    if(!policy||!fs.existsSync(policy))throw Error('Missing sealed Bash execution policy');
    process.env.BASH_ENV=policy;
    pi.on('tool_call',(event:any)=>{
    const args=event.input??{};
    const privatePath=['read','write','edit'].includes(event.toolName) && /memweave-eval|\.pi\/agent/.test(args.path??'');
    if(privatePath){
      fs.appendFileSync(trace!,JSON.stringify({event:'sealed_tool_rejected',executables:['private-asset'],tool:event.toolName,call_id:event.toolCallId,timestamp:new Date().toISOString()})+'\n');
      return {block:true,reason:'Sealed task permits C99 tools, not evaluation/controller runtimes or private assets.'};
    }
    });
  }
  pi.on('agent_start',(_event:any,ctx:any)=>{
    record('agent_start');
    evidence?.event('task_registry_checkpoint',{phase:'agent_start',registry:captureTaskRegistry(),binding:captureCommittedState(ctx)});
  });
  pi.on('tool_result',(event:any,ctx:any)=>{
    record('tool_result',event.toolCallId);
    // Also covers a call rejected before execute(), which has no execution_end.
    evidence?.event('task_registry_checkpoint',{phase:'after_tool',call_id:event.toolCallId,
      registry:captureTaskRegistry(),binding:captureCommittedState(ctx)});
  });
  let returns=0,sent=false;
  const after=Number(process.env.MEMWEAVE_EVAL_PROGRESS_AFTER ?? 80);
  pi.on('message_end',(event: any)=>{
    if(event.message?.role!=='assistant' || typeof event.message.usage!=='object')return;
    if(evidence)evidence.event('assistant_return',{
      boundary_id:(globalThis as any)[Symbol.for('memweave.eval.requestBoundary')]?.boundary_id??null,
      record_ref:evidence.put(event.message)});
    returns++;
    if(after>0 && !sent && returns>=after) {
      sent=true;
      fs.appendFileSync(trace!,JSON.stringify({event:'case_input',case_id:'marathon-progress-detour',
        after_assistant_returns:returns,timestamp:new Date().toISOString(),
        variant:process.env.MEMWEAVE_EVAL_VARIANT})+'\n');
      pi.sendUserMessage('请简短汇报进度，然后继续完成刚才的任务。',{deliverAs:'steer'});
    }
  });
  pi.on('tool_execution_end',(event:any,ctx:any)=>{
    record('tool_end',event.toolCallId);
    evidence?.event('task_registry_checkpoint',{phase:'after_tool',call_id:event.toolCallId,
      registry:captureTaskRegistry(),binding:captureCommittedState(ctx)});
    if(evidence && ['task_create','task_resume','state_append','append_fact','append_decision',
      'modify_fact','archive_fact','archive_decision','state_archive'].includes(event.toolName)){
      evidence.event('state_after_tool',{call_id:event.toolCallId,tool:event.toolName,
        state:captureCommittedState(ctx)});
    }
    if(!['memory_read','state_read'].includes(event.toolName))return;
    const text=(event.result?.content??[]).filter((p:any)=>p.type==='text').map((p:any)=>p.text).join('\n');
    let value:any;try{value=JSON.parse(text);}catch{}
    fs.appendFileSync(trace!,JSON.stringify({event:'reference_delivery',call_id:event.toolCallId,
      tool:event.toolName,is_error:typeof event.isError==='boolean'?event.isError:null,
      state_version:value?.state_version??(Number(text.match(/state_version: (\d+)/)?.[1])||null),
      task_id:value?.task_id??text.match(/task_id: (\S+)/)?.[1]??null,
      projection_sha256:createHash('sha256').update(text).digest('hex'),
      ranges:event.result?.details?.memweave_read?.ranges??null,
      expected_projection_source:'not_independently_resolved',timestamp:new Date().toISOString()})+'\n');
  });
  pi.on('agent_end',(_event:any,ctx:any)=>{
    record('agent_end');
    evidence?.event('task_registry_checkpoint',{phase:'agent_end',registry:captureTaskRegistry(),binding:captureCommittedState(ctx)});
  });
}
