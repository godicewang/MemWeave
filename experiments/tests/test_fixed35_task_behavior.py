import json

import pytest

from memweave_eval.behavior_metrics import evaluate_behavior
from memweave_eval.fixed35_task_behavior import extract_task_opportunity


def test_actual_state_delivery_accepts_preserved_array_content_as_well_as_text():
    from memweave_eval.fixed35_task_behavior import delivered_state_blocks
    text='# Symbolic State\n\ntask_id: task_a\nstate_version: 4\n'
    for content in [text,[{'type':'text','text':text}]]:
        payload={'messages':[{'role':'user','content':content}]}
        assert delivered_state_blocks(payload)==[{'task_id':'task_a','version':4}]
        assert payload['messages'][0]['content']==content
    assert delivered_state_blocks({'messages':[{'content':[{'type':'image_url','image_url':{}}]}]})==[]


def registry(phase,tasks,bound='task_old',call=None,order=0):
    return {'stage_id':'4','event':'task_registry_checkpoint','phase':phase,'call_id':call,
        'registry':{'complete':True,'tasks':tasks},'binding':{'task_id':bound,'version':3,
            'status':'CAPTURED'if bound else'NO_BOUND_TASK'},'_order':order}


def task(identity='task_old',goal='a'*64):
    return {'task_id':identity,'workspace':'scope','goal_sha256':goal,'journal_sha256':'b'*64,
        '_projection':{'Goal':'protected goal','F1':'constraint','D1':'next step'}}


def tool(name,identity='call',args=None,order=1):
    return {'stage_id':'4','event':'tool_call','call_id':identity,'tool':name,
        '_value':{'input':args or{}},'_order':order}


def reply(identity='call',value=None,error=False):
    return {'stage_id':'4','event':'tool_execution_end','call_id':identity,'_value':{
        'isError':error,'result':{'content':[{'type':'text','text':json.dumps(value)}]}}}


def score(gold,rows,action=None):
    obs=extract_task_opportunity(gold,rows,action_evidence=action)
    return evaluate_behavior({'version':'fixture','cases':[gold]},{gold['id']:obs}),obs


def protocol(rows):
    """Positive fixture builder explicitly supplies all native hook boundaries."""
    result=[];latest=None
    before={r.get('call_id')for r in rows if r.get('phase')=='before_tool'}
    after={r.get('call_id')for r in rows if r.get('phase')=='after_tool'}
    calls={r.get('call_id'):r for r in rows if r.get('event')=='tool_call'}
    for row in rows:
        if row.get('event')=='tool_call'and row['call_id']not in before and latest:
            result.append(dict(latest,phase='before_tool',call_id=row['call_id'],_order=row['_order']-.1))
        result.append(row)
        if row.get('event')=='task_registry_checkpoint':latest=row
        if row.get('event')=='tool_execution_end'and row['call_id']not in after and latest:
            result.append(dict(latest,phase='after_tool',call_id=row['call_id'],_order=calls[row['call_id']]['_order']+.1))
    return result


def test_task_search_real_arguments_result_ranking_and_limit_missing():
    gold={'id':'T1','kind':'retrieval','stage_id':'4','k':3,'relevant':['task_old'],
        'best':['task_old'],'frozen_default_limit':5,'requires_query':True}
    before=registry('agent_start',[task()]);end=registry('agent_end',[task()],order=9)
    query=tool('task_find',args={'query':'previous task'})
    rows=protocol([before,query,reply(value=[{'task_id':'task_old','score':.4}]),end])
    result,obs=score(gold,rows)
    assert result['metrics']['hit_at_k']['value']==1 and result['metrics']['best_top1']['value']==1
    assert obs['query']=='previous task'and obs['raw_candidates'][0]['score']==.4
    bad=protocol([before,query,reply(value=[{'task_id':'wrong'},{'task_id':'task_old'}]),end])
    result,_=score(gold,bad)
    assert result['metrics']['hit_at_k']['value']==1 and result['metrics']['best_top1']['value']==0
    assert result['metrics']['top1_given_best_hit']['denominator']==1
    for missing in [[before,query,end],[query,reply(value=[]),end]]:
        result,_=score(gold,missing);assert result['metrics']['hit_at_k']['unknown']==1
    result,_=score(gold,[before,end]);assert result['metrics']['hit_at_k']['value']==0
    query=tool('task_find',args={'query':'previous task','limit':2})
    result,_=score(gold,protocol([before,query,reply(value=[{'task_id':'task_old'}]),end]))
    assert result['metrics']['hit_at_k']['unknown']==1


