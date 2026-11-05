"""Each flow component is independently falsifiable; fixtures are not model scores."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_tb01_capsules import fixture

from memweave_eval.tb01_flow_v2 import collect_flow_v2
from memweave_eval.tool_outcomes import tool_contract_metric


def prepared(tmp_path, variant):
    trace, save = fixture(tmp_path, variant)
    session = []
    for e in trace:
        if e.get('event') != 'request_ready':
            continue
        d = e['capsule_deliveries'][0]
        body = (json.dumps({'task_id': 'task_one', 'state_version': 4, 'items': [
            {'id': f'F{i}', 'content': json.dumps(v)} for i, v in enumerate(d['values'], 1)]})
            if variant == 'pi-memweave' else '\n'.join(json.dumps(v) for v in d['values'])+'\n')
        identity = d['tool_call_id']
        digest = hashlib.sha256(json.dumps({'role': 'tool', 'content': body, 'tool_call_id': identity},
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        d['message_sha256'] = digest
        e['messages'] = [{'role': 'tool', 'tool_call_id': identity, 'sha256': digest}]
        session.append({'id': identity, 'message': {'role': 'toolResult', 'toolName': 'state_read' if variant == 'pi-memweave' else 'read',
            'toolCallId': identity, 'isError': False, 'content': [{'type': 'text', 'text': body}]}})
        e['memory_state_deliveries'] = []
        if variant == 'pi-memweave':
            previous = trace[trace.index(e)-1]['state_boundary']
            e.update(previous)
            e['state_blocks'] = [{'task_id': 'task_one', 'version': 4, 'sha256': 'a' * 64}]
            e['memory_state_deliveries'] = [{'task_id': 'task_one', 'state_version': 4,
                'body_sha256': 'a' * 64, 'values': copy.deepcopy(e['capsule_deliveries'][0]['values'])}]
    save()
    p = tmp_path/'agent/pi/sessions'
    p.mkdir(parents=True)
    (p/'session.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in session))
    return trace, save


@pytest.mark.parametrize('variant', ['pi-native', 'pi-memweave'])
def test_separate_components_pass(tmp_path, variant):
    prepared(tmp_path, variant)
    result = collect_flow_v2(tmp_path, variant)
    assert result['complete'] and set(result['assertions'].values()) == {'pass'}


def test_auto_state_counts_without_any_explicit_read(tmp_path):
    trace, save = prepared(tmp_path, 'pi-memweave')
    # Keep valid tool boundaries but turn read calls into ordinary diagnostics.
    pi = tmp_path / 'agent/pi.txt'
    events = [json.loads(x) for x in pi.read_text().splitlines()]
    for e in events:
        if e.get('toolName') == 'state_read':
            e['toolName'] = 'bash'
    for e in trace:
        if e.get('tool_name') == 'state_read':
            e['tool_name'] = 'bash'
        if e.get('event') == 'request_ready':
            e['capsule_deliveries'] = []
    save()
    pi.write_text(''.join(json.dumps(e) + '\n' for e in events))
    result = collect_flow_v2(tmp_path, 'pi-memweave')
    assert result['complete'] and set(result['assertions'].values()) == {'pass'}


@pytest.mark.parametrize('variant', ['pi-native', 'pi-memweave'])
def test_missing_delivery_never_repeats_capture_or_business_failure(tmp_path, variant):
    trace, save = prepared(tmp_path, variant)
    for e in trace:
        if e.get('event') == 'request_ready':
            e['capsule_deliveries'] = []
            e['memory_state_deliveries'] = []
            e['state_blocks'] = []
            e['messages'] = []
    save()
    result = collect_flow_v2(tmp_path, variant)
    assert result['complete']
    for key, status in result['assertions'].items():
        assert status == ('fail' if ':delivery:' in key else 'pass')


@pytest.mark.parametrize('variant', ['pi-native', 'pi-memweave'])
def test_business_failure_does_not_revoke_capture_or_delivery(tmp_path, variant):
    prepared(tmp_path, variant)
    p = tmp_path / 'verifier/derived-ctrf.json'
    d = json.loads(p.read_text())
    d['results']['tests'][0]['status'] = 'failed'
    p.write_text(json.dumps(d))
    result = collect_flow_v2(tmp_path, variant)
    failed = [k for k, v in result['assertions'].items() if v == 'fail']
    assert failed == ['flow:row:behavior:probe1']


@pytest.mark.parametrize('variant', ['pi-native', 'pi-memweave'])
def test_absent_required_v2_projection_is_missing(tmp_path, variant):
    trace, save = prepared(tmp_path, variant)
    del next(e for e in trace if e.get('event') == 'request_ready')['memory_state_deliveries']
    save()
    result = collect_flow_v2(tmp_path, variant)
    assert not result['complete'] and 'flow_delivery_projection_missing' in result['issues']
    assert all(v == 'missing' for k, v in result['assertions'].items() if ':delivery:' in k)


def test_empty_parser_summary_cannot_misgrade_a_real_delivered_read(tmp_path):
    trace, save = prepared(tmp_path, 'pi-native')
    for e in trace:
        if e.get('event') == 'request_ready':
            e['capsule_deliveries'] = []
    save()
    result = collect_flow_v2(tmp_path, 'pi-native')
    assert not result['complete'] and 'flow_read_summary_disagrees_with_original' in result['issues']


def test_lost_automatic_projection_is_missing_not_failure(tmp_path):
    trace, save = prepared(tmp_path, 'pi-memweave')
    for e in trace:
        if e.get('event') == 'request_ready':
            e['memory_state_deliveries'] = []
    save()
    result = collect_flow_v2(tmp_path, 'pi-memweave')
    assert not result['complete'] and 'flow_delivery_projection_missing' in result['issues']


@pytest.mark.parametrize('variant', ['pi-native', 'pi-memweave'])
@pytest.mark.parametrize('key', ['row', 'pmi', 'stop'])
def test_each_capture_truth_opportunity_has_wrong_value_control(tmp_path, variant, key):
    trace, save = prepared(tmp_path, variant)
    edit = next(e for e in trace if e.get('phase') == 'tool_start' and e.get('call_id') == 'edit')
    if variant == 'pi-native':
        for v in edit['workspace']['memory_capsules']['values']:
            if v['k'] == key:
                v['s'] = 'wrong-scope'
    else:
        # A valid older committed prefix lacks the required proposition.
        first = trace[0]['state_boundary']
        edit['state_boundary'] = dict(first)
    save()
    result = collect_flow_v2(tmp_path, variant)
    assert result['complete']
    assert result['assertions'][f'flow:{key}:capture:values'] == 'fail'
    assert all(v == 'pass' for k, v in result['assertions'].items() if ':behavior:' in k)


@pytest.mark.parametrize('key', ['row', 'pmi', 'stop'])
@pytest.mark.parametrize('n', [1, 2])
@pytest.mark.parametrize('status', ['failed', 'absent'])
def test_each_business_leaf_fail_and_missing(tmp_path, key, n, status):
    prepared(tmp_path, 'pi-memweave')
    p = tmp_path/'verifier/derived-ctrf.json'
    data = json.loads(p.read_text())
    name = f'tb01_capsule_actions.py::test_{key}_{n}'
    if status == 'failed':
        next(r for r in data['results']['tests'] if r['name'] == name)['status'] = status
    else:
        data['results']['tests'] = [r for r in data['results']['tests'] if r['name'] != name]
    p.write_text(json.dumps(data))
    result = collect_flow_v2(tmp_path, 'pi-memweave')
    assert result['assertions'][f'flow:{key}:behavior:probe{n}'] == ('fail' if status == 'failed' else 'missing')
    assert all(v == 'pass' for k, v in result['assertions'].items() if ':behavior:' not in k)


def ends(error=False, exit_code=0, result=None):
    return [{'type': 'tool_execution_start', 'toolCallId': 'one', 'toolName': 'bash'},
        {'type': 'tool_execution_end', 'toolCallId': 'one', 'toolName': 'bash', 'isError': error,
         'result': result if result is not None else {'content': [{'type': 'text', 'text': 'AssertionError' if error else 'ok'}],
             'structuredContent': {'output': 'AssertionError' if error else 'ok', 'exit_code': exit_code}}}]


@pytest.mark.parametrize('error,exit_code,category', [(False, 0, 'success'),
    (True, 1, 'business_assertion_failure'), (True, 127, 'environment_missing_dependency')])
def test_action_failure_is_not_malformed_tool_contract(error, exit_code, category):
    result = tool_contract_metric(ends(error, exit_code), 'observed')
    assert result['metric']['raw'] == 1
    assert result['calls'][0]['outcome_category'] == category


def test_explicit_bad_tool_result_fails_contract():
    result = tool_contract_metric(ends(result={'content': 'not-an-array'}), 'observed')
    assert result['metric']['raw'] == 0 and result['metric']['support']['f'] == 1


def test_missing_tool_receipt_is_collection_gap():
    result = tool_contract_metric(ends()[:1], 'observed')
    assert result['metric']['raw'] is None and result['metric']['status'] == 'missing'


def test_tool_receipts_require_matching_original_session():
    result = tool_contract_metric(ends(), 'observed', sessions=[])
    assert result['metric']['raw'] is None and result['source_issue'] == 'original_session_call_result_set_mismatch'


@pytest.mark.parametrize('missing_delivery', [False, True])
def test_v2_report_and_zero_weight_collection_gate(tmp_path, monkeypatch, missing_delivery):
    import memweave_eval.primary_evidence as evidence
    from memweave_eval.primary_report import score_run
    from memweave_eval.storage import evidence_index, file_digest

    contract = json.loads((Path(__file__).parents[1]/'cases/TB-01/1.5.0/scoring.json').read_text())
    (tmp_path/'primary-case.json').write_text(json.dumps(contract))
    rows = []
    for variant in ('pi-native', 'pi-memweave'):
        trial = tmp_path/'harbor'/variant/'trial'
        trial.mkdir(parents=True)
        trace, save = prepared(trial, variant)
        if missing_delivery:
            del next(e for e in trace if e.get('event') == 'request_ready')['memory_state_deliveries']
            save()
        (trial/'result.json').write_text('{}')
        rows.append({'variant_id': variant, 'task_id': 'batched-eval-parity',
                     'score_source': str((trial/'result.json').relative_to(tmp_path))})
    def collected(*args, **kwargs):
        return {'metrics': {k: {'raw': 1, 'status': 'observed'} for k in (
            'tool_contract_complete_rate', 'service_complete_rate', 'model_cost_usd', 'actor_wall_seconds')},
            'assertions': {}, 'parse_issues': [], 'sources': {}, 'transport_integrity': {'status': 'observed'}}
    monkeypatch.setattr(evidence, 'collect_arm', collected)
    (tmp_path/'evidence-index.json').write_text(json.dumps({'files': evidence_index(tmp_path)}))
    result = score_run(tmp_path, {'run_id': 'fixture', 'primary_case_sha256': file_digest(tmp_path/'primary-case.json')}, rows)
    assert result['engineering']['total']['score'] == 50
    assert result['measurement_acceptance']['status'] == ('blocked_missing_evidence' if missing_delivery else 'complete')
    assert all(v['total']['score'] == (None if missing_delivery else 100) for v in result['behavior'].values())


def test_v2_payload_excludes_goal_from_automatic_capsules():
    import subprocess
    module = (Path(__file__).parents[1]/'src/memweave_eval/fetch_guard.mjs').as_uri()
    body = '# Symbolic State\n\ntask_id: task_one\nstate_version: 1\n\n## Goal\n'+json.dumps({'k': 'row'})+'\n\n## Facts\n\n## Decisions\n'
    script = ('import {requestSummary} from '+json.dumps(module)+';process.env.MEMWEAVE_EVAL_WORKSPACE=JSON.stringify({memory_protocol:"tb01-capsule.v2"});'
        'console.log(JSON.stringify(requestSummary('+json.dumps({'messages': [{'role': 'user', 'content': body}]})+',null)));')
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value['memory_state_deliveries'][0]['values'] == []
    assert value['memory_state_deliveries'][0]['state_version'] == 1


@pytest.mark.parametrize('field,value', [('memory_state_deliveries', None), ('memory_state_deliveries', [None]),
    ('capsule_deliveries', None), ('capsule_deliveries', [None]), ('state_blocks', None), ('state_blocks', [None])])
def test_malformed_required_delivery_projection_is_missing(tmp_path, field, value):
    trace, save = prepared(tmp_path, 'pi-memweave')
    next(e for e in trace if e.get('event') == 'request_ready')[field] = value
    save()
    result = collect_flow_v2(tmp_path, 'pi-memweave')
    assert not result['complete']
    assert all(v == 'missing' for k, v in result['assertions'].items() if ':delivery:' in k)


def test_corrupt_journal_blocks_instead_of_failing_or_crashing(tmp_path):
    prepared(tmp_path, 'pi-memweave')
    (tmp_path/'agent/memory.tar.gz').write_text('truncated archive')
    result = collect_flow_v2(tmp_path, 'pi-memweave')
    assert not result['complete'] and 'flow_journal_invalid' in result['issues']
