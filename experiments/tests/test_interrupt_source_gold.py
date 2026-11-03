import json
from copy import deepcopy

import pytest

from memweave_eval.interrupt_source_gold import (
    CASES,
    REVISION,
    baseline_prefix,
    capture_final,
    contract_from_source,
    contract_hash,
    freeze_baseline,
    grade_capture,
)


def contract(case_id):
    spec=CASES[case_id];kind,task_id=spec['kind'],spec['task_id']
    if case_id=='INT-08':
        raw={'task_id':task_id,'intent':'Cancel order 302','transformed_initial_intent':'Cancel an order','updates':['Order 302']}
        targets=[{'url':'http://localhost:8083/admin/sales/order/view/order_id/302/',
            'locator':'document.querySelector("#order_status").outerText','required_contents':{'exact_match':'Canceled'}}]
    elif case_id=='INT-09':
        raw={'task_id':task_id,'intent':'111 Magnolia Path, Atlanta, GA, 30303',
            'transformed_initial_intent':'222 Oak Road, Atlanta, GA, 30305',
            'updates':['The street is 111 Magnolia Path, not 222 Oak Road.','And the zip code is 30303, not 30305.']}
        targets=[{'url':'http://localhost:8082/customer/address',
            'locator':f'document.querySelector(".box.box-address-{which} > .box-content").outerText',
            'required_contents':{'must_include':['111 Magnolia Path','Atlanta, Georgia, 30303']}}
            for which in ['shipping','billing']]
    else:
        raw={'task_id':task_id,'intent':'Show products under $30 in men shoes',
            'transformed_initial_intent':'Show products under $30 in men shoes with 4+ star ratings',
            'updates':['Actually, show all products under $30 regardless of rating.']};targets=[]
    config={'task_id':task_id,'true_intent':raw['intent'],'intent':raw['transformed_initial_intent'],
        'eval':{'eval_types':['program_html']if targets else['url_match'],'program_html':targets,
            'reference_url':''if targets else'http://localhost:8082/clothing-shoes-jewelry/men/shoes.html?price=0-30',
            'url_note':'GOLD in PRED'}}
    original=dict(config,intent=raw['intent']);original.pop('true_intent')
    case={'pack_case_id':case_id,'source_revision':REVISION,'upstream_case_id':f'{kind}:task_id={task_id}:60pct'}
    return contract_from_source(case,raw,config,original,{'raw':'a'*64,'config':'b'*64,'evaluator':'c'*64},fixture_only=True)


class Page:
    def __init__(self,context,url):self.context=context;self.url=url;self.closed=False
    def goto(self,url):self.url=url
    def evaluate(self,expression):
        if self.context.error:raise RuntimeError('simulated unavailable page')
        if '#order_status'in expression:return self.context.values['order']
        return self.context.values['shipping'if'shipping'in expression else'billing']
    def close(self):self.closed=True


class Context:
    def __init__(self,values=None):self.values=values or{};self.error=False;self.created=[]
    def new_page(self):
        page=Page(self,'about:blank');self.created.append(page);return page


@pytest.mark.parametrize('case_id',['INT-08','INT-09'])
def test_source_final_values_have_independent_required_checks_and_do_not_move_actor(case_id,tmp_path):
    gold=contract(case_id);context=Context({'order':'Canceled','shipping':'111 Magnolia Path\nAtlanta, Georgia, 30303',
        'billing':'111 Magnolia Path\nAtlanta, Georgia, 30303'})
    actor=Page(context,'http://localhost:8082/actor-unchanged')
    record=capture_final(context,actor,gold,tmp_path/'capture.json',fixture_control=True)
    result=grade_capture(gold,record)
    assert result['goal_checkpoint']['score']==100 and result['goal_checkpoint']['collection_complete']
    assert len(result['goal_checkpoint']['assertions'])>=2
    assert actor.url=='http://localhost:8082/actor-unchanged'and not actor.closed
    assert all(p.closed for p in context.created)
    wrong=deepcopy(record);wrong['queries'][0]['value']='Processing'if case_id=='INT-08'else'222 Oak Road\nAtlanta, Georgia, 30305'
    assert grade_capture(gold,wrong)['goal_checkpoint']['score']==0
    missing=deepcopy(record);missing['queries'].pop()
    point=grade_capture(gold,missing)['goal_checkpoint']
    assert point['score']is None and not point['collection_complete']


