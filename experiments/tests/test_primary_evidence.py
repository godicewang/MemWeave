import json

from memweave_eval.primary_evidence import collect_arm


def write(path,rows):path.write_text(''.join(json.dumps(r)+'\n'for r in rows))


def test_explicit_tool_error_pending_and_duplicate_receipt(tmp_path):
    a=tmp_path/'agent';a.mkdir();write(a/'pi.txt',[
        {'type':'tool_execution_start','toolCallId':'one','toolName':'bash'},
        {'type':'tool_execution_end','toolCallId':'one','toolName':'bash','isError':False},
        {'type':'tool_execution_start','toolCallId':'two','toolName':'edit'},
        {'type':'tool_execution_end','toolCallId':'two','toolName':'edit','isError':True}])
    r=collect_arm(tmp_path,[]);m=r['metrics']['common_tool_rate'];assert m['raw']==.5 and m['support']=={'s':1,'f':1,'u':0,'n':2}
    with(a/'pi.txt').open('a')as f:f.write(json.dumps({'type':'tool_execution_start','toolCallId':'pending','toolName':'read'})+'\n')
    m=collect_arm(tmp_path,[])['metrics']['common_tool_rate'];assert m['status']=='missing'and m['support']['u']==1 and m['support']['n']==3
    with(a/'pi.txt').open('a')as f:f.write(json.dumps({'type':'tool_execution_end','toolCallId':'one','toolName':'bash','isError':False})+'\n')
    assert collect_arm(tmp_path,[])['metrics']['common_tool_rate']['status']=='invalid'


def trace():
    return [{'event':event,'request_id':'r',**extra}for event,extra in [
        ('budget_reserved',{}),('request_ready',{}),('http_attempt',{}),('http_response',{'status':200}),
        ('budget_settled',{'charge_usd':.1}),('request_end',{'settled':True,'stream_done':True,'usage':{'input':100,'output':20,'cache_hit':0}})]]


def test_full_stream_cost_and_explicit_zero_cache_are_observed(tmp_path):
    a=tmp_path/'agent';a.mkdir();write(a/'request-trace.jsonl',trace())
    r=collect_arm(tmp_path,[]);assert r['metrics']['service_complete_rate']['raw']==1
    assert r['metrics']['model_cost_usd']['raw']==.1 and r['cache']['input_cache_utilization']['value']==0
    write(a/'request-trace.jsonl',trace()+[trace()[-1]])
    assert collect_arm(tmp_path,[])['metrics']['model_cost_usd']['status']=='invalid'
    events=trace();events[-1]['usage']['cache_hit']=None;write(a/'request-trace.jsonl',events)
    cost=collect_arm(tmp_path,[])['metrics']['model_cost_usd'];assert cost['status']=='missing'and cost['raw']is None and cost['unknown_cache_requests']==1


def test_unknown_charge_is_not_released_or_replaced_with_zero(tmp_path):
    a=tmp_path/'agent';a.mkdir();write(a/'request-trace.jsonl',trace()[:3]+[{'event':'http_error','request_id':'r','error_class':'TypeError'}])
    r=collect_arm(tmp_path,[]);assert r['metrics']['service_complete_rate']['raw']==0
    assert r['metrics']['model_cost_usd']['raw']is None and r['transport']['unsettled_request_ids']==['r']
    write(a/'request-trace.jsonl',trace()[:3]);assert collect_arm(tmp_path,[])['metrics']['service_complete_rate']['status']=='missing'
    with(a/'request-trace.jsonl').open('a')as f:f.write('{"truncated":')
    assert collect_arm(tmp_path,[])['metrics']['service_complete_rate']['status']=='invalid'


def test_absence_zero_opportunities_and_out_of_order_are_not_perfect(tmp_path):
    r=collect_arm(tmp_path,[]);assert r['metrics']['common_tool_rate']['status']=='missing'
    a=tmp_path/'agent';a.mkdir();write(a/'pi.txt',[]);write(a/'request-trace.jsonl',[])
    r=collect_arm(tmp_path,[]);assert r['metrics']['common_tool_rate']['status']=='not_comparable'
    assert r['metrics']['service_complete_rate']['status']=='not_comparable'
    events=trace();events[0],events[2]=events[2],events[0];write(a/'request-trace.jsonl',events)
    assert collect_arm(tmp_path,[])['metrics']['model_cost_usd']['status']=='invalid'
