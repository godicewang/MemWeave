import json
import os
import shutil
import subprocess
from pathlib import Path

from memweave_eval.contract_metrics import provider_projection_integrity, state_freshness
from memweave_eval.finance_metrics import attach_finance, transport_finance

NODE=os.environ.get('MEMWEAVE_EVAL_TEST_NODE')or shutil.which('node')or'node'
SRC=Path(__file__).parents[1]/'src/memweave_eval'


def test_strict_preparation_boundary_is_distinct_from_lower_bound():
    req={'request_id':'r','expected_task_id':'T','expected_version_at_prepare':3,
         'boundary_source':'atomic_journal_before_context_transform','state_blocks':[{'task_id':'T','version':3}]}
    assert state_freshness([], [req])['value']==1
    assert state_freshness([], [dict(req,state_blocks=[{'task_id':'T','version':2}])])['value']==0
    assert state_freshness([], [dict(req,state_blocks=[{'task_id':'T','version':4}])])['status']=='unknown'
    assert state_freshness([], [dict(req,expected_version_at_prepare=None)])['status']=='unknown'


def test_final_projection_compares_actual_pairs_and_keeps_unknown():
    msgs=[{'role':'assistant','sha256':'a','tool_call_id':None,'tool_calls':['c']},
          {'role':'tool','sha256':'b','tool_call_id':'c','tool_calls':[]}]
    req={'request_id':'r','messages':msgs,'prepared_messages':msgs}
    assert provider_projection_integrity([req])['value']==1
    assert provider_projection_integrity([dict(req,messages=msgs[::-1])])['value']==0
    assert provider_projection_integrity([dict(req,messages=msgs[:1],prepared_messages=msgs[:1])])['value']==0
    assert provider_projection_integrity([{}])['status']=='unknown'


def test_raw_cache_field_missing_and_explicit_zero(tmp_path):
    path=tmp_path/'request-trace.jsonl'
    def write(cache):
        events=[{'event':'http_attempt','request_id':'x'},
                {'event':'request_end','request_id':'x','usage':{'input':100,'output':10,'cache_hit':cache},'settled':True},
                {'event':'budget_settled','request_id':'x','charge_usd':.1}]
        path.write_text('\n'.join(map(json.dumps,events)))
    write(None);assert transport_finance(tmp_path)['cache_metrics']['input_cache_utilization']['status']=='unknown'
    write(0);assert transport_finance(tmp_path)['cache_metrics']['input_cache_utilization']['value']==0
    row={'usage':{'input_tokens':100,'cache_tokens':0,'output_tokens':10,'cost_usd':.1}}
    attach_finance(row,{})
    assert row['cache_status']=='unknown'


def test_node_budget_policy_is_atomic_backend_equivalent(tmp_path):
    script='''import {change} from MODULE;
let a={schema_version:1,maximum_usd:1,deadline:2000,requests:{},arm_limits:{'z:n':.4,'c:n':.4}};
a=change(a,{action:'reserve',id:'a',arm:'z:n',max_output:1000},1000).ledger;
try{change(a,{action:'reserve',id:'b',arm:'z:n',max_output:1000},1000);throw Error('not rejected');}catch(e){if(e.message==='not rejected')throw e;}
a=change(a,{action:'reserve',id:'c',arm:'c:n',max_output:1000},1000).ledger;
a=change(a,{action:'settle',id:'a',input:100,output:1,cache_input:90},1001).ledger;
if(Object.keys(a.requests).length!==2||a.requests.a.status!=='settled'||a.requests.c.status!=='reserved')throw Error('wrong ledger');
'''.replace('MODULE',json.dumps(str((SRC/'budget_guard.mjs').resolve())))
    result=subprocess.run([NODE,'--input-type=module','-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_sealed_handoff_removes_renamed_elf_node_without_editing_source(tmp_path):
    (tmp_path/'keep.c').write_text('int main(){return 0;}')
    (tmp_path/'renamed').write_bytes(bytes([127,69,76,70])+b'patched-node:internal/marker')
    (tmp_path/'link').symlink_to('/root/.local/share/memweave-eval/node/bin/node')
    script='''import {sealSource,disableZstd} from MODULE;import zlib from 'node:zlib';
disableZstd();for(const key of Object.keys(zlib).filter(k=>/zstd/i.test(k)&&typeof zlib[k]==='function')){
try{zlib[key]();throw Error('not disabled');}catch(e){if(e.message==='not disabled')throw e;}}
console.log(JSON.stringify(sealSource(ROOT)));'''.replace('MODULE',json.dumps(str((SRC/'sealed_runtime.mjs').resolve()))).replace('ROOT',json.dumps(str(tmp_path)))
    result=subprocess.run([NODE,'--input-type=module','-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'keep.c').read_text()=='int main(){return 0;}'
    assert not (tmp_path/'renamed').exists()and not(tmp_path/'link').exists()


def test_registered_reference_defect_cannot_mask_another_failure(tmp_path):
    from memweave_eval.runner import control_ok
    trial=tmp_path/'compiler__x';(trial/'verifier').mkdir(parents=True)
    (trial/'result.json').write_text(json.dumps({'task_name':'abundant/compiler','exception_info':None,'verifier_result':{'rewards':{'reward':0}}}))
    (trial/'verifier/metrics.json').write_text(json.dumps({'new_passed':893,'new_total':894}))
    expected={'reward':0,'metrics':{'new_passed':893,'new_total':894},'stdout_fail_lines':['FAIL (rc): known']}
    (trial/'verifier/test-stdout.txt').write_text('FAIL (rc): known\n')
    assert control_ok(tmp_path,'compiler',expected)
    (trial/'verifier/test-stdout.txt').write_text('FAIL (rc): different\n')
    assert not control_ok(tmp_path,'compiler',expected)
