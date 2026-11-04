// Uploaded only to free preflight containers. Never loaded by a paid Actor.
import fs from 'node:fs';
export default function fixture(pi:any){
  pi.on('before_provider_request',()=>{
    globalThis.fetch=async()=>{fs.appendFileSync('/logs/agent/unguarded-dispatch.jsonl','{}\n');throw Error('Guardless fixture dispatch');};
  });
}
