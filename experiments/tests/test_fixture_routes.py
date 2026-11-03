import json
import subprocess
from pathlib import Path


def test_fixture_task_ids_and_evidence_must_come_from_observed_actual_results():
    module=Path(__file__).parents[1]/'src/memweave_eval/fixture_transport.ts'
    script='''import {resolveFixtureArguments,fixtureContentText} from MODULE;
for(const v of ['[task_source:U4]\\nsource',[{type:'text',text:'[task_source:U4]\\nsource'}]]){
 if(fixtureContentText(v)!=='[task_source:U4]\\nsource')throw Error('provider content shape lost');
}
const ids=new Map([['source-objective','task_observed']]);
const value=resolveFixtureArguments({task_id:{$task_route:'source-objective'},
 evidence:{'$latest_user_ref':'real source snippet'}},ids,'task_source:U4');
if(value.task_id!=='task_observed'||value.evidence['task_source:U4']!=='real source snippet')throw Error('bad resolution');
const read=resolveFixtureArguments({items:[{$latest_user_origin:true}],evidence:{$latest_read_ref:'read source'}},ids,'task_source:U4','R7');
if(read.items[0].ref!=='U4'||read.items[0].task_id!=='task_source'||read.evidence.R7!=='read source')throw Error('cross-task alias resolution');
let missingAlias=false;try{resolveFixtureArguments({evidence:{$latest_read_ref:'source'}},ids,'U1')}catch{missingAlias=true}
if(!missingAlias)throw Error('read alias may not be guessed');
for(const input of [{task_id:{$task_route:'unknown'}},{evidence:{'$latest_user_ref':'source'}}]){
 let failed=false;try{resolveFixtureArguments(input,new Map(),null)}catch{failed=true}
 if(!failed)throw Error('missing observed identity must fail');
}
console.log('ok');
'''.replace('MODULE',json.dumps(str(module)))
    result=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],
        check=True,capture_output=True,text=True,timeout=15)
    assert result.stdout.strip()=='ok'
