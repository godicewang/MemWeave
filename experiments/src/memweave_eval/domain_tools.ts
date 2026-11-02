// Derived STATE/Pi interface. Only public tool schemas and one scoped endpoint.
import fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
export default function domainTools(pi:any){
  const descriptor=JSON.parse(fs.readFileSync(process.env.MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR!,'utf8'));
  if(!Array.isArray(descriptor.tools)||!descriptor.exchange||!descriptor.token)throw Error('Domain channel missing');
  pi.on('before_agent_start',(event:any)=>({systemPrompt:event.systemPrompt+'\n\n'+descriptor.system_prompt}));
  for(const tool of descriptor.tools){
    pi.registerTool({name:tool.name,label:tool.name,description:tool.description,parameters:tool.parameters,
      async execute(callId:string,input:any,signal:AbortSignal){
        const name=createHash('sha256').update(callId).digest('hex')+'.json';
        const target=path.join(descriptor.exchange,'requests',name),temporary=target+'.'+randomUUID()+'.partial';
        const fd=fs.openSync(temporary,'wx',0o600);
        try{fs.writeFileSync(fd,JSON.stringify({call_id:callId,name:tool.name,arguments:input,token:descriptor.token}));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
        fs.renameSync(temporary,target);
        const response=path.join(descriptor.exchange,'responses',name),until=Date.now()+60000;
        while(!fs.existsSync(response)){
          if(signal?.aborted||Date.now()>=until)throw Error('Domain IPC interrupted or timed out');
          await new Promise(resolve=>setTimeout(resolve,10));
        }
        const receipt=JSON.parse(fs.readFileSync(response,'utf8'));
        if(receipt.bridge_error)throw Error(receipt.bridge_error);
        const value=receipt.result;
        return {content:[{type:'text',text:JSON.stringify(value)}],details:{domain_result:value}};
      }});
  }
}
