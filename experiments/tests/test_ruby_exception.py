import json

import pytest

from memweave_eval.ruby_exception import BAN, EXCEPTION, exception_checkpoint, lock_policy


def records(*,ban=None,exception=EXCEPTION):
    return [{'text':json.dumps({'s':'rj','ban':list(BAN)if ban is None else ban}),'visible':True,'archived':False},
        {'text':json.dumps({'s':'rj','except':exception}),'visible':True,'archived':False}]


def lock(*names):
    return 'version = 4\n'+''.join('[[package]]\nname = '+json.dumps(n)+'\nversion = "1.0.0"\n'for n in names)


@pytest.mark.parametrize('names,expected',[(('axum',EXCEPTION),True),(('magnus',EXCEPTION),False),
    (('axum',),False),(('rb-sys',),False)])
def test_lock_checks_ban_minus_the_actual_sqlite_exception(names,expected):
    p=lock_policy({'status':'captured','text':lock(*names)})
    assert p['score']==(100 if expected else 0)and p['collection_complete']


@pytest.mark.parametrize('value',[{'status':'absent'},{'status':'captured','text':'broken ['},
    {'status':'captured','text':'version=4\npackage=[]'},
    {'status':'captured','text':'[[package]]\nname=42\nversion="1"'}])
def test_proved_undelivered_or_malformed_lock_is_failure_not_missing_capture(value):
    p=lock_policy(value);assert p['score']==0 and p['collection_complete']


@pytest.mark.parametrize('value',[None,{}, {'status':'incomplete'}, {'status':'captured'}])
def test_missing_capture_stays_missing(value):
    p=lock_policy(value);assert p['score']is None and not p['collection_complete']


@pytest.mark.parametrize('mode',['pass','drop-exception','wrong-ban','wrong-scope','hidden-old-conflict','missing-state','missing-boundary','no-change'])
def test_literal_memory_scope_timing_and_real_lock_are_independent_and_required(mode):
    entries=records();before=True;complete=True;opportunity=True
    if mode=='drop-exception':entries.pop()
    elif mode=='wrong-ban':entries=records(ban=['magnus'])
    elif mode=='wrong-scope':entries[1]['text']=json.dumps({'s':'other','except':EXCEPTION})
    elif mode=='hidden-old-conflict':entries.append({'text':json.dumps({'s':'rj','except':'magnus'}),'archived':False,'visible':False})
    elif mode=='missing-state':entries=None
    elif mode=='missing-boundary':complete=False
    elif mode=='no-change':opportunity=False
    p=exception_checkpoint(entries,lock_policy({'status':'captured','text':lock('axum',EXCEPTION)}),
        before_dependency=before,boundaries_complete=complete,opportunity=opportunity)
    if mode=='pass':assert p['score']==100 and len(p['assertions'])>=6
    elif mode in ['missing-state','missing-boundary']:assert p['score']is None and not p['collection_complete']
    elif mode=='no-change':assert p['score']is None and p['status']=='CONDITIONAL_NO_OPPORTUNITY'
    else:assert p['score']==0 and p['collection_complete']


def test_archived_conflict_is_history_but_unarchived_hidden_record_is_still_effective():
    entries=records();entries.append({'text':json.dumps({'s':'rj','except':'magnus'}),'archived':True,'visible':False})
    assert exception_checkpoint(entries,lock_policy({'status':'captured','text':lock(EXCEPTION)}),
        before_dependency=True,boundaries_complete=True,opportunity=True)['score']==100


def test_duplicate_keys_and_extra_exception_never_gain_a_pass():
    entries=records();entries.append({'text':'{"s":"rj","s":"rj","except":"magnus"}', 'archived':False,'visible':True})
    assert exception_checkpoint(entries,lock_policy({'status':'captured','text':lock(EXCEPTION)}),
        before_dependency=True,boundaries_complete=True,opportunity=True)['score']==0


