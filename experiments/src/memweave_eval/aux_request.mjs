// Evaluator-only user simulator/judge requests use the same global atomic admission.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {installGuard} from './fetch_guard.mjs';
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const role=process.env.MEMWEAVE_EVAL_ROLE;
if(!['user_simulator','official_judge','preflight'].includes(role))throw Error('Unregistered auxiliary role');
const dir=path.dirname(fileURLToPath(import.meta.url));
const fetch=installGuard({ledger:process.env.MEMWEAVE_EVAL_LEDGER,trace:process.env.MEMWEAVE_EVAL_TRACE,
  deadline:Number(process.env.MEMWEAVE_EVAL_DEADLINE),variant:process.env.MEMWEAVE_EVAL_VARIANT,
  quotaScript:path.join(dir,process.env.MEMWEAVE_EVAL_QUOTA_BACKEND==='ipc'?'quota_ipc.mjs':'budget_guard.py'),credentialFile:process.env.MEMWEAVE_EVAL_CREDENTIAL_FILE});
const payload={model:'deepseek-flash',stream:true,stream_options:{include_usage:true},
  max_tokens:input.max_tokens,messages:input.messages,thinking:{type:'disabled'},
  ...(input.temperature===null?{}:{temperature:input.temperature??0}),
  ...(input.json?{response_format:{type:'json_object'}}:{})};
const response=await fetch('https://api.deepseek.com/chat/completions',{
  method:'POST',body:JSON.stringify(payload),headers:{'content-type':'application/json'}});
if(!response.ok)throw Error('Auxiliary provider returned HTTP '+response.status);
const raw=await response.text();let text='',usage=null,done=false;
for(const line of raw.split('\n')){
  if(!line.startsWith('data:'))continue;
  const data=line.slice(5).trim();if(data==='[DONE]'){done=true;continue;}
  const value=JSON.parse(data);text+=value.choices?.[0]?.delta?.content??'';
  if(value.usage)usage=value.usage;
}
if(!done||!usage)throw Error('Auxiliary response lacks completed provider usage');
process.stdout.write(JSON.stringify({text,usage}));
