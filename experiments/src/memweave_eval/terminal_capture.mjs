// Evaluation-only terminal observation, never a fabricated Pi tool/agent event.
import {contentEvidence} from './content_evidence.mjs';
import {workspaceSummary} from './fetch_guard.mjs';
import {captureTaskRegistry} from './task_registry.mjs';
const key=Symbol.for('memweave.eval.terminalCapture');

export function installTerminalCapture(){
  if(globalThis[key]||!process.env.MEMWEAVE_EVAL_CONTENT_STORE)return;
  globalThis[key]=true;let captured=false;
  process.on('SIGTERM',()=>{
    // Print-mode's synchronous signal listeners kill tracked tool children first.
    // We observe after all listeners, before its async dispose/exit continuation.
    queueMicrotask(()=>{
      if(captured)return;captured=true;
      const evidence=contentEvidence();
      const base={phase:'execution_terminated',signal:'SIGTERM',owner_pid:process.pid,
        scheduled_deadline:Number(process.env.MEMWEAVE_EVAL_DEADLINE),
        observation_source:'evaluation_signal_microtask_not_native_agent_end'};
      try{
        evidence.event('execution_terminated',{...base,capture_status:'CAPTURED',
          workspace:workspaceSummary(),registry:captureTaskRegistry({evidence})});
      }catch(error){
        evidence?.event('execution_terminated',{...base,capture_status:'FAILED',error_class:error?.name??'Error'});
      }
    });
  });
}
