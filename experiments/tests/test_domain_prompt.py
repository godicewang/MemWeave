import json
import os
import subprocess
from pathlib import Path


def test_domain_prompt_uses_public_structured_append_without_forcing_full_system(tmp_path):
    descriptor=tmp_path/'domain.json'
    descriptor.write_text(json.dumps({'tools':[],'exchange':'/fixture','token':'fixture-only',
        'system_prompt':'Original domain rules'}))
    module=Path(__file__).parents[1]/'src/memweave_eval/domain_tools.ts'
    script='''import domain from MODULE;
const hooks=new Map();domain({on:(event,fn)=>hooks.set(event,fn),registerTool:()=>{}});
const options={appendSystemPrompt:'Existing user append',sections:{other:'preserved'}};
const result=hooks.get('before_agent_start')({systemPrompt:'native full prompt',systemPromptOptions:options});
console.log(JSON.stringify({result:result??null,options}));
'''.replace('MODULE',json.dumps(str(module)))
    result=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],
        env=dict(os.environ,MEMWEAVE_EVAL_DOMAIN_DESCRIPTOR=str(descriptor)),capture_output=True,text=True,
        timeout=10,check=True)
    value=json.loads(result.stdout)
    assert value['result'] is None
    assert value['options']=={'appendSystemPrompt':'Existing user append\n\nOriginal domain rules',
        'sections':{'other':'preserved'}}