def test_blocked_search_with_public_tool_result_is_known_failure_not_missing_receipt():
    gold={'id':'T1','kind':'retrieval','stage_id':'4','k':1,'relevant':['task_old'],
        'best':['task_old'],'frozen_default_limit':5}
    rows=[registry('agent_start',[task()]),registry('before_tool',[task()],call='call'),
        tool('task_find',args={'query':'old'}),
        {'stage_id':'4','event':'tool_result','call_id':'call',
            '_value':{'isError':True,'content':[{'type':'text','text':'blocked'}]}},
        registry('after_tool',[task()],call='call'),registry('agent_end',[task()])]
    result,obs=score(gold,rows)
    assert obs['complete']and result['metrics']['hit_at_k']['value']==0
    with pytest.raises(ValueError,match='query-time'):
        score(dict(gold,relevant=['not_created_yet'],best=['not_created_yet']),
            [dict(r,_value=dict(r.get('_value',{}),isError=False,result={'content':[{'type':'text','text':'[]'}]}))if r['event']=='tool_result'else r for r in rows])


def test_task_restore_requires_actual_state_delivery_and_every_program_action_check():
    gold={'id':'T2','kind':'restore','stage_id':'4','targets':['task_old'],
        'critical_tools':['write','edit'],'required_checkers':['config','regression']}
    action={'first_action_call_id':'call','program_checks':[{'checker_id':c,'call_id':'call',
        'passed':True,'evidence_sha256':'c'*64}for c in gold['required_checkers']]}
    prepare={'stage_id':'4','event':'request_ready','_order':1,
        'prepared_boundary':{'expected_task_id':'task_old','expected_version_at_prepare':3},
        '_delivered_state':[{'task_id':'task_old','version':3}]}
    rows=protocol([registry('agent_start',[task()]),prepare,
        registry('before_tool',[task()],call='call',order=2),tool('write',order=3),
        reply(value={}),registry('agent_end',[task()],order=5)])
    result,_=score(gold,rows,action);assert result['metrics']['restore_end_to_end']['value']==1
    failed=json.loads(json.dumps(action));failed['program_checks'][1]['passed']=False
    result,_=score(gold,rows,failed);assert result['metrics']['restore_end_to_end']['value']==0
    result,_=score(gold,rows,{});assert result['metrics']['restore_end_to_end']['unknown']==1
    absent=[dict(r,_delivered_state=[])if r is prepare else r for r in rows]
    result,_=score(gold,absent,action);assert result['metrics']['restore_end_to_end']['value']==0
    unobserved=[{k:v for k,v in r.items()if k!='_delivered_state'}if r is prepare else r for r in rows]
    result,_=score(gold,unobserved,action);assert result['metrics']['restore_end_to_end']['unknown']==1


def test_source_probe_critical_boundary_uses_observed_file_commit_not_an_earlier_unrelated_command():
    gold={'id':'T2','kind':'restore','stage_id':'4','targets':['task_old'],
        'critical_tools':['bash','write'],'critical_boundary':'program_action_call_id','required_checkers':['artifact']}
    action={'first_action_call_id':'commit','program_checks':[{'checker_id':'artifact','call_id':'commit',
        'passed':True,'evidence_sha256':'c'*64}]}
    prepare={'stage_id':'4','event':'request_ready','_order':2,
        'prepared_boundary':{'expected_task_id':'task_old','expected_version_at_prepare':3},
        '_delivered_state':[{'task_id':'task_old','version':3}]}
    rows=protocol([registry('agent_start',[task()]),tool('bash','read-other',order=1),reply('read-other',value={}),
        prepare,registry('before_tool',[task()],call='commit',order=3),tool('bash','commit',order=4),
        reply('commit',value={}),registry('agent_end',[task()],order=8)])
    result,_=score(gold,rows,action)
    assert result['metrics']['restore_end_to_end']['value']==1
    action['first_action_call_id']='not-observed'
    result,_=score(gold,rows,action)
    assert result['metrics']['restore_end_to_end']['unknown']==1


def test_independent_goal_create_and_deadline_require_durable_objects():
    gold={'id':'T3','kind':'route','stage_id':'4','allowed':['create'],'must_create':True,
        'goal_sha256':'a'*64,'workspace':'scope'}
    rows=protocol([registry('agent_start',[task()]),tool('task_create'),reply(value={}),
        registry('after_tool',[task(),task('task_new')],bound='task_new',call='call'),
        registry('agent_end',[task(),task('task_new')],bound='task_new')])
    result,obs=score(gold,rows,{'creation_before_dependency':True})
    assert result['metrics']['create_recall']['value']==1 and obs['created_ids']==['task_new']
    result,_=score(gold,rows,{'creation_before_dependency':False})
    assert result['metrics']['create_recall']['value']==0
    result,_=score(gold,rows,{})
    assert result['metrics']['create_recall']['unknown']==1
    result,_=score(gold,[registry('agent_start',[task()]),registry('agent_end',[task()])])
    assert result['metrics']['create_recall']['value']==0


