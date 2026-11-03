from copy import deepcopy

from memweave_eval.fixed35_window import small_window_checkpoint


def example():
    source=[{'role':'user','content':'Original required exception.'},
        {'role':'assistant','content':[{'type':'toolCall','id':'c','name':'read','arguments':{'path':'a'}}]},
        {'role':'toolResult','toolCallId':'c','content':[{'type':'text','text':'Actual result.'}]}]
    payload={'messages':[{'role':'system','content':'native + Rule'},
        {'role':'user','content':'[U1]\nOriginal required exception.'},
        {'role':'assistant','content':'[A1]','tool_calls':[{'id':'c','function':{'name':'read','arguments':'{"path":"a"}'}}]},
        {'role':'tool','tool_call_id':'c','content':'[T1]\nActual result.'},
        {'role':'user','content':'# Symbolic State\ncurrent'}]}
    return source,payload


def check(source,payload,**extra):
    return small_window_checkpoint(source,payload,recent_turns=200,enabled=True,**extra)


def test_whole_event_text_and_arguments_are_independent_required_checks():
    source,payload=example();assert check(source,payload)[0]is True
    mutations=[lambda p:p['messages'].pop(3),
        lambda p:p['messages'][3].update(tool_call_id='foreign'),
        lambda p:p['messages'][3].update(content='different result'),
        lambda p:p['messages'][3].update(content='[T1]\nActual result. Invented extra instruction.'),
        lambda p:p['messages'][2]['tool_calls'][0]['function'].update(arguments='{"path":"other"}'),
        lambda p:p['messages'].reverse()]
    for mutate in mutations:
        changed=deepcopy(payload);mutate(changed);assert check(source,changed)[0]is False


def test_missing_compaction_eviction_and_truncation_are_unknown_not_na_or_success():
    source,payload=example()
    assert check(None,payload)[0]is None
    assert check(source,payload,max_source_bytes=1)[0]is None
    assert small_window_checkpoint(source,payload,recent_turns=1,enabled=True)[0]is None
    changed=deepcopy(payload);changed['messages'][3]['content']='[TRUNCATED]'
    assert check(source,changed)[0]is None
    assert check(source+[{'role':'compactionSummary','content':'summary'}],payload)[0]is None
