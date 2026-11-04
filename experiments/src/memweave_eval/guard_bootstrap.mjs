import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {installGuard} from './fetch_guard.mjs';
const marker=Symbol.for('memweave.eval.guard');

export function attachGuard() {
  if(!process.env.MEMWEAVE_EVAL_LEDGER)throw Error('Evaluation ledger missing');
  if(globalThis[marker]?.fetch===globalThis.fetch)return globalThis[marker];
  const guarded=installGuard({ledger:process.env.MEMWEAVE_EVAL_LEDGER,
    trace:process.env.MEMWEAVE_EVAL_TRACE,deadline:Number(process.env.MEMWEAVE_EVAL_DEADLINE),
    variant:process.env.MEMWEAVE_EVAL_VARIANT,
    credentialFile:process.env.MEMWEAVE_EVAL_CREDENTIAL_FILE,
    quotaScript:path.join(path.dirname(fileURLToPath(import.meta.url)),
      process.env.MEMWEAVE_EVAL_QUOTA_BACKEND==='node'?'budget_guard.mjs':'budget_guard.py')});
  globalThis.fetch=guarded;
  globalThis[marker]={fetch:guarded,pid:process.pid};
  fs.appendFileSync(process.env.MEMWEAVE_EVAL_TRACE,JSON.stringify({event:'guard_attached',
    timestamp:new Date().toISOString(),pid:process.pid,title:process.title})+'\n');
  return globalThis[marker];
}

export function guardReady() {return Boolean(globalThis[marker]?.fetch===globalThis.fetch);}
