import copy
import json
import subprocess
from pathlib import Path

import pytest
from test_tb01_flow_v2 import prepared

from memweave_eval.tb01_flow_v2 import collect_flow_context
from memweave_eval.tool_outcomes import tool_contract_metric


def fixture(tmp_path, kind='write_context'):
    trace, save = prepared(tmp_path, 'pi-native')
    for e in trace:
        if e.get('event') != 'request_ready':
            continue
        previous = trace[trace.index(e)-1]
        note = copy.deepcopy(previous['workspace']['memory_capsules'])
        e['workspace'] = {'memory_capsules': note}
        e['capsule_deliveries'] = []
        e['messages'] = [{'role': 'tool' if kind == 'tool_result' else 'assistant',
            'tool_calls': ['capture'] if kind in ('write_context', 'tool_arguments_context') else [],
            'tool_call_id': 'capture' if kind == 'tool_result' else None,
            'sha256': 'c'*64}]
        e['note_context_deliveries'] = [{'source_kind': kind, 'tool_call_id': None if kind == 'assistant_context' else 'capture',
            'message_sha256': 'c'*64, 'note_sha256': note['sha256'], 'values': note['values']}]
    save()
    return trace, save


@pytest.mark.parametrize('kind', ['write_context', 'tool_result', 'tool_arguments_context', 'assistant_context'])
def test_existing_record_available_without_read_name(tmp_path, kind):
    fixture(tmp_path, kind)
    result = collect_flow_context(tmp_path, 'pi-native')
    assert result['complete'] and set(result['assertions'].values()) == {'pass'}


@pytest.mark.parametrize('mutation', ['missing_field', 'wrong_hash', 'wrong_note', 'missing_message'])
def test_unproven_projection_is_collection_gap(tmp_path, mutation):
    trace, save = fixture(tmp_path)
    q = next(e for e in trace if e.get('event') == 'request_ready')
    if mutation == 'missing_field':
        del q['note_context_deliveries']
    elif mutation == 'wrong_hash':
        q['note_context_deliveries'][0]['message_sha256'] = 'd'*64
    elif mutation == 'wrong_note':
        q['note_context_deliveries'][0]['note_sha256'] = 'd'*64
    else:
        q['messages'] = []
    save()
    result = collect_flow_context(tmp_path, 'pi-native')
    assert not result['complete']
    assert all(v == 'missing' for k, v in result['assertions'].items() if ':delivery:' in k)


@pytest.mark.parametrize('mutation', ['not_visible', 'wrong_values'])
def test_real_non_delivery_is_observed_not_missing(tmp_path, mutation):
    trace, save = fixture(tmp_path)
    for e in trace:
        if e.get('event') == 'request_ready':
            if mutation == 'not_visible':
                e['note_context_deliveries'] = []
            else:
                for value in e['note_context_deliveries'][0]['values']:
                    value['s'] = 'wrong'
    save()
    result = collect_flow_context(tmp_path, 'pi-native')
    assert result['complete']
    assert all(v == 'fail' for k, v in result['assertions'].items() if ':delivery:' in k)


def test_actual_payload_projection_needs_visible_bytes_and_existing_note(tmp_path):
    module = (Path(__file__).parents[1]/'src/memweave_eval/fetch_guard.mjs').as_uri()
    note = tmp_path/'note.jsonl'
    body = '{"k":"row","by":"non_support_position","support":false,"ids":"repeat","s":"TB01"}\n'
    note.write_text(body)
    script = ('import {noteContextDeliveries} from '+json.dumps(module)+';const note='+json.dumps(str(note))+';'
        'const record='+json.dumps(body)+';const write={role:"assistant",tool_calls:[{id:"w",function:{name:"write",arguments:JSON.stringify({path:"/app/evalbench/memory_capsules.jsonl",content:record})}}]};'
        'const cat={role:"tool",tool_call_id:"c",content:record+"Command exited with code 1"};'
        'console.log(JSON.stringify([noteContextDeliveries([write,cat],note),noteContextDeliveries([{role:"tool",tool_call_id:"x",content:"no memory"}],note),noteContextDeliveries([write],note+".missing")]));')
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    values = json.loads(result.stdout)
    assert len(values[0]) == 2 and values[1:] == [[], []]


def test_actual_binding_gate_is_operation_rejection_not_failed_shell():
    from test_tb01_flow_v2 import ends

    events = ends(True, result={'content': [{'type': 'text', 'text':
        'TASK_BINDING_REQUIRED: bind a Task before business tools'}], 'details': {}})
    result = tool_contract_metric(events, 'observed')
    assert result['metric']['raw'] == 1
    assert result['calls'][0]['outcome_category'] == 'tool_operation_rejected'


def test_actual_bash_arguments_and_assistant_copy_are_also_visible_context(tmp_path):
    module = (Path(__file__).parents[1]/'src/memweave_eval/fetch_guard.mjs').as_uri()
    note = tmp_path/'note.jsonl'
    body = '{"k":"row","by":"non_support_position","support":false,"ids":"repeat","s":"TB01"}\n'
    note.write_text(body)
    script = ('import {noteContextDeliveries} from '+json.dumps(module)+';const body='+json.dumps(body)+';'
        'console.log(JSON.stringify(noteContextDeliveries([{role:"assistant",content:body},'
        '{role:"assistant",tool_calls:[{id:"bash-save",function:{name:"bash",arguments:JSON.stringify({command:"cat > /app/evalbench/memory_capsules.jsonl <<EOF\\n"+body+"EOF"})}}]}],'+json.dumps(str(note))+')));')
    p = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert {x['source_kind'] for x in json.loads(p.stdout)} == {'assistant_context', 'tool_arguments_context'}
