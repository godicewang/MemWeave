// Evaluation-only Node backend. Caller holds the same flock as the Python host.
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';

export function change(input,operation,now=Date.now()/1000) {
  const ledger=structuredClone(input), requests=ledger.requests;
  const id=operation.id;
  if(typeof id!=='string'||!id||id.length>200)throw Error('Invalid request ID');
  const sum=values=>values.reduce((n,v)=>n+v.charge_usd,0);
  if(operation.action==='reserve') {
    const output=operation.max_output;
    if(!Number.isInteger(output)||output<1||output>384000)throw Error('Unbounded output');
    if(requests[id]||now>=ledger.deadline)throw Error('Duplicate request or deadline');
    const reserve=1048576*.3/1e6+output*1.2/1e6, all=Object.values(requests);
    if(sum(all)+reserve>ledger.maximum_usd)throw Error('Global budget');
    const arm=operation.arm, episode=operation.episode;
    const own=all.filter(v=>v.arm===arm), current=own.filter(v=>v.episode===episode);
    if(operation.episode_budget!=null && (!(operation.episode_budget>0)||sum(current)+reserve>operation.episode_budget))throw Error('Episode budget');
    if(operation.max_requests!=null && (!Number.isInteger(operation.max_requests)||operation.max_requests<1||current.length>=operation.max_requests))throw Error('Request limit');
    if(Object.keys(ledger.arm_limits??{}).length && (!(arm in ledger.arm_limits)||sum(own)+reserve>ledger.arm_limits[arm]))throw Error('Arm budget');
    requests[id]={status:'reserved',max_output:output,charge_usd:reserve,admitted_at:now,arm,episode};
  } else if(operation.action==='settle') {
    const record=requests[id], i=operation.input,o=operation.output,c=operation.cache_input??0;
    if(!record||![i,o,c].every(Number.isInteger)||i<0||i>1048576||o<0||o>record.max_output||c<0||c>i)throw Error('Usage outside reservation');
    if(record.status==='settled') {
      if(record.input!==i||record.output!==o||(record.cache_input??0)!==c)throw Error('Conflicting usage');
    } else Object.assign(record,{status:'settled',input:i,output:o,cache_input:c,
      charge_usd:(i-c)*.3/1e6+c*.006/1e6+o*1.2/1e6,settled_at:now});
  } else throw Error('Unknown action');
  ledger.exposure_usd=sum(Object.values(requests));
  return {ledger,record:requests[id]};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  try {
    if(process.argv[3]!=='--lock-held')throw Error('flock required');
    const target=process.argv[2], directory=path.dirname(target),temporary=path.join(directory,'.quota-'+randomUUID());
    const operation=JSON.parse(fs.readFileSync(0,'utf8')),owner=path.join(directory,'WRITER_PLATFORM');
    if(fs.existsSync(owner)&&fs.readFileSync(owner,'utf8').trim()!==process.platform)throw Error('Writer platform mismatch');
    if(operation.action==='reserve'&&fs.existsSync(path.join(directory,'STOP_REQUESTED')))throw Error('Durable stop');
    const result=change(JSON.parse(fs.readFileSync(target,'utf8')),operation);
    const fd=fs.openSync(temporary,'wx',0o600);
    try{fs.writeFileSync(fd,JSON.stringify(result.ledger));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    fs.renameSync(temporary,target);
    const dir=fs.openSync(path.dirname(target),'r');try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}
    process.stdout.write(JSON.stringify(result.record));
  }catch {process.stderr.write('QuotaRejected\n');process.exitCode=2;}
}
