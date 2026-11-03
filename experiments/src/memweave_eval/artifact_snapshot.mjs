// Explicit evaluator-only output files; content never enters model context.
import fs from 'node:fs';
import path from 'node:path';
import {createHash}from'node:crypto';

export function artifactSnapshot(root,definitions,put){
  const results={},base=path.resolve(root);
  for(const [name,limit]of Object.entries(definitions)){
    let fd;
    try{
      const file=path.resolve(base,name);
      if(!Number.isInteger(limit)||limit<1||limit>1048576||file===base||!file.startsWith(base+path.sep))throw Error('invalid artifact definition');
      const relative=path.relative(base,file).split(path.sep);let current=base;
      for(const part of relative){current=path.join(current,part);if(fs.lstatSync(current).isSymbolicLink())throw Error('redirected artifact');}
      fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
      const before=fs.fstatSync(fd);
      if(!before.isFile()||before.size>limit)throw Error('artifact size or type unsupported');
      const bytes=Buffer.alloc(before.size),count=fs.readSync(fd,bytes,0,bytes.length,0),after=fs.fstatSync(fd);
      if(count!==before.size||before.size!==after.size||before.mtimeMs!==after.mtimeMs)throw Error('artifact changed during capture');
      const ref=put(bytes);if(!ref)throw Error('artifact evidence store unavailable');
      results[name]={status:'captured',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),ref};
    }catch(error){results[name]={status:error?.code==='ENOENT'?'absent':'incomplete',reason:error?.code??error.message};}
    finally{if(fd!==undefined)fs.closeSync(fd);}
  }
  return results;
}
