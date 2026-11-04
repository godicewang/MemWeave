// Standalone evaluator observer for an already-frozen actor, no network/API use.
import fs from 'node:fs';
import {contentEvidence}from'./content_evidence.mjs';
import {workspaceSummary}from'./fetch_guard.mjs';
import {captureTaskRegistry}from'./task_registry.mjs';

export async function observeDeadline({trace,owner_pid,deadline,stop_after=deadline+30,poll_ms=50}){
  if(!Number.isInteger(owner_pid)||owner_pid<=1||!Number.isFinite(deadline)||!Number.isFinite(stop_after)||
    stop_after<deadline||stop_after>deadline+60)throw Error('Invalid bound deadline observer');
  const evidence=contentEvidence();if(!evidence)throw Error('Missing evaluator store');
  evidence.event('deadline_observer_started',{role:'observer',owner_pid,scheduled_deadline:deadline,read_only:true});
  while(Date.now()/1000<=stop_after){
    if(Date.now()/1000<deadline-2){
      await new Promise(resolve=>setTimeout(resolve,Math.min(5000,(deadline-2-Date.now()/1000)*1000)));
      continue;
    }
    let lines=[];try{lines=fs.readFileSync(trace,'utf8').trimEnd().split('\n').filter(Boolean).map(s=>JSON.parse(s));}catch{}
    const stop=lines.find(e=>e.event==='local_deadline_stop'&&e.pid===owner_pid&&Math.abs(
      (typeof e.timestamp==='number'?e.timestamp:Date.parse(e.timestamp)/1000)-deadline)<=5);
    if(stop){
      // The actor's original signal listeners kill tracked children synchronously.
      // Capture is independent evidence, never represented as a native callback.
      await new Promise(resolve=>setTimeout(resolve,250));
      const base={role:'observer',phase:'execution_deadline_snapshot',owner_pid,scheduled_deadline:deadline,
        observation_source:'evaluation_external_after_deadline_guard',guard_stop_ref:evidence.put(stop)};
      try{
        evidence.event('execution_deadline_snapshot',{...base,capture_status:'CAPTURED',
          workspace:workspaceSummary(),registry:captureTaskRegistry({evidence})});
        return {captured:true};
      }catch(error){
        evidence.event('execution_deadline_snapshot',{...base,capture_status:'FAILED',error_class:error?.name??'Error'});
        return {captured:false};
      }
    }
    await new Promise(resolve=>setTimeout(resolve,poll_ms));
  }
  evidence.event('deadline_observer_expired',{role:'observer',owner_pid,scheduled_deadline:deadline});
  return {captured:false,reason:'no_actual_bound_guard_stop'};
}
