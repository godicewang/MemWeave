import hashlib
import json
from copy import deepcopy

from test_state_metrics import originals, save_state

from memweave_eval.state_journal_sources import registry_journals
from memweave_eval.state_metrics import task_state_metrics


def test_actual_committed_journals_repair_missing_archive_without_tool_input_inference(tmp_path):
    session,_,_,state=originals(tmp_path,writes={10:(2,False)})
    result=task_state_metrics([session],None,committed_journals={'task_x':state},baseline_journals={})
    assert result['fd_events_added']==2 and result['event_model_ratio']==.05
    assert result['write_model_positions']==[10]
    assert result['uniformity']['status']=='insufficient_sample'
    assert result['commit_evidence_source']=='terminal_task_registry'
    assert result['fd_added_scope']=='episode_delta_from_initial_inventory'


def test_missing_initial_inventory_and_historical_response_scope_are_not_silently_empty(tmp_path):
    session,archive,_,_=originals(tmp_path,writes={10:(2,False)})
    result=task_state_metrics([session],archive,require_initial_inventory=True)
    assert result['fd_events_added']is None and result['fd_events_journal_total']==2
    assert result['fd_events_active']==2 and result['ratio_status']=='unknown'
    result=task_state_metrics([session],archive,episode_returns=5)
    assert result['model_responses_with_usage']is None and result['session_model_responses_with_usage']==40
    assert result['writes']is None and result['uniformity']['status']=='unknown'
    assert task_state_metrics([session],None,enabled=False,require_initial_inventory=True)['fd_added_scope']=='not_applicable'


def test_initial_stock_is_not_new_events_and_disagreeing_sources_never_pick_a_winner(tmp_path):
    session,archive,_,state=originals(tmp_path,writes={10:(1,False)})
    state[1]['id']='F2';seed={'op_id':'prior-seed','op':'append_fact','id':'F1','fact':'old seed'}
    state.insert(1,seed)
    result=task_state_metrics([session],None,committed_journals={'task_x':state},baseline_journals={'task_x':state[:2]})
    assert result['fd_events_added']==1 and result['fd_events_active']==2
    assert result['write_model_positions']==[10]
    conflict=task_state_metrics([session],archive,committed_journals={'task_x':state},baseline_journals={})
    assert conflict['fd_events_added']is None and conflict['commit_evidence_source']=='conflicting_state_originals'
    corrupt=deepcopy(state);corrupt.append(corrupt[-1])
    assert task_state_metrics([session],None,committed_journals={'task_x':corrupt})['fd_events_added']is None


def test_cumulative_archives_are_selected_by_verified_prefix_not_mtime_or_order(tmp_path):
    session,full,_,state=originals(tmp_path,writes={10:(2,False)})
    older=tmp_path/'older.tar.gz';save_state(older,state[:1])
    for paths in [[older,full],[full,older]]:
        result=task_state_metrics([session],paths)
        assert result['fd_events_added']==result['fd_events_active']==2
    result=task_state_metrics([session],older,committed_journals={'task_x':state},baseline_journals={})
    assert result['fd_events_added']==2 and result['commit_evidence_source']=='terminal_task_registry'
    wrong=deepcopy(state);wrong[-1]['fact']='silent rewrite'
    damaged=tmp_path/'conflict.tar.gz';save_state(damaged,wrong)
    assert task_state_metrics([session],[full,damaged])['fd_events_added']is None


def registry_fixture(monkeypatch):
    blobs={}
    def snapshot(rows):
        raw=('\n'.join(json.dumps(r)for r in rows)+'\n').encode();digest=hashlib.sha256(raw).hexdigest();blobs[digest]=raw
        return {'workspace':'scope','task_id':'task_x','version':len(rows),'journal_sha256':digest,'journal_ref':{'sha256':digest}}
    goal={'op':'update_goal','op_id':'goal','goal':'g'};fact={'op':'append_fact','op_id':'new','id':'F1','fact':'one'}
    def frame(seq,phase,tasks,**kw):return {'event':'task_registry_checkpoint','phase':phase,'producer_id':'p','sequence':seq,
        'stage_id':'1','timestamp':str(seq),'registry':{'complete':True,'tasks':tasks},**kw}
    first=frame(1,'agent_start',[]);middle=frame(2,'after_tool',[snapshot([goal])]);last=frame(3,'agent_end',[snapshot([goal,fact])])
    monkeypatch.setattr('memweave_eval.state_journal_sources.read_object',lambda store,ref:blobs[ref['sha256']])
    return [first,middle,last],{('p',i):None for i in range(1,4)},snapshot,goal,fact


def test_registry_sources_require_terminal_inventory_hash_version_and_append_only_history(monkeypatch):
    events,locations,snapshot,goal,fact=registry_fixture(monkeypatch)
    result=registry_journals(events,locations,complete=True)
    assert result['complete']and result['baseline']=={}and len(result['journals']['task_x'])==2
    for broken in [events[:-1],events[1:]]:
        assert not registry_journals(broken,locations,complete=True)['complete']
    assert not registry_journals(events,locations,complete=False)['complete']
    changed=deepcopy(events);changed[-1]['registry']['tasks'][0]['version']=9
    assert not registry_journals(changed,locations,complete=True)['complete']
    changed=deepcopy(events);changed[-1]['registry']['tasks']=[]
    assert not registry_journals(changed,locations,complete=True)['complete'],'lost Task is not zero new events'
    changed=deepcopy(events);changed[-1]['registry']['complete']=False
    assert not registry_journals(changed,locations,complete=True)['complete']
    changed=deepcopy(events);changed[-1]['registry']['tasks']=[snapshot([dict(goal,goal='silent rewrite'),fact])]
    assert not registry_journals(changed,locations,complete=True)['complete']


def test_explicit_empty_initial_and_terminal_inventory_is_known_zero_not_missing(monkeypatch):
    events,locations,*_=registry_fixture(monkeypatch)
    events=[events[0],dict(events[-1],registry={'complete':True,'tasks':[]})]
    result=registry_journals(events,locations,complete=True)
    assert result['complete']and result['journals']==result['baseline']=={}
