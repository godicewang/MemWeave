import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {syncBuiltinESMExports} from 'node:module';
import {createHash}from'node:crypto';
import {pathToFileURL} from 'node:url';

export function disableZstd() {
  for(const key of Object.keys(zlib).filter(k=>/zstd/i.test(k)&&typeof zlib[k]==='function')) {
    Object.defineProperty(zlib,key,{value(){throw Error('Codec unavailable in sealed evaluation runtime');},writable:false,configurable:false});
  }
  syncBuiltinESMExports();
}

export function sealSource(root) {
  const removed=[],sources=[],unsupported=[],inputFiles={},handoffFiles={};
  const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
  root=path.resolve(root);
  function visit(dir){for(const entry of fs.readdirSync(dir,{withFileTypes:true})){
    const file=path.join(dir,entry.name);
    if(entry.isSymbolicLink()) {
      const relative=path.relative(root,file),target=fs.readlinkSync(file);
      inputFiles[relative]={type:'symlink',target};
      if(target.includes('memweave-eval')){fs.unlinkSync(file);removed.push(relative);}
      else {
        try {
          const resolved=fs.realpathSync(file);
          if(resolved!==root && !resolved.startsWith(root+path.sep))throw Error('outside source tree');
          handoffFiles[relative]={type:'symlink',target,resolved_relative:path.relative(root,resolved),sha256:digest(fs.readFileSync(resolved))};
        } catch {unsupported.push({path:relative,reason:'external_or_unresolved_symbolic_input'});}
      }
    } else if(entry.isDirectory())visit(file);
    else if(entry.isFile()) {
      const bytes=fs.readFileSync(file);
      const relative=path.relative(root,file);
      inputFiles[relative]={type:'file',sha256:digest(bytes),bytes:bytes.length};
      const node=bytes.subarray(0,4).equals(Buffer.from([127,69,76,70]))&&bytes.includes(Buffer.from('node:internal/'));
      if(node){fs.unlinkSync(file);removed.push(path.relative(root,file));}
      else {sources.push(relative);handoffFiles[relative]=inputFiles[relative];}
    }
  }}
  visit(root);
  return {removed_control_runtimes:removed,preserved_source_files:sources,source_bytes_modified:false,
    input_files:inputFiles,handoff_files:handoffFiles,unsupported_inputs:unsupported,
    status:unsupported.length?'adapter_unsupported_input':'ready',
    verifier_boundary:'fresh official image; no Pi/Node/evaluation assets transferred'};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  const result=sealSource(process.argv[2]);fs.writeFileSync(process.argv[3],JSON.stringify(result,null,2)+'\n');
  if(result.unsupported_inputs.length)process.exitCode=2;
}