def test_source_query_identity_errors_and_missing_fields_never_default_to_success(tmp_path):
    gold=contract('INT-09');context=Context({'shipping':'111 Magnolia Path\nAtlanta, Georgia, 30303','billing':'111 Magnolia Path\nAtlanta, Georgia, 30303'})
    actor=Page(context,'http://localhost:8082');record=capture_final(context,actor,gold,tmp_path/'capture.json',fixture_control=True)
    both=deepcopy(record);both['queries'][0]['value']+='\n222 Oak Road\nAtlanta, Georgia, 30305'
    assert grade_capture(gold,both)['goal_checkpoint']['score']==0
    for key in ['locator','url','status','value']:
        missing=deepcopy(record);missing['queries'][0].pop(key)
        assert not grade_capture(gold,missing)['goal_checkpoint']['collection_complete']
    wrong=deepcopy(record);wrong['contract_sha256']='0'*64
    with pytest.raises(ValueError,match='contract'):grade_capture(gold,wrong)
    context.error=True;record=capture_final(context,actor,gold,tmp_path/'error.json',fixture_control=True)
    assert grade_capture(gold,record)['goal_checkpoint']['score']is None
    assert all(p.closed for p in context.created)
    with pytest.raises(TypeError):capture_final(context,actor,gold,tmp_path/'unmarked.json')


def test_native_url_match_cannot_prove_rating_retraction(tmp_path):
    gold=contract('INT-10');context=Context();url=gold['native_evaluation']['reference_url']
    actor=Page(context,url+'&rating=4');record=capture_final(context,actor,gold,tmp_path/'capture.json',fixture_control=True)
    result=grade_capture(gold,record)
    assert result['native_endpoint_checkpoint']['score']==100,'preserve pinned GOLD in PRED behavior'
    assert result['goal_checkpoint']['score']is None and not result['goal_checkpoint']['collection_complete']
    assert result['rating_retraction_status']=='BLOCKED_FILTER_OBSERVATION_NOT_IMPLEMENTED'
    wrong=deepcopy(record);wrong['actor_url']=wrong['actor_url_after_capture']='http://localhost:8082/wrong'
    assert grade_capture(gold,wrong)['native_endpoint_checkpoint']['score']==0
    missing=deepcopy(record);missing.pop('actor_url')
    assert grade_capture(gold,missing)['native_endpoint_checkpoint']['score']is None


def replay_file(tmp_path,gold,actions=None):
    actions=actions if actions is not None else[{'action_type':6,'element_id':str(i)}for i in range(4)]+[{'action_type':17,'answer':'HIDDEN-FUTURE-ANSWER'}]
    value={'version':1,'task_id':gold['task_id'],'intent':gold['initial_intent'],'num_actions':len(actions),
        'actions':actions,'interrupt':None}
    path=tmp_path/'baseline.json';path.write_text(json.dumps(value));return path


@pytest.mark.parametrize('case_id',['INT-08','INT-09','INT-10'])
def test_shared_baseline_prefix_is_hash_bound_and_cannot_leak_future_actions(case_id,tmp_path):
    gold=contract(case_id);path=replay_file(tmp_path,gold)
    frozen=freeze_baseline(gold,path,tmp_path/'frozen.json')
    assert frozen['total_actions']==5 and frozen['interrupt_at_action']==3
    with pytest.raises(ValueError,match='fixture'):baseline_prefix(gold,frozen)
    prefix=baseline_prefix(gold,frozen,fixture_control=True)
    assert len(prefix)==3 and 'HIDDEN-FUTURE-ANSWER'not in json.dumps(prefix)
    assert frozen['contract_sha256']==contract_hash(gold)
    assert frozen['behavior_opportunity_verified']is False
    path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError,match='baseline'):baseline_prefix(gold,frozen,fixture_control=True)


