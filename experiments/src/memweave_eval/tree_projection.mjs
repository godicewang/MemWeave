// Bounded read-only projections. No directory body is copied into evaluation logs.
import fs from'node:fs';
import path from'node:path';
import {createHash}from'node:crypto';
const digest=value=>createHash('sha256').update(value).digest('hex');
export function treeProjection(root,{selectors={names:[],segments:[],suffixes:[]},
  maxFiles=20000,maxBytes=512*1024*1024,excludeSegments=['target','.git','.cargo']}={}){
  const entries=[];let bytes=0;
  try{
    if(!path.isAbsolute(root)||!Number.isSafeInteger(maxFiles)||maxFiles<1||!Number.isSafeInteger(maxBytes)||maxBytes<1)
      throw Error('invalid_projection_bounds');
    for(const key of['names','segments','suffixes'])
      if(!Array.isArray(selectors[key])||selectors[key].some(x=>typeof x!=='string'||!x||x.includes('/')||x.includes('\\')))
        throw Error('invalid_projection_selectors');
    const all=Object.values(selectors).every(values=>values.length===0);
    const selected=relative=>all||selectors.names.includes(path.basename(relative))||
      relative.split('/').some(segment=>selectors.segments.includes(segment))||selectors.suffixes.some(s=>relative.endsWith(s));
    function visit(filename,relative){
      const stat=fs.lstatSync(filename);
      if(stat.isDirectory()){
        for(const name of fs.readdirSync(filename).sort()){
          if(excludeSegments.includes(name))continue;
          visit(path.join(filename,name),relative==='.'?name:relative+'/'+name);
        }
      }else if(selected(relative)){
        if(entries.length>=maxFiles)throw Error('projection_file_limit');
        const value={path:relative,kind:stat.isSymbolicLink()?'symlink':stat.isFile()?'file':'unsupported',mode:stat.mode&0o777};
        if(value.kind==='symlink')value.target_sha256=digest(fs.readlinkSync(filename));
        else if(value.kind==='file'){
          bytes+=stat.size;if(bytes>maxBytes)throw Error('projection_byte_limit');
          const h=createHash('sha256'),buffer=Buffer.alloc(1024*1024),fd=fs.openSync(filename,'r');
          try{let n;while((n=fs.readSync(fd,buffer,0,buffer.length,null))>0)h.update(buffer.subarray(0,n));}
          finally{fs.closeSync(fd);}
          value.content_sha256=h.digest('hex');value.bytes=stat.size;
        }else throw Error('unsupported_projection_node');
        entries.push(value);
      }
    }
    try{fs.lstatSync(root);}catch(error){if(error.code==='ENOENT')return {status:'absent',complete:true,entries:[],file_count:0,bytes:0,projection_sha256:digest('[]')};throw error;}
    visit(root,'.');entries.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
    return {status:'complete',complete:true,entries,file_count:entries.length,bytes,
      projection_sha256:digest(JSON.stringify(entries))};
  }catch(error){return {status:'incomplete',complete:false,reason:error.code??error.message,
    file_count:entries.length,bytes,projection_sha256:null};}
}
