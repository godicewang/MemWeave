// Common evaluation-only extension: observes public tool events, adds no tools/prompts.
import fs from 'node:fs';
import {workspaceSummary} from './fetch_guard.mjs';
import {attachGuard,guardReady} from './guard_bootstrap.mjs';

export default function observe(pi: any) {
  const trace=process.env.MEMWEAVE_EVAL_TRACE;
  if (!trace) throw Error('Missing evaluation trace');
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
    fs.appendFileSync(trace!,JSON.stringify({event:'workspace_checkpoint',phase,call_id,
      timestamp:new Date().toISOString(),variant:process.env.MEMWEAVE_EVAL_VARIANT,
      workspace:workspaceSummary()})+'\n');
  }
  pi.on('agent_start',()=>record('agent_start'));
  let returns=0,sent=false;
  const after=Number(process.env.MEMWEAVE_EVAL_PROGRESS_AFTER ?? 80);
  pi.on('message_end',(event: any)=>{
    if(event.message?.role!=='assistant' || typeof event.message.usage!=='object')return;
    returns++;
    if(!sent && returns>=after) {
      sent=true;
      fs.appendFileSync(trace!,JSON.stringify({event:'case_input',case_id:'wasm-progress-detour',
        after_assistant_returns:returns,timestamp:new Date().toISOString(),
        variant:process.env.MEMWEAVE_EVAL_VARIANT})+'\n');
      pi.sendUserMessage('请简短汇报进度，然后继续完成刚才的任务。',{deliverAs:'steer'});
    }
  });
  pi.on('tool_execution_end',(event: any)=>record('tool_end',event.toolCallId));
  pi.on('agent_end',()=>record('agent_end'));
}