@pytest.mark.parametrize('mutation',['actions','num_actions','task_id','interrupt','stop'])
def test_malformed_or_early_ended_baseline_is_not_a_valid_common_prefix(mutation,tmp_path):
    gold=contract('INT-08');path=replay_file(tmp_path,gold);data=json.loads(path.read_text())
    if mutation=='actions':data.pop('actions')
    elif mutation=='num_actions':data['num_actions']=6
    elif mutation=='task_id':data['task_id']=True
    elif mutation=='interrupt':data['interrupt']={'prior':'already interrupted'}
    else:data['actions'][1]={'action_type':17}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):freeze_baseline(gold,path,tmp_path/'frozen.json')


def test_existing_cli_keeps_fixture_guard_and_only_returns_prefix_metadata(tmp_path):
    from types import SimpleNamespace

    from memweave_eval.fixed35_cli import execute
    gold=contract('INT-08');p=tmp_path/'contract.json';p.write_text(json.dumps(gold))
    context=Context({'order':'Canceled'});actor=Page(context,'http://localhost:8083/admin')
    capture=tmp_path/'capture.json';capture_final(context,actor,gold,capture,fixture_control=True)
    args=SimpleNamespace(fixed35_command='interrupt-final',contract=p,capture=capture,output=tmp_path/'grade.json',fixture_control=False)
    with pytest.raises(ValueError,match='fixture'):execute(args)
    assert not args.output.exists()
    args.fixture_control=True;assert execute(args)['collection_complete']is True
    source=replay_file(tmp_path,gold)
    result=execute(SimpleNamespace(fixed35_command='interrupt-baseline',contract=p,replay=source,output=tmp_path/'prefix.json'))
    assert result['interrupt_at_action']==3 and 'HIDDEN-FUTURE-ANSWER'not in json.dumps(result)


def test_report_uses_common_final_component_without_fabricating_official_reward(tmp_path):
    from memweave_eval.fixed35_report import single_report
    from memweave_eval.normalized_scores import catalogue
    from memweave_eval.storage import file_digest
    gold=contract('INT-09');gold['metric_matrix']=[{'metric_id':m['id'],
        'design_status':'PLANNED'if m['id']=='S.common.protected_constraints'else'DESIGN_NA',
        'reason':'synthetic integration scope, not source applicability','opportunity_ids':['unit-source-query']}
        for m in catalogue()['metrics']]
    p=tmp_path/'contract.json';p.write_text(json.dumps(gold));capture_root=tmp_path/'browser'
    (tmp_path/'admission.json').write_text(json.dumps({'case_id':'INT-09','family':'interrupt',
        'benchmark':'InterruptBench current main','contract_path':str(p),'contract_sha256':file_digest(p),
        'browser_evaluator_output':str(capture_root)}))
    collection={'state_metrics':{},'tools':{},'cache':{},'estimated_usd':0,'collection_complete':True,'fixture_control':True}
    (tmp_path/'pair-result.json').write_text(json.dumps({'arms':[{'arm':arm,'result_path':str(tmp_path/arm/'result.json'),
        'collection':collection,'exception':None,'verifier':None}for arm in ['pi-native','pi-memweave']]}))
    for arm in ['pi-native','pi-memweave']:
        context=Context({'shipping':'111 Magnolia Path\nAtlanta, Georgia, 30303','billing':'111 Magnolia Path\nAtlanta, Georgia, 30303'})
        capture_final(context,Page(context,'http://localhost:8082'),gold,capture_root/arm/'final.json',fixture_control=True)
    single_report(tmp_path,tmp_path/'reports',fixture_control=True)
    data=json.loads((tmp_path/'reports/results.json').read_text());assert data['fixture_scores_included']
    for row in data['rows']:
        assert row['native_reward']is None
        assert next(m for m in row['normalized_metrics']if m['id']=='S.common.protected_constraints')['score']==100
        assert row['derived_behavior_checkpoints'][0]['weights']=={'common_product':0,'plugin_memory':0}
    (capture_root/'pi-memweave/final.json').unlink()
    single_report(tmp_path,tmp_path/'missing',fixture_control=True)
    result=json.loads((tmp_path/'missing/results.json').read_text());assert not result['collection_accepted']
    row=result['rows'][1];assert next(m for m in row['normalized_metrics']if m['id']=='S.common.protected_constraints')['score']is None


