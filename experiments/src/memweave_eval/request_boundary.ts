// Read-only evaluation boundary. Hashes/IDs only; never injects context or saves State bodies.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash,randomUUID} from 'node:crypto';
import {contentEvidence} from './content_evidence.mjs';
export const boundaryKey=Symbol.for('memweave.eval.requestBoundary');
const hash=(value:any)=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
export function captureCommittedState(ctx:any){
  const evidence=contentEvidence();let task:any=null;
  if(!ctx?.sessionManager?.getBranch)return {task_id:null,status:'SESSION_CONTEXT_UNAVAILABLE'};
  for(const entry of ctx.sessionManager.getBranch()){
    if(entry.type==='custom' && entry.customType==='memweave.restart.v1')task=null;
    if(entry.type==='custom' && entry.customType==='memweave.scope.v1')task=entry.data?.task_id??null;
  }
  const record:any={task_id:task};
  if(!task)return {...record,status:'NO_BOUND_TASK'};
  try{
    if(!/^[^/\\:\x00]+$/.test(task))throw Error('invalid task identifier');
    const memory=path.join(os.homedir(),'.pi','memory');
    const files=fs.readdirSync(memory,{withFileTypes:true}).filter(e=>e.isDirectory())
      .map(e=>path.join(memory,e.name,'tasks',task,'state.json')).filter(f=>fs.existsSync(f));
    if(files.length!==1)throw Error('ambiguous journal');
    const bytes=fs.readFileSync(files[0],'utf8');
    if(!bytes.endsWith('\n'))throw Error('incomplete journal');
    const rows=bytes.trimEnd().split('\n').map(line=>JSON.parse(line));
    return {...record,status:'CAPTURED',version:rows.length,
      journal_sha256:createHash('sha256').update(bytes).digest('hex'),
      journal_ref:evidence?.put(bytes)??null};
  }catch{return {...record,status:'AUTHORITATIVE_JOURNAL_UNAVAILABLE'};}
}
export function attachBoundaries(pi:any) {
  let prepared:any=null;
  pi.on('context_with_system',(_event:any,ctx:any)=>{
    let task:any=null;
    for(const e of ctx.sessionManager.getBranch()) {
      if(e.type==='custom' && e.customType==='memweave.restart.v1')task=null;
      if(e.type==='custom' && e.customType==='memweave.scope.v1')task=e.data?.task_id??null;
    }
    prepared={boundary_id:randomUUID(),expected_task_id:task,boundary_source:'atomic_journal_before_context_transform'};
    const evidence=contentEvidence();
    if(evidence){
      const rule=path.join(os.homedir(),'.pi','memory','rule.md');
      if(fs.existsSync(rule))prepared.expected_rule_template_ref=evidence.put(fs.readFileSync(rule));
    }
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
        const evidence=contentEvidence();
        // CAS deduplicates unchanged journals. No snapshot is injected or persisted to Session.
        if(evidence)prepared.expected_journal_ref=evidence.put(bytes);
      } catch {prepared.boundary_error='authoritative_journal_unavailable';}
    }
  });
  pi.on('before_provider_request',(event:any,ctx:any)=>{
    const payload=event.payload;
    const evidence=contentEvidence();
    if(evidence){
      const latest:any={};
      for(const entry of ctx.sessionManager.getBranch()){
        if(entry.type==='custom' && /^memweave\.(?:scope|resume|restart|window)\./.test(entry.customType)){
          latest[entry.customType]={id:entry.id,data:entry.data};
        }
      }
      evidence.event('memory_projection_boundary',{boundary_id:prepared?.boundary_id??null,
        metadata_ref:evidence.put(latest)});
    }
    (globalThis as any)[boundaryKey]={...prepared,prepared_messages_sha256:hash(payload?.messages??[]),
      prepared_messages:(payload?.messages??[]).map((m:any)=>({role:m.role,sha256:hash(m),
        tool_call_id:m.tool_call_id??null,tool_calls:(m.tool_calls??[]).map((t:any)=>t.id)}))};
  });
}
