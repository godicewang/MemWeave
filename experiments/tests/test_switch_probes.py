import json
from copy import deepcopy

import pytest

from memweave_eval.fixed35_switch_probes import PROBES, grade_probe, route_marker


@pytest.mark.parametrize('identity',list(PROBES))
def test_source_probe_has_independent_schema_scope_and_each_constraint(identity):
    for probe in PROBES[identity]:
        payload=dict(probe['expected'])
        assert grade_probe(json.dumps(payload),probe)['score']==100
        for key,value in payload.items():
            wrong=deepcopy(payload);wrong[key]=not value if type(value)is bool else 'wrong scope or value'
            assert grade_probe(json.dumps(wrong),probe)['score']==0
        assert grade_probe(None,probe)['score']is None
        assert grade_probe('',probe)['score']==0
        assert grade_probe(json.dumps(dict(payload,extra='not allowed')),probe)['score']==0
        assert grade_probe('{"checkout":"a","checkout":"b"}',probe)['score']==0


def test_source_route_marker_is_exactly_one_explicit_closed_set_identity():
    assert route_marker('ROUTE w01-base64-strict\nHarden base64.')=='w01-base64-strict'
    assert route_marker('Notes mention ROUTE w01-base64-strict somewhere')is None
    assert route_marker('ROUTE w01-base64-strict\nROUTE other')is None


def test_creation_deadline_uses_actual_git_change_and_missing_capture_never_means_no_change():
    from memweave_eval.fixed35_switch_replay import mutation_deadline, source_targets
    def frame(order,phase,digest='a',call=None):
        return {'event':'workspace_checkpoint','stage_id':'2','phase':phase,'_order':order,
            'producer_id':'p','call_id':call,'workspace':{'git_worktrees':{'w03':{
                'status':'complete','projection_sha256':digest}}}}
    rows=[frame(0,'agent_start'),{'event':'tool_call','stage_id':'2','_order':1,'producer_id':'p','call_id':'write'},
        frame(2,'tool_end','b','write'),frame(3,'agent_end','b')]
    assert mutation_deadline(rows,'2','w03')==(1,None)
    assert mutation_deadline([rows[0],frame(4,'agent_end')],'2','w03')==(4,None)
    missing=deepcopy(rows);missing[2]['workspace']['git_worktrees']['w03']['status']='incomplete'
    assert mutation_deadline(missing,'2','w03')[0]is None
    assert mutation_deadline(rows[:2],'2','w03')[0]is None
    assert source_targets({'complete':True,'tasks':[{'task_id':'independent','_projection':{
        'Goal':'ROUTE w03-password-hasher-async\nAsync password checking'}}]},'w03-password-hasher-async')==['independent']
    assert source_targets({'complete':True,'tasks':[{'task_id':'unobserved'}]},'w03-password-hasher-async')is None


def test_source_binding_must_be_observed_at_the_actual_mutation_call_not_only_at_end():
    from memweave_eval.fixed35_switch_replay import binding_at_deadline
    call={'stage_id':'2','_order':3,'producer_id':'p','event':'tool_call','call_id':'write'}
    before={'stage_id':'2','_order':4,'producer_id':'p','event':'task_registry_checkpoint','phase':'before_tool',
        'call_id':'write','event_sha256':'a'*64,'binding':{'status':'CAPTURED','task_id':'wrong'}}
    end=dict(before,_order=9,phase='agent_end',binding={'status':'CAPTURED','task_id':'target'})
    assert binding_at_deadline([call,before,end],'2',3,['target'])['passed']is False
    assert binding_at_deadline([call,end],'2',3,['target'])['passed']is None
    assert binding_at_deadline([end],'2',9,['target'])['passed']is True


def test_forbidden_persistent_creation_is_known_wrong_without_a_goal_semantics_judge():
    from memweave_eval.behavior_metrics import evaluate_behavior
    gold={'version':'source-case','cases':[{'id':'simple','kind':'route','allowed':['continue'],
        'simple':True}]}
    evidence={'simple':{'complete':True,'route':'create','created_ids':['new'],'create_attempts':1,
        'answer_passed':True,'protected_unchanged':True}}
    result=evaluate_behavior(gold,evidence)
    assert result['metrics']['create_precision']['value']==0
    assert result['metrics']['simple_no_create_and_complete']['value']==0


def test_probe_assertions_and_opportunities_are_distinct_denominators():
    from memweave_eval.fixed35_switch_replay import checkpoint_metric
    def p(score):return {'checkpoint':{'score':score}}
    assert checkpoint_metric([p(100),p(0),p(100)])['value']==pytest.approx(2/3)
    missing=checkpoint_metric([p(100),p(None)])
    assert missing['value']is None and missing['numerator']==1 and missing['unknown']==1
    assert checkpoint_metric([])['status']=='not_applicable'


def test_original_tests_remain_separate_from_remembered_contract_probe(tmp_path):
    from memweave_eval.fixed35_switch_replay import source_final
    contract={'original_stage_ids':{'final':'20'},'source_component':{'case_id':'INT-06',
        'response_task_id':'source','f2p':['one'],'p2p':['two'],'protected_paths':[],'scope':'original only'}}
    missing=source_final(tmp_path,contract,[])
    assert missing['native_metrics']['passed']is None
    folder=tmp_path/'steps/final/verifier';folder.mkdir(parents=True)
    (folder/'candidate.outcomes.json').write_text(json.dumps({'one':'pass','two':'fail','unrelated':'pass'}))
    (folder/'result.json').write_text(json.dumps({'status':'graded'}))
    known=source_final(tmp_path,contract,[])
    assert known['native_metrics']['passed']==1 and known['native_metrics']['total']==2
    assert known['checkpoints'][0]['score']is None and known['checkpoints'][1]['score']==0
    (folder/'result.json').write_text(json.dumps({'status':'error'}))
    assert source_final(tmp_path,contract,[])['native_metrics']['passed']is None
