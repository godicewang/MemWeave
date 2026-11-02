import json

import toml

from memweave_eval.fixed35_schedule import execute_schedule, pair_policy


def record(tmp_path,cpus,memory,seconds=2700,verify=1200):
    task=tmp_path/(str(cpus)+'-'+str(memory));task.mkdir()
    (task/'task.toml').write_text(toml.dumps({'environment':{'cpus':cpus,'memory_mb':memory},'verifier':{'timeout_sec':verify}}))
    return {'case_id':'c','task_path':str(task),'resources':{'cpus':cpus,'memory_mb':memory},'seconds':seconds}


def test_large_pairs_serialize_and_reserve_verification_before_second_arm(tmp_path):
    wdm=pair_policy(record(tmp_path,8,16384));ruby=pair_policy(record(tmp_path,4,24576))
    assert not wdm['parallel_arms']and not ruby['parallel_arms']
    assert wdm['reserved_cpus']==8 and ruby['reserved_memory_mb']==24576
    from memweave_eval.fixed35_execution import MODEL_CUTOFF
    assert wdm['latest_pair_start_unix']<=MODEL_CUTOFF-2*(2700+120)-1200
    ordinary=pair_policy(record(tmp_path,2,4096,900,300))
    assert ordinary['parallel_arms']and ordinary['reserved_cpus']==4


def test_pending_cases_never_launch_and_all_35_remain_in_queue_report(tmp_path):
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'cases':[
        {'case_id':str(i),'readiness':'NOT_ADMITTED','reason':'real canary authorization pending'}for i in range(35)]}))
    result=execute_schedule(plan,tmp_path/'output')
    assert result=={'dry_run':True,'paid_requests':0,'admitted_cases':0,'blocked_cases':35}
    assert (tmp_path/'output/frozen-plan.json').exists()
