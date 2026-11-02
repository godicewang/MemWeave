// Targeted read-only source evidence at a requested reference, not another Session store.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash}from'node:crypto';
import {contentEvidence}from'./content_evidence.mjs';
import {captureCommittedState}from'./request_boundary.ts';

export function captureReferenceSources(ctx:any,input:any,options:any={}){
  const evidence=contentEvidence(),branch=ctx?.sessionManager?.getBranch?.();
  if(!Array.isArray(branch)||!Array.isArray(input?.items))return {complete:false,reason:'reference context or arguments missing',items:[]};
  const current=options.taskId??captureCommittedState(ctx).task_id;
  const entries=ctx.sessionManager.getEntries?.()??branch;
  const session=ctx.sessionManager.getSessionId?.();
  const snapshots=(type:string,task:string)=>branch.filter((e:any)=>e.type==='custom'&&e.customType===type&&e.data?.task_id===task).flatMap((e:any)=>(e.data.bindings??[]).map((b:any)=>({...b,source_session_id:b.source_session_id??e.data.source_session_id})));
  const items=input.items.map((request:any)=>{
    const record:any={requested_ref:request.ref,offset:request.offset??0,limit:request.limit??null};
    try{
      let task=request.task_id??current,ref=request.ref;
      if(typeof ref!=='string')throw Error('invalid_reference');
      if(ref.startsWith('R')){
        const alias=snapshots('memweave.aliases.v1',current).filter((a:any)=>a.ref===ref).at(-1);
        if(!alias||alias.part_index!==undefined)throw Error('image_or_unresolved_alias');
        task=alias.source_task_id;ref=alias.source_ref;
      }
      const location=snapshots('memweave.references.v1',task).filter((r:any)=>r.ref===ref).at(-1);
      const original=snapshots('memweave.originals.v1',task).filter((r:any)=>r.ref===ref).at(-1);
      let body:string|undefined,source:any;
      if(original&&/^[a-f0-9]{64}$/.test(original.blob_hash)){
        const raw=fs.readFileSync(path.join(options.memoryRoot??path.join(os.homedir(),'.pi','memory'),'blobs',original.blob_hash));
        if(createHash('sha256').update(raw).digest('hex')!==original.blob_hash)throw Error('original_blob_hash_mismatch');
        body=raw.toString('utf8');source=original;
      }else if(location&&location.source_session_id===session){
        const entry=entries.find((e:any)=>e.id===location.entry_id);
        const content=entry?.message?.content;
        if(typeof content==='string')body=content;
        else if(Array.isArray(content)&&content.every((p:any)=>p.type==='text'&&typeof p.text==='string'))body=content.map((p:any)=>p.text).join('\n');
        source=location;
      }
      // U/A plain text is normalized independently. Tool calls/results have
      // additional projection rules and remain explicitly unsupported here.
      if(!/^[UA][1-9][0-9]*$/.test(ref)||body===undefined||!source)throw Error('source_projection_not_supported');
      body=body.replace(/\r\n?/g,'\n');
      return {...record,status:'CAPTURED_KNOWN_TEXT',source_task_id:task,source_ref:ref,
        source_session_id:source.source_session_id,entry_id:source.entry_id,
        source_ref_cas:evidence?.put(body)??null,total_chars:Array.from(body).length};
    }catch(error){return {...record,status:'UNKNOWN_SOURCE',reason:error instanceof Error?error.message:'source_error'};}
  });
  return {version:'fixed35-known-text-source-v1',complete:items.length>0&&items.every((i:any)=>i.status==='CAPTURED_KNOWN_TEXT'),
    current_task_id:current,max_total_chars:input.max_total_chars??null,items};
}
