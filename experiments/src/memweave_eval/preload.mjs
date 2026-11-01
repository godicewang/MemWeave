import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {attachGuard} from './guard_bootstrap.mjs';
import {spawn} from 'node:child_process';
import {disableZstd} from './sealed_runtime.mjs';

if (!process.env.MEMWEAVE_EVAL_LEDGER) throw Error('Evaluation quota configuration missing');
attachGuard();
if(process.env.MEMWEAVE_EVAL_SEALED==='1')disableZstd();
if (process.platform==='linux') {
  const node=process.env.MEMWEAVE_EVAL_QUOTA_BACKEND==='node';
  const watchdog=spawn(node?process.execPath:'python3',[path.join(path.dirname(fileURLToPath(import.meta.url)),
    node?'container_deadline.mjs':'container_deadline.py'),String(process.pid),process.env.MEMWEAVE_EVAL_DEADLINE,
    process.env.MEMWEAVE_EVAL_TRACE],{detached:true,stdio:'ignore',env:{...process.env,NODE_OPTIONS:''}});
  watchdog.on('error',()=>process.kill(process.pid,'SIGTERM'));
  watchdog.on('exit',code=>{if(code!==0 && Date.now()/1000<Number(process.env.MEMWEAVE_EVAL_DEADLINE))process.kill(process.pid,'SIGTERM');});
  watchdog.unref();
}
