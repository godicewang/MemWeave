// Opt-in evaluation evidence, never a runtime memory or actor input source.
import fs from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {gzipSync,gunzipSync} from 'node:zlib';

const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const key=Symbol.for('memweave.eval.contentEvidence');

export function contentEvidence(root=process.env.MEMWEAVE_EVAL_CONTENT_STORE) {
  if(!root)return null;
  if(!path.isAbsolute(root))throw Error('Evidence root must be absolute');
  const stores=globalThis[key]??=new Map();
  if(stores.has(root))return stores.get(root);
  fs.mkdirSync(path.join(root,'objects'),{recursive:true,mode:0o700});
  const producer=randomUUID();let sequence=0,previous=null;
  const journal=path.join(root,'producer-'+producer+'.jsonl');
  const mirror=path.join(root,'producer-'+producer+'.mirror.jsonl');
  const put=(value)=>{
    const bytes=Buffer.isBuffer(value)?value:Buffer.from(typeof value==='string'?value:JSON.stringify(value));
    const digest=sha(bytes),target=path.join(root,'objects',digest+'.gz');
    if(fs.existsSync(target)) {
      if(sha(gunzipSync(fs.readFileSync(target)))!==digest)throw Error('Corrupt existing evidence object');
    } else {
      const temporary=target+'.'+randomUUID()+'.partial',fd=fs.openSync(temporary,'wx',0o600);
      try{fs.writeFileSync(fd,gzipSync(bytes));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
      fs.renameSync(temporary,target);
      const directory=fs.openSync(path.dirname(target),'r');
      try{fs.fsyncSync(directory);}finally{fs.closeSync(directory);}
    }
    return {sha256:digest,bytes:bytes.length,object:'objects/'+digest+'.gz',encoding:'gzip'};
  };
  const event=(kind,data)=>{
    const body={schema_version:1,producer_id:producer,sequence:++sequence,previous_sha256:previous,
      run_id:process.env.MEMWEAVE_EVAL_RUN_ID??null,case_id:process.env.MEMWEAVE_EVAL_CASE_ID??null,
      stage_id:process.env.MEMWEAVE_EVAL_STAGE_ID??null,
      execution_invocation_id:process.env.MEMWEAVE_EVAL_INVOCATION_ID??null,
      arm:process.env.MEMWEAVE_EVAL_BUDGET_ARM??process.env.MEMWEAVE_EVAL_VARIANT??null,
      role:process.env.MEMWEAVE_EVAL_ROLE??'actor',event:kind,
      timestamp:new Date().toISOString(),monotonic_ns:process.hrtime.bigint().toString(),...data};
    const digest=sha(JSON.stringify(body));
    const line=JSON.stringify({...body,event_sha256:digest})+'\n';
    for(const target of [journal,mirror]) {
      const fd=fs.openSync(target,'a',0o600);
      try{fs.writeFileSync(fd,line);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    }
    previous=digest;return {producer_id:producer,sequence,event_sha256:digest};
  };
  const store={put,event,root};stores.set(root,store);return store;
}
