import json
import os
import subprocess
from pathlib import Path


def test_independent_native_identity_ledger_does_not_copy_chat_content(tmp_path):
    module=Path(__file__).parents[1]/'src/memweave_eval/request_boundary.ts'
    script='''import {attachBoundaries,boundaryKey} from MODULE;
const hooks=new Map();attachBoundaries({on:(k,fn)=>hooks.set(k,fn)});
const message={role:'user',content:'Native important evidence',timestamp:1};
const branch=[{type:'message',id:'u',parentId:null,message},
 {type:'custom',id:'w',customType:'memweave.window.v1',data:{boundary_entry_id:null,pending:[]}}];
const ctx={sessionManager:{getBranch:()=>branch,getSessionId:()=> 'session'}};
hooks.get('context_with_system')({messages:[message]},ctx);
hooks.get('before_provider_request')({payload:{messages:[]}},ctx);
console.log(JSON.stringify(globalThis[boundaryKey]));
'''.replace('MODULE',json.dumps(str(module)))
    value=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],
        env=dict(os.environ,MEMWEAVE_EVAL_CONTENT_STORE=str(tmp_path/'store')),check=True,capture_output=True,text=True)
    result=json.loads(value.stdout)
    assert result['source_messages'][0]['entry_id']=='u'
    assert result['native_shape']['session_id']=='session'
    assert result['native_shape']['messages'][0]['id']=='u'
    assert result['native_shape']['previous_window']=={'boundary_entry_id':None,'pending':[]}
    assert 'Native important evidence'not in json.dumps(result['native_shape'])
