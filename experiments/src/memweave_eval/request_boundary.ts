// Read-only evaluation boundary. Hashes/IDs only; never injects context or saves State bodies.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash,randomUUID} from 'node:crypto';
export const boundaryKey=Symbol.for('memweave.eval.requestBoundary');
const hash=(value:any)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
export function stateJournalBoundary(ctx:any,source='atomic_journal_before_context_transform') {
  const observed:any={expected_task_id:null,boundary_source:source};
  if(!ctx?.sessionManager?.getBranch) return {...observed,boundary_error:'state_context_unavailable'};
  let task:any=null;
  for(const e of ctx.sessionManager.getBranch()) {
    if(e.type==='custom' && e.customType==='memweave.restart.v1')task=null;
    if(e.type==='custom' && e.customType==='memweave.scope.v1')task=e.data?.task_id??null;
  }
  observed.expected_task_id=task;
  if(task===null)return observed; // Native/unbound is a real lifecycle state, not version zero.
  try {
    if(typeof task!=='string'||!/^[^/\\:\x00]+$/.test(task))throw Error('invalid task binding');
    const memory=path.join(os.homedir(),'.pi','memory');
    const files=fs.readdirSync(memory,{withFileTypes:true}).filter(e=>e.isDirectory())
      .map(e=>path.join(memory,e.name,'tasks',task,'state.json')).filter(f=>fs.existsSync(f));
    if(files.length!==1)throw Error('ambiguous or missing journal');
    const bytes=fs.readFileSync(files[0],'utf8');
    if(!bytes.endsWith('\n'))throw Error('incomplete journal');
    const rows=bytes.trimEnd().split('\n').map(line=>JSON.parse(line));
    observed.expected_version_at_prepare=rows.length;
    observed.expected_journal_sha256=createHash('sha256').update(bytes).digest('hex');
  } catch {observed.boundary_error='authoritative_journal_unavailable';}
  return observed;
}

export function attachBoundaries(pi:any) {
  let prepared:any=null;
  pi.on('context_with_system',(_event:any,ctx:any)=>{
    prepared={boundary_id:randomUUID(),...stateJournalBoundary(ctx)};
  });
  pi.on('before_provider_request',(event:any)=>{
    const payload=event.payload;
    (globalThis as any)[boundaryKey]={...prepared,prepared_messages_sha256:hash(payload?.messages??[]),
      prepared_messages:(payload?.messages??[]).map((m:any)=>({role:m.role,sha256:hash(m),
        tool_call_id:m.tool_call_id??null,tool_calls:(m.tool_calls??[]).map((t:any)=>t.id)}))};
  });
}
