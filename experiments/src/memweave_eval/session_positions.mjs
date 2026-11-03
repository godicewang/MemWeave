// Read-only Harbor continuation usage offsets, using the already pinned Node.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL}from'node:url';
export function sessionPositions(root){
  if(!fs.lstatSync(root).isDirectory())throw Error('Native Session directory is not a real directory');
  const positions={},buffer=Buffer.alloc(65536);
  for(const entry of fs.readdirSync(root,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
    if(!entry.isFile()||!entry.name.endsWith('.jsonl'))continue;
    const fd=fs.openSync(path.join(root,entry.name),'r');let count=0;
    try{let length;while((length=fs.readSync(fd,buffer,0,buffer.length,null))>0){
      for(let i=0;i<length;i++)if(buffer[i]===10)count++;
    }}finally{fs.closeSync(fd);}
    positions[entry.name]=count;
  }
  return positions;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)
  process.stdout.write(JSON.stringify(sessionPositions(process.argv[2])));