@pytest.mark.parametrize(('index','fault'),[(i,f)for i in [0,1]for f in ['street','city_zip','old_street','old_city_zip']])
def test_each_address_field_and_old_value_guard_independently_gates_the_checkpoint(index,fault,tmp_path):
    gold=contract('INT-09');context=Context({'shipping':'111 Magnolia Path\nAtlanta, Georgia, 30303',
        'billing':'111 Magnolia Path\nAtlanta, Georgia, 30303'})
    record=capture_final(context,Page(context,'http://localhost:8082'),gold,tmp_path/'capture.json',fixture_control=True)
    row=record['queries'][index]
    if fault=='street':row['value']=row['value'].replace('111 Magnolia Path','333 Wrong Street')
    elif fault=='city_zip':row['value']=row['value'].replace('Atlanta, Georgia, 30303','Albany, Georgia, 30303')
    elif fault=='old_street':row['value']+='\n222 Oak Road'
    else:row['value']+='\nAtlanta, Georgia, 30305'
    point=grade_capture(gold,record)['goal_checkpoint']
    assert point['score']==0 and point['collection_complete']and len(point['failed_assertions'])==1


def test_failed_evaluator_page_close_preserves_capture_but_blocks_collection(tmp_path):
    gold=contract('INT-08');context=Context({'order':'Canceled'})
    def new_page():
        page=Page(context,'about:blank')
        def close():raise RuntimeError('do not store this diagnostic body')
        page.close=close;return page
    context.new_page=new_page
    record=capture_final(context,Page(context,'http://localhost:8083/admin'),gold,tmp_path/'capture.json',fixture_control=True)
    assert record['queries'][0]['value']=='Canceled'and record['evaluation_page_close_error']=='RuntimeError'
    assert 'diagnostic body'not in(tmp_path/'capture.json').read_text()
    assert grade_capture(gold,record)['goal_checkpoint']['score']is None


@pytest.mark.parametrize('count',range(1,12))
def test_prefix_rounding_uses_fixed_source_action_denominator_without_call_count_claim(count,tmp_path):
    gold=contract('INT-08');path=replay_file(tmp_path,gold,[{'action_type':6}for _ in range(count)])
    frozen=freeze_baseline(gold,path,tmp_path/'frozen.json')
    assert frozen['interrupt_at_action']==3*count//5
    assert len(baseline_prefix(gold,frozen,fixture_control=True))==3*count//5
    assert frozen['behavior_opportunity_verified']is False


def test_source_binding_rejects_wrong_revision_intent_and_non_source_javascript():
    gold=contract('INT-08');raw={'task_id':110,'intent':gold['true_intent'],
        'transformed_initial_intent':gold['initial_intent'],'updates':gold['updates']}
    config={'task_id':110,'intent':gold['initial_intent'],'true_intent':gold['true_intent'],'eval':gold['native_evaluation']}
    original=dict(config,intent=gold['true_intent']);original.pop('true_intent')
    case={'pack_case_id':'INT-08','source_revision':REVISION,'upstream_case_id':'1update:task_id=110:60pct'}
    with pytest.raises(ValueError,match='revision'):
        contract_from_source(dict(case,source_revision='0'*40),raw,config,original,gold['source_hashes'],fixture_only=True)
    with pytest.raises(ValueError,match='intent'):
        contract_from_source(case,raw,dict(config,true_intent='different task'),original,gold['source_hashes'],fixture_only=True)
    changed=deepcopy(config);changed['eval']['program_html'][0]['locator']='document.querySelector("#order_status");alert(1)'
    with pytest.raises(ValueError,match='locator'):
        contract_from_source(case,raw,changed,dict(original,eval=changed['eval']),gold['source_hashes'],fixture_only=True)
