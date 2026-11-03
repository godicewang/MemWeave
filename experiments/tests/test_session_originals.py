import json
from copy import deepcopy

import pytest

from memweave_eval.fixed35_identity_window import identity_selection, identity_window_checkpoint
from memweave_eval.session_originals import (
    MissingSessionOriginals,
    load_original_sessions,
    with_foreign_originals,
)


def fixture(tmp_path):
    rows=[]
    def entry(identity,kind='message',message=None,custom=None,data=None):
        row={'id':identity,'parentId':rows[-1]['id']if rows else None,'type':kind,'timestamp':'2026-11-03T00:00:01Z'}
        if message:row['message']=message
        if custom:row.update(customType=custom,data=data)
        rows.append(row)
    entry('scope','custom',custom='memweave.scope.v1',data={'task_id':'A'})
    entry('same',message={'role':'user','content':'source A'})
    entry('a0',message={'role':'assistant','content':[{'type':'text','text':'source acknowledged'}]})
    original=deepcopy(rows);rows=[]
    entry('same',message={'role':'user','content':'return to source A'})
    entry('call',message={'role':'assistant','content':[{'type':'toolCall','id':'c','name':'task_resume','arguments':{'task_id':'A'}}]})
    receipt={'task_id':'A','source_session_id':'origin','source_anchor_entry_id':'a0','target_anchor_entry_id':None,
        'seed_event_ids':['same','a0'],'recent_turns':20,'evict_turns':4}
    entry('resume','custom',custom='memweave.resume.v1',data=receipt)
    entry('scopeA','custom',custom='memweave.scope.v1',data={'task_id':'A'})
    entry('result',message={'role':'toolResult','toolCallId':'c','content':[{'type':'text','text':'restored'}]})
    for row in rows:row['timestamp']='2026-11-03T00:00:02Z'
    folder=tmp_path/'agent/sessions';folder.mkdir(parents=True)
    for name,entries in [('origin',original),('target',rows)]:
        values=[{'type':'session','version':3,'id':name},*entries]
        (folder/(name+'.jsonl')).write_text(''.join(json.dumps(e)+'\n'for e in values))
    source=[r['message']for r in rows if r['type']=='message'];ids=[r['id']for r in rows if r['type']=='message']
    messages=[{'id':i,'sha256':i,'role':m['role'],'stop_reason':None,
        'calls':['c']if i=='call'else[],'result_id':'c'if i=='result'else None}for i,m in zip(ids,source,strict=True)]
    ledger=[dict(id=r['id'],parent_id=r['parentId'],type=r['type'],**({'custom_type':r['customType'],'data':r['data']}if'customType'in r else{}))for r in rows]
    shape={'version':'native-window-shape-v2','session_id':'target','unsupported_lifecycle':True,
        'previous_window':None,'branch_ledger':ledger,'messages':messages}
    descriptors=[{'entry_id':i,'sha256':i}for i in ids]
    payload={'messages':[{'role':'user','content':'source A'},{'role':'assistant','content':'source acknowledged'},
        {'role':'user','content':'return to source A'},{'role':'assistant','content':'','tool_calls':[{
            'id':'c','function':{'name':'task_resume','arguments':'{"task_id":"A"}'}}]},
        {'role':'tool','tool_call_id':'c','content':'restored'}]}
    return shape,descriptors,source,payload,folder


def test_foreign_originals_are_frozen_at_anchor_and_namespaced_without_trusting_receipt_alone(tmp_path):
    shape,d,source,payload,folder=fixture(tmp_path)
    originals=load_original_sessions(tmp_path)
    enriched,ds,ss,proof=with_foreign_originals(shape,d,source,originals,'2026-11-03T00:00:03Z')
    ids,window=identity_selection(enriched,recent_turns=20,evict_turns=4)
    assert ids==['origin:same','origin:a0','same','call','result']
    assert identity_window_checkpoint(enriched,ds,ss,payload,window,recent_turns=20,evict_turns=4)[0]is True
    assert proof['source_original_sha256']and'foreign_source'not in shape
    # Source later grows on another branch; the declared prefix does not.
    with (folder/'origin.jsonl').open('a')as f:f.write(json.dumps({'id':'later','parentId':'a0','type':'message',
        'timestamp':'2026-11-03T00:00:09Z','message':{'role':'user','content':'later unrelated goal'}})+'\n')
    enriched2,ds2,ss2,_=with_foreign_originals(shape,d,source,load_original_sessions(tmp_path),'2026-11-03T00:00:03Z')
    assert identity_window_checkpoint(enriched2,ds2,ss2,payload,window,recent_turns=20,evict_turns=4)[0]is True
    wrong=deepcopy(enriched2);wrong['branch_ledger'][2]['data']['seed_event_ids']=[]
    assert identity_window_checkpoint(wrong,ds2,ss2,payload,window,recent_turns=20,evict_turns=4)[0]is False


def test_missing_foreign_originals_or_anchors_are_not_evidence_of_correct_restoration(tmp_path):
    shape,d,s,_,folder=fixture(tmp_path);originals=load_original_sessions(tmp_path)
    with pytest.raises(MissingSessionOriginals):with_foreign_originals(shape,d,s,{},'2026-11-03T00:00:03Z')
    wrong=deepcopy(shape);wrong['branch_ledger'][2]['data']['source_anchor_entry_id']='not captured'
    # Target declaration and independent original must first agree.
    with pytest.raises(ValueError):with_foreign_originals(wrong,d,s,originals,'2026-11-03T00:00:03Z')
    (folder/'origin.jsonl').unlink()
    with pytest.raises(MissingSessionOriginals):with_foreign_originals(shape,d,s,load_original_sessions(tmp_path),'2026-11-03T00:00:03Z')


def test_inconsistent_clocks_are_unknown_but_target_content_mismatch_is_known(tmp_path):
    shape,d,s,_,_=fixture(tmp_path);originals=load_original_sessions(tmp_path)
    originals['origin']['entries']['a0']['timestamp']='2026-11-03T00:00:04Z'
    with pytest.raises(MissingSessionOriginals,match='clock evidence'):with_foreign_originals(shape,d,s,originals,'2026-11-03T00:00:03Z')
    originals=load_original_sessions(tmp_path);s[0]['content']='changed after capture'
    with pytest.raises(ValueError,match='content differs'):with_foreign_originals(shape,d,s,originals,'2026-11-03T00:00:03Z')


def test_pending_foreign_tail_after_frozen_anchor_is_not_loaded(tmp_path):
    shape,d,s,p,folder=fixture(tmp_path)
    with (folder/'origin.jsonl').open('a')as f:f.write(json.dumps({'id':'pending','parentId':'a0','type':'message',
        'timestamp':'2026-11-03T00:00:02Z','message':{'role':'assistant','content':[{'type':'toolCall',
            'id':'pending-call','name':'bash','arguments':{'command':'long operation'}}]}})+'\n')
    enriched,ds,ss,_=with_foreign_originals(shape,d,s,load_original_sessions(tmp_path),'2026-11-03T00:00:03Z')
    _,window=identity_selection(enriched,recent_turns=20,evict_turns=4)
    assert identity_window_checkpoint(enriched,ds,ss,p,window,recent_turns=20,evict_turns=4)[0]is True


@pytest.mark.parametrize('tail',['{incomplete','{bad-json}\n'])
def test_truncated_or_corrupt_original_is_missing_evidence_not_a_fabricated_score(tmp_path,tail):
    *_,folder=fixture(tmp_path)
    with (folder/'origin.jsonl').open('a')as f:f.write(tail)
    with pytest.raises(MissingSessionOriginals):load_original_sessions(tmp_path)
