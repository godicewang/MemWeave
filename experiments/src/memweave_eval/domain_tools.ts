// Derived STATE/Pi interface. Only public tool schemas and one scoped endpoint.
import fs from 'node:fs';
export default function domainTools(pi:any){
  const descriptor=JSON.parse(fs.readFileSync(process.env.MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR!,'utf8'));
  if(!Array.isArray(descriptor.tools)||!descriptor.endpoint||!descriptor.token)throw Error('Domain endpoint missing');
  pi.on('before_agent_start',(event:any)=>({systemPrompt:event.systemPrompt+'\n\n'+descriptor.system_prompt}));
  for(const tool of descriptor.tools){
    pi.registerTool({name:tool.name,label:tool.name,description:tool.description,parameters:tool.parameters,
      async execute(callId:string,input:any,signal:AbortSignal){
        const response=await fetch(descriptor.endpoint,{method:'POST',signal,
          headers:{'content-type':'application/json','authorization':'Bearer '+descriptor.token},
          body:JSON.stringify({call_id:callId,name:tool.name,arguments:input})});
        if(!response.ok)throw Error('Domain backend HTTP '+response.status);
        const value=await response.json();
        return {content:[{type:'text',text:JSON.stringify(value)}],details:{domain_result:value}};
      }});
  }
}
