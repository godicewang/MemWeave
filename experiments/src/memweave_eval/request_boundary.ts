// Read-only evaluation boundary. Hashes/IDs only; never injects context or saves State bodies.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash,randomUUID} from 'node:crypto';
export const boundaryKey=Symbol.for('memweave.eval.requestBoundary');
const hash=(value:any)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
export function attachBoundaries(pi:any) {
  let prepared:any=null;
  pi.on('context_with_system',(_event:any,ctx:any)=>{
    let task:any=null;
    for(const e of ctx.sessionManager.getBranch()) {
      if(e.type==='custom' && e.customType==='memweave.restart.v1')task=null;
      if(e.type==='custom' && e.customType==='memweave.scope.v1')task=e.data?.task_id??null;
    }
    prepared={boundary_id:randomUUID(),expected_task_id:task,boundary_source:'atomic_journal_before_context_transform'};
    if(task && /^[^/\\:\x00]+$/.test(task)) {
      try {
        const memory=path.join(os.homedir(),'.pi','memory');
        // Task IDs are global; require a unique journal, never choose a same-name candidate.
        const files=fs.readdirSync(memory,{withFileTypes:true}).filter(e=>e.isDirectory())
          .map(e=>path.join(memory,e.name,'tasks',task,'state.json')).filter(f=>fs.existsSync(f));
        if(files.length!==1)throw Error('ambiguous or missing journal');
        const bytes=fs.readFileSync(files[0],'utf8');
        if(!bytes.endsWith('\n'))throw Error('incomplete journal');
        const rows=bytes.trimEnd().split('\n').map(line=>JSON.parse(line));
        prepared.expected_version_at_prepare=rows.length;
        prepared.expected_journal_sha256=createHash('sha256').update(bytes).digest('hex');
      } catch {prepared.boundary_error='authoritative_journal_unavailable';}
    }
  });
  pi.on('before_provider_request',(event:any)=>{
    const payload=event.payload;
    (globalThis as any)[boundaryKey]={...prepared,prepared_messages_sha256:hash(payload?.messages??[]),
      prepared_messages:(payload?.messages??[]).map((m:any)=>({role:m.role,sha256:hash(m),
        tool_call_id:m.tool_call_id??null,tool_calls:(m.tool_calls??[]).map((t:any)=>t.id)}))};
  });
}
