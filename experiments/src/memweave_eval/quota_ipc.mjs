// No ledger access and no flock: the single VM authority applies every operation.
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
const channel=process.argv[2];
try{
  const config=JSON.parse(fs.readFileSync(path.join(channel,'client.json'),'utf8'));
  const ready=JSON.parse(fs.readFileSync(path.join(channel,'ready.json'),'utf8'));
  if(ready.service_id!==config.service_id||ready.channel_id!==config.channel_id)throw Error('quota_service_identity_mismatch');
  const operation=JSON.parse(fs.readFileSync(0,'utf8')),nonce=randomUUID();
  const filename=nonce+'.json',target=path.join(channel,'requests',filename),temporary=target+'.partial';
  const fd=fs.openSync(temporary,'wx',0o600);
  try{fs.writeFileSync(fd,JSON.stringify({nonce,token:config.token,operation}));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  fs.renameSync(temporary,target);
  const response=path.join(channel,'responses',filename),stop=Date.now()+10000;
  while(!fs.existsSync(response)&&Date.now()<stop)Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,10);
  if(!fs.existsSync(response))throw Error('quota_service_response_timeout');
  const result=JSON.parse(fs.readFileSync(response,'utf8'));
  if(result.nonce!==nonce||result.service_id!==config.service_id)throw Error('quota_response_identity_mismatch');
  if(!result.ok){process.stderr.write(JSON.stringify({error_class:result.error_class,reason:result.reason}));process.exitCode=2;}
  else process.stdout.write(JSON.stringify(result.record));
}catch(error){
  process.stderr.write(JSON.stringify({error_class:error?.code??error?.name??'Error',reason:'quota_IPC_unavailable_or_invalid'}));process.exitCode=2;
}
