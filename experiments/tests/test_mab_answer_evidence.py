import hashlib
import json

from memweave_eval.fixed35_mab import grade_mab_trial


def setup(root):
    agent=root/'steps/query/agent';(agent/'fixed35-artifacts').mkdir(parents=True)
    (agent/'fixed35-artifacts/answer-presence.json').write_text('{"exists":true}')
    (agent/'fixed35-artifacts/answer.json').write_text('{"value":"B"}')
    return agent,{'answers':['B'],'query_stage_id':'2'}


def test_missing_final_answer_or_query_directory_is_unknown_without_failure_proof(tmp_path):
    agent,contract=setup(tmp_path)
    result=grade_mab_trial(tmp_path,contract,arm='pi-native')
    assert result['native']['native_outcome']is None and result['derived_action']['score']is None
    result=grade_mab_trial(tmp_path/'absent',contract,arm='pi-native')
    assert result['native']['native_outcome']is None
    (agent/'pi.txt').write_text('not JSON\n'+json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'B'}]}}))
    assert grade_mab_trial(tmp_path,contract,arm='pi-native')['native']['native_outcome']is None


def test_original_invocation_stdout_repairs_missing_derived_pi_log(tmp_path):
    agent,contract=setup(tmp_path);folder=agent/'execution-invocations';folder.mkdir()
    raw=(json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'B'}]}})+'\n'+json.dumps({'type':'agent_end'})+'\n').encode()
    (folder/'call.stdout.jsonl').write_bytes(raw)
    manifest={'schema_version':1,'invocation_id':'call','stage_id':'2','capture_status':'CAPTURED','status':'RETURNED',
        'stdout_file':'call.stdout.jsonl','stdout_sha256':hashlib.sha256(raw).hexdigest(),'stdout_bytes':len(raw),
        'started_monotonic_ns':'1','return_code':0}
    (folder/'call.json').write_text(json.dumps(manifest))
    result=grade_mab_trial(tmp_path,contract,arm='pi-native')
    assert result['native']['native_outcome']==100 and result['derived_action']['score']==100
    assert result['answer_evidence']['source']=='independent_native_invocation'
    (agent/'pi.txt').write_text(raw.decode().replace('"B"','"A"'))
    assert grade_mab_trial(tmp_path,contract,arm='pi-native')['native']['native_outcome']is None,'conflicting derived log cannot select the winning answer'
    (agent/'pi.txt').unlink()
    (folder/'call.stdout.jsonl').write_bytes(raw+b'damage')
    assert grade_mab_trial(tmp_path,contract,arm='pi-native')['native']['native_outcome']is None


def test_known_abort_before_query_is_failure_not_a_missing_folder_guess(tmp_path):
    (tmp_path/'agent').mkdir();(tmp_path/'agent/experiment-setup.json').write_text(json.dumps({'expected_actor_stage_names':['ingest','query']}))
    (tmp_path/'result.json').write_text(json.dumps({'exception_info':{'exception_type':'AgentTimeoutError'},
        'step_results':[{'step_name':'ingest','exception_info':{'exception_type':'AgentTimeoutError'}}]}))
    result=grade_mab_trial(tmp_path,{'answers':['B'],'query_stage_id':'2'},arm='pi-native')
    assert result['native']['native_outcome']==0 and result['derived_action']['score']==0
    assert result['answer_evidence']['source']=='known_source_stage_abort'
