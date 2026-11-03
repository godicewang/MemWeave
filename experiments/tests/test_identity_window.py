from copy import deepcopy

from memweave_eval.fixed35_identity_window import identity_selection, identity_window_checkpoint


def fixture():
    source=[{'role':'user','content':'old source'}, {'role':'assistant','content':[{'type':'text','text':'ack'}]},
        {'role':'user','content':'new source'}]
    shape={'version':'native-window-shape-v1','session_id':'s','previous_window':None,
        'unsupported_lifecycle':False,'messages':[{'id':str(i),'role':m['role'],'calls':[],
            'result_id':None,'stop_reason':None,'sha256':str(i)}for i,m in enumerate(source)]}
    descriptors=[{'entry_id':str(i),'sha256':str(i)}for i in range(3)]
    _ids,metadata=identity_selection(shape,recent_turns=2,evict_turns=1)
    payload={'messages':[{'role':m['role'],'content':m['content']}for m in source]}
    return shape,descriptors,source,payload,metadata


def test_uncommitted_pending_is_still_visible_then_committed_boundary_excludes_it():
    shape,descriptors,source,payload,metadata=fixture()
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is True
    assert metadata['pending'][0]['candidate_event_ids']==['0']
    shape['previous_window']=dict(metadata,stage='commit',boundary_entry_id='0',pending=[],completed_by='after')
    payload['messages']=payload['messages'][1:]
    assert identity_window_checkpoint(shape,descriptors,source,payload,shape['previous_window'],recent_turns=2,evict_turns=1)[0]is True
    payload['messages'].insert(0,{'role':'user','content':'old source'})
    assert identity_window_checkpoint(shape,descriptors,source,payload,shape['previous_window'],recent_turns=2,evict_turns=1)[0]is False


def test_wrong_batch_wrong_message_and_missing_native_identity_are_distinct():
    shape,descriptors,source,payload,metadata=fixture()
    changed=deepcopy(metadata);changed['pending'][0]['candidate_event_ids']=['1']
    assert identity_window_checkpoint(shape,descriptors,source,payload,changed,recent_turns=2,evict_turns=1)[0]is False
    payload['messages'][2]['content']='changed source'
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is False
    descriptors[2]['entry_id']=None
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is None
    shape['unsupported_lifecycle']=True
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is None


def test_tool_result_is_indivisible_and_wrong_or_missing_pair_never_passes():
    shape,descriptors,source,payload,_=fixture()
    shape['messages'][1]['calls']=['c']
    shape['messages'].insert(2,{'id':'r','role':'toolResult','calls':[],'result_id':'c','sha256':'r'})
    source[1]['content']=[{'type':'toolCall','id':'c','name':'read','arguments':{'path':'a'}}]
    source.insert(2,{'role':'toolResult','toolCallId':'c','content':[{'type':'text','text':'result'}]})
    descriptors.insert(2,{'entry_id':'r','sha256':'r'})
    payload['messages'][1]={'role':'assistant','content':'','tool_calls':[{'id':'c','function':{'name':'read','arguments':'{"path":"a"}'}}]}
    payload['messages'].insert(2,{'role':'tool','tool_call_id':'c','content':'result'})
    _,metadata=identity_selection(shape,recent_turns=2,evict_turns=1)
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is True
    payload['messages'][2]['tool_call_id']='foreign'
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is False
    shape['messages'][2]['result_id']='foreign'
    assert identity_window_checkpoint(shape,descriptors,source,payload,metadata,recent_turns=2,evict_turns=1)[0]is False
