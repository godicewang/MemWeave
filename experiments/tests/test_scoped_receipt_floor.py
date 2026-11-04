import pytest


def fixture(version=3):
    r={'request_id':'r','state_blocks':[{'task_id':'t','version':version}]}
    p={'messages':[
        {'role':'assistant','tool_calls':[{'id':'same','function':{'name':'update_goal'}}]},
        {'role':'tool','tool_call_id':'same','content':'State updated: v2'},
        {'role':'assistant','tool_calls':[{'id':'same','function':{'name':'update_goal'}}]},
        {'role':'tool','tool_call_id':'same','content':'State updated: v3'}]}
    return r,p,{'same':{('t',2),('t',3)}}


@pytest.mark.parametrize('version,score',[(3,1),(2,0)])
def test_reused_tool_id_is_resolved_per_actual_provider_message(version,score):
    from memweave_eval.contract_evidence import request_receipt_floor
    r,p,receipts=fixture(version)
    result=request_receipt_floor([r],{'r':p},receipts,enabled=True)
    assert result['value']==score and result['unknown']==0


@pytest.mark.parametrize('mode',['missing-payload','unverified-version','unpaired-result','nonwrite-collision'])
def test_missing_or_wrong_receipt_identity_does_not_become_an_invented_dependency(mode):
    from memweave_eval.contract_evidence import request_receipt_floor
    r,p,receipts=fixture()
    if mode=='missing-payload':p=None
    elif mode=='unverified-version':p['messages'][3]['content']='State updated: v4'
    elif mode=='unpaired-result':p['messages']=p['messages'][1:2]
    else:
        for m in p['messages']:
            if m['role']=='assistant':m['tool_calls'][0]['function']['name']='read'
    result=request_receipt_floor([r],{'r':p},receipts,enabled=True)
    if mode=='nonwrite-collision':assert result['status']=='not_applicable'
    else:assert result['value']is None and result['unknown']==1
