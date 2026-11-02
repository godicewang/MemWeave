import json
import subprocess
from pathlib import Path


def test_actual_public_pi_tool_event_collector_keeps_arguments_results_and_opt_out(tmp_path):
    root=Path(__file__).parents[1]/'src/memweave_eval'
    script="""
import observe from OBSERVER;
import fs from 'node:fs';
process.env.MEMWEAVE_EVAL_TRACE=ROOT+'/trace.jsonl';
process.env.MEMWEAVE_EVAL_CONTENT_STORE=ROOT+'/contents';
process.env.MEMWEAVE_EVAL_PROGRESS_AFTER='0';
const handlers=new Map();let sent=0;
const pi={on:(name,f)=>{const list=handlers.get(name)??[];list.push(f);handlers.set(name,list);},sendUserMessage:()=>sent++};
observe(pi);
for(const kind of ['tool_call','tool_execution_start','tool_execution_end','tool_result']){
 const event={type:kind,toolCallId:'t',toolName:'state_append',input:{facts:['scope A: 5 ms']},
 args:{facts:['scope A: 5 ms']},result:{content:[{type:'text',text:'state_version: 3'}]},isError:false};
 for(const handler of handlers.get(kind)??[])handler(event);
}
for(let i=0;i<100;i++)for(const f of handlers.get('message_end'))f({message:{role:'assistant',usage:{}}});
if(sent!==0)throw Error('disabled legacy detour leaked');
""".replace('OBSERVER',json.dumps((root/'checkpoint_observer.ts').as_uri())).replace('ROOT',json.dumps(str(tmp_path)))
    result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,timeout=10,check=False)
    assert result.returncode==0,result.stderr
    from memweave_eval.evidence_replay import read_object, replay_content
    data=replay_content(tmp_path/'contents')
    events=[e for e in data['events']if e['event'].startswith('tool_')]
    assert len(events)==4
    originals=[json.loads(read_object(tmp_path/'contents',e['record_ref']))for e in events]
    assert originals[0]['input']['facts']==['scope A: 5 ms']
    assert originals[2]['result']['content'][0]['text']=='state_version: 3'
    snapshots=[e for e in data['events']if e['event']=='state_after_tool']
    assert snapshots[0]['state']['status']=='SESSION_CONTEXT_UNAVAILABLE'