@pytest.mark.parametrize('mode',['pass','late','forbidden','missing-final','missing-ref','native'])
def test_actual_cas_and_commit_replay_bind_cards_to_pre_mutation_boundary(tmp_path,monkeypatch,mode):
    import gzip
    from hashlib import sha256

    from memweave_eval.ruby_exception import VERSION, grade_trial
    from memweave_eval.storage import file_digest

    store=tmp_path/'store';(store/'objects').mkdir(parents=True)
    def put(raw):
        raw=raw.encode();h=sha256(raw).hexdigest();name='objects/'+h+'.gz';(store/name).write_bytes(gzip.compress(raw))
        return {'sha256':h,'bytes':len(raw),'object':name,'encoding':'gzip'}
    rows=[{'op':'update_goal','op_id':'g','goal':'Port RubyJournal'},
        {'op':'append_fact','op_id':'b','id':'F1','fact':records()[0]['text']},
        {'op':'append_fact','op_id':'e','id':'F2','fact':records()[1]['text']}]
    journal=put(''.join(json.dumps(r)+'\n'for r in(rows[:1]if mode=='late'else rows)))
    data=put(lock(EXCEPTION,'magnus')if mode=='forbidden'else lock(EXCEPTION))
    def workspace(phase,seq,h,**kwargs):return {'event':'workspace_checkpoint','producer_id':'p','sequence':seq,
        'phase':phase,'workspace':{'tree_projections':{'ruby-dependency':{'status':'complete','complete':True,
        'projection_sha256':h*64}},'artifacts':{}},**kwargs}
    events=[workspace('agent_start',1,'a'),{'event':'request_ready','producer_id':'p','sequence':2,
        'prepared_boundary':{'expected_task_id':'task-test','expected_journal_ref':journal}},
        {'event':'tool_call','producer_id':'p','sequence':3,'call_id':'write'},
        workspace('tool_end',4,'b',call_id='write'),workspace('agent_end',5,'b')]
    events[-1]['workspace']['artifacts']['rj-rust/Cargo.lock']={'status':'captured','sha256':data['sha256'],'ref':data}
    if mode=='missing-final':events.pop()
    if mode=='missing-ref':events[-1]['workspace']['artifacts']['rj-rust/Cargo.lock'].pop('ref')
    locations={('p',e['sequence']):store for e in events}
    monkeypatch.setattr('memweave_eval.ruby_exception.exception_observations',lambda _:(events,locations,{'complete':True}))
    source=tmp_path/'instruction.md';source.write_text('unit public constraint')
    c={'version':VERSION,'case_id':'LONG-05','ban':list(BAN),'except':EXCEPTION,
        'instruction_path':str(source),'instruction_sha256':file_digest(source),'fixture_only':True}
    result=grade_trial(tmp_path,c,arm='pi-native'if mode=='native'else'pi-memweave')
    if mode=='pass':assert result['common']['score']==result['plugin']['score']==100 and result['collection_complete']
    elif mode=='late':assert result['plugin']['score']==0 and result['collection_complete']
    elif mode=='forbidden':assert result['common']['score']==result['plugin']['score']==0 and result['collection_complete']
    elif mode=='native':assert result['plugin']['status']=='DESIGN_NA'and result['common']['score']==100
    else:assert not result['collection_complete']


@pytest.mark.parametrize('mode',['pass','missing','native','fixture-rejected','changed-contract'])
def test_existing_report_attaches_opt_in_component_without_changing_original_outcome(tmp_path,monkeypatch,mode):
    from memweave_eval.fixed35_report import attach_ruby_exception, mark_checkpoint_collection
    from memweave_eval.storage import file_digest
    path=tmp_path/'component.json';path.write_text('{}')
    reference={'path':str(path),'sha256':file_digest(path)}
    point=lock_policy({'status':'captured','text':lock(EXCEPTION)})
    plugin=exception_checkpoint(None if mode=='missing'else records(),point,
        before_dependency=True,boundaries_complete=True,opportunity=True)
    if mode=='native':plugin={'score':None,'status':'DESIGN_NA','collection_complete':True}
    component={'common':point,'plugin':plugin,'scope':'finite source-bound fixture',
        'collection_complete':point['collection_complete']and plugin['collection_complete'],'fixture_only':True}
    monkeypatch.setattr('memweave_eval.ruby_exception.grade_trial',lambda *a,**k:component)
    row={'native_reward':0,'normalization_evidence':{},'derived_behavior_checkpoints':[{'id':'original'}]}
    if mode=='changed-contract':path.write_text('{"changed":true}')
    if mode in {'fixture-rejected','changed-contract'}:
        with pytest.raises(ValueError):attach_ruby_exception(row,tmp_path,{'exception_contract':reference},'pi-memweave',fixture_control=False)
        return
    attach_ruby_exception(row,tmp_path,{'exception_contract':reference},'pi-native'if mode=='native'else'pi-memweave',fixture_control=True)
    assert row['native_reward']==0 and len(row['derived_behavior_checkpoints'])==3
    assert row['normalization_evidence']['S.common.dependency_constraints']['value']==1
    evidence=row['normalization_evidence']['S.case_v2.C2-literal']
    if mode=='missing':
        assert evidence['value']is None and evidence['status']=='unknown'
        metrics=[{'id':'F35.C2-literal','status':'unknown'}]
        mark_checkpoint_collection(metrics,{'F35.C2-literal':plugin})
        assert metrics[0]['collection_status']=='REPAIR_REQUIRED'
    elif mode=='native':assert evidence['status']=='not_applicable'
    else:assert evidence['value']==1