def test_simple_detour_requires_answer_and_protected_projection_even_with_no_create():
    gold={'id':'T4','kind':'route','stage_id':'4','allowed':['continue','no-persistent-task'],
        'simple':True,'accepted_answers':['12'],'protected_fields':{'task_old':['Goal','F1','D1']}}
    answer={'stage_id':'4','event':'assistant_return','_value':{'content':[{'type':'text','text':'12'}]}}
    rows=[registry('agent_start',[task()]),answer,registry('agent_end',[task()])]
    result,_=score(gold,rows);assert result['metrics']['simple_no_create_and_complete']['value']==1
    wrong=dict(answer,_value={'content':[{'type':'text','text':'13'}]})
    result,_=score(gold,[rows[0],wrong,rows[-1]]);assert result['metrics']['simple_no_create_and_complete']['value']==0
    changed=dict(task(),_projection={'Goal':'changed goal','F1':'constraint','D1':'next step'})
    result,_=score(gold,[rows[0],answer,registry('agent_end',[changed])])
    assert result['metrics']['simple_no_create_and_complete']['value']==0
    result,_=score(gold,rows[:-1]);assert result['metrics']['simple_no_create_and_complete']['unknown']==1
    # A created-then-deleted persistent object still violates the simple detour.
    intermediate=registry('after_tool',[task(),task('task_temporary')],call='create',order=2)
    mutation=protocol([rows[0],tool('task_create','create'),reply('create'),intermediate,
        tool('bash','delete',order=3),reply('delete'),
        registry('after_tool',[task()],call='delete',order=4),answer,rows[-1]])
    result,_=score(gold,mutation)
    assert result['metrics']['simple_no_create_and_complete']['value']==0
    extra=dict(task(),journal_sha256='c'*64,_projection={**task()['_projection'],'F2':'unprotected new note'})
    result,_=score(gold,[rows[0],answer,registry('agent_end',[extra])])
    assert result['metrics']['simple_no_create_and_complete']['value']==1


@pytest.mark.parametrize('missing',['complete','tasks'])
def test_incomplete_registry_never_defaulted_to_empty_creation(missing):
    gold={'id':'simple','kind':'route','stage_id':'4','allowed':['continue'],'simple':True,
        'accepted_answers':['12'],'protected_fields':{'task_old':['Goal','F1']}}
    row=registry('agent_start',[task()]);row['registry'].pop(missing)
    if missing=='tasks':row['registry']['complete']=False
    result,obs=score(gold,[row,registry('agent_end',[task()])])
    assert 'created_ids'not in obs and result['metrics']['simple_no_create_and_complete']['unknown']==1


def test_protected_projection_tracks_corrections_and_evictions_without_freezing_unrelated_notes():
    from memweave_eval.fixed35_task_behavior import journal_projection
    rows=[{'op_id':'g','op':'update_goal','goal':'original'},
        {'op_id':'f','op':'append_fact','id':'F1','fact':'old'},
        {'op_id':'d','op':'append_decision','id':'D1','decision':'next'}]
    assert journal_projection(rows)=={'Goal':'original','F1':'old','D1':'next'}
    rows.append({'op_id':'m','op':'modify_fact','archive':['F1'],'append_fact':{'content':'new'}})
    assert journal_projection(rows)=={'Goal':'original','F2':'new','D1':'next'}
    rows.append({'op_id':'s','op':'slide_window','evicted_range':{'from':1,'to':3},'retained_ids':[]})
    assert journal_projection(rows)=={'Goal':'original','F2':'new'}


def test_creation_deadline_is_measured_from_real_registry_commit_before_first_dependency():
    gold={'id':'create','kind':'route','stage_id':'4','allowed':['create'],'must_create':True,
        'goal_sha256':'a'*64,'workspace':'scope','creation_deadline':'first_critical_action_or_episode_end',
        'critical_tools':['write']}
    rows=protocol([registry('agent_start',[task()]),tool('task_create',identity='create',order=1),reply('create'),
        registry('after_tool',[task(),task('task_new')],bound='task_new',call='create',order=2),
        tool('write',order=3),reply(),registry('agent_end',[task(),task('task_new')],bound='task_new',order=4)])
    result,_=score(gold,rows);assert result['metrics']['create_recall']['value']==1
    late=[dict(r,_order=5)if r.get('phase')=='after_tool'else r for r in rows]
    result,_=score(gold,late);assert result['metrics']['create_recall']['value']==0
    missing=[r for r in rows if not(r.get('phase')=='after_tool'and r.get('call_id')=='create')]
    result,_=score(gold,missing);assert result['metrics']['create_recall']['unknown']==1
