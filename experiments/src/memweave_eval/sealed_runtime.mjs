import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {syncBuiltinESMExports} from 'node:module';
import {pathToFileURL} from 'node:url';

export function disableZstd() {
  for(const key of Object.keys(zlib).filter(k=>/zstd/i.test(k)&&typeof zlib[k]==='function')) {
    Object.defineProperty(zlib,key,{value(){throw Error('Codec unavailable in sealed evaluation runtime');},writable:false,configurable:false});
  }
  syncBuiltinESMExports();
}

export function sealSource(root) {
  const removed=[],sources=[];
  function visit(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
    const file=path.join(dir,entry.name);
    if(entry.isSymbolicLink()) {
      if(fs.readlinkSync(file).includes('memweave-eval')){fs.unlinkSync(file);removed.push(path.relative(root,file));}
    } else if(entry.isDirectory())visit(file);
    else if(entry.isFile()) {
      const bytes=fs.readFileSync(file);
      const node=bytes.subarray(0,4).equals(Buffer.from([127,69,76,70]))&&bytes.includes(Buffer.from('node:internal/'));
      if(node){fs.unlinkSync(file);removed.push(path.relative(root,file));}
      else if(/\.(?:c|h|inc)$/.test(file)||entry.name==='Makefile')sources.push(path.relative(root,file));
    }
  }}
  visit(root);
  return {removed_control_runtimes:removed,preserved_source_files:sources,source_bytes_modified:false,
    verifier_boundary:'fresh official image; no Pi/Node/evaluation assets transferred'};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  const result=sealSource(process.argv[2]);fs.writeFileSync(process.argv[3],JSON.stringify(result,null,2)+'\n');
}
