// Transport guard attachment only. Does not add tasks, prompts, tools or scoring hooks.
import fs from 'node:fs';
import {attachGuard,guardReady} from './guard_bootstrap.mjs';

export default function guard(pi: any) {
  if (!process.env.MEMWEAVE_EVAL_LEDGER) return;
  const trace=process.env.MEMWEAVE_EVAL_TRACE;
  if (!trace) throw Error('Missing evaluation trace');
  // Pi initializes its dispatcher before extension factories; reattach the guard here.
  attachGuard();
  pi.on('before_provider_request',(_event: any,ctx: any)=>{
    if (guardReady()) return;
    fs.appendFileSync(trace,JSON.stringify({event:'guard_lost',
      timestamp:new Date().toISOString(),pid:process.pid})+'\n');
    ctx.abort();
    throw Error('Evaluation guard lost; request aborted');
  });
}
