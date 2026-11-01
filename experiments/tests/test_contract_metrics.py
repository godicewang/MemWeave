import pytest

from memweave_eval.contract_metrics import (
    logical_operation_metrics,
    reference_integrity,
    state_freshness,
    window_integrity,
)


def test_recovery_requires_explicit_identity_and_external_state():
    events = [
        {"type": "tool_execution_end", "toolCallId": "a", "evaluation_operation_id": "op",
         "sequence": 1, "isError": True, "durationMs": 3},
        {"type": "tool_execution_end", "toolCallId": "b", "evaluation_operation_id": "op",
         "sequence": 2, "isError": False, "durationMs": 4,
         "evaluation_state": {"hash": "B"}},
    ]
    metadata = {"op": {"recoverable": True, "retry_budget": 1, "deadline_seq": 5,
                       "observed_through_seq": 5, "expected_state": {"hash": "B"}}}
    result = logical_operation_metrics(events, metadata)
    assert result["recovery"]["value"] == 1
    assert result["retry_load"]["value"] == 0.5
    assert result["retry_duration_ms"] == 4
    assert logical_operation_metrics(events + [events[-1]], metadata) == result
    start = dict(events[0], type='tool_execution_start', arguments={'must_not_affect_identity':True})
    receipt = dict(events[0])
    del receipt['evaluation_operation_id']
    replay = logical_operation_metrics([start, receipt, receipt], metadata)
    assert replay['mapped_attempts'] == 1 and replay['mapping_coverage'] == 1
    del events[-1]["evaluation_state"]
    assert logical_operation_metrics(events, metadata)["recovery"]["value"] is None
    metadata["op"]["final_state"] = {"hash": "wrong"}
    assert logical_operation_metrics(events, metadata)["recovery"]["value"] == 0
    for e in events:
        del e["evaluation_operation_id"]
    result = logical_operation_metrics(events, metadata)
    assert result["retry_load"]["value"] is None
    assert result["mapping_coverage"] == 0


def test_recovery_cutoff_retry_budget_and_unrecoverable_are_distinct():
    event = {"type": "tool_execution_end", "toolCallId": "a", "evaluation_operation_id": "op",
             "sequence": 1, "isError": True}
    meta = {"op": {"recoverable": True, "retry_budget": 0, "deadline_seq": 5,
                   "observed_through_seq": 3, "expected_state": {"hash": "B"}}}
    assert logical_operation_metrics([event], meta)["recovery"]["unknown"] == 1
    meta["op"].update(observed_through_seq=5, final_state={"hash": "A"})
    assert logical_operation_metrics([event], meta)["recovery"]["value"] == 0
    meta["op"]["recoverable"] = False
    assert logical_operation_metrics([event], meta)["recovery"]["not_applicable"] == 1
    assert logical_operation_metrics([])["retry_load"]["status"] == "not_applicable"


def test_state_latest_requires_authoritative_prepare_boundary():
    commits = [{"task_id": "a", "version": 1, "sequence": 2},
               {"task_id": "a", "version": 2, "sequence": 8}]
    req = {"request_id": "r", "expected_task_id": "a", "prepare_seq": 5,
           "state_blocks": [{"task_id": "a", "version": 1}]}
    assert state_freshness(commits, [req], commits_complete=True)["value"] == 1
    req["prepare_seq"] = 9
    assert state_freshness(commits, [req], commits_complete=True)["value"] == 0
    req["state_blocks"] = [{"task_id": "b", "version": 2}]
    assert state_freshness(commits, [req], commits_complete=True)["value"] == 0
    assert state_freshness(commits, [req], commits_complete=False)["value"] is None
    del req["prepare_seq"]
    assert state_freshness(commits, [req], commits_complete=True)["value"] is None
    assert state_freshness([], [], enabled=False)["status"] == "not_applicable"


def test_reference_fidelity_checks_wrong_scope_version_hash_and_missing():
    gold = [{"read_id": "r", "ref_id": "T1", "scope_id": "a", "version": 2,
             "projection_sha256": "good"}]
    obs = [dict(gold[0], is_error=False, evidence_id="read:1")]
    assert reference_integrity(gold, obs)["value"] == 1
    for key, value in (("scope_id", "b"), ("version", 1), ("projection_sha256", "bad")):
        assert reference_integrity(gold, [dict(obs[0], **{key: value})])["value"] == 0
    assert reference_integrity(gold, [dict(obs[0], is_error=True)])["value"] == 0
    assert reference_integrity(gold, [])["value"] is None
    assert reference_integrity([], [])["status"] == "not_applicable"


def test_window_whole_event_pairing_projection_and_scope():
    messages = [
        {"event_id": "e", "scope_id": "a", "kind": "call", "call_id": "c", "sha256": "1"},
        {"event_id": "e", "scope_id": "a", "kind": "result", "call_id": "c", "sha256": "2"},
    ]
    gold = [{"window_id": "w", "messages": messages}]
    obs = [{"window_id": "w", "messages": messages, "complete": True}]
    assert window_integrity(gold, obs)["value"] == 1
    assert window_integrity(gold, [dict(obs[0], messages=messages[:1])])["value"] == 0
    assert window_integrity(gold, [dict(obs[0], messages=list(reversed(messages)))])["value"] == 0
    for key in ("scope_id", "sha256"):
        bad = [dict(messages[0], **{key: "wrong"}), messages[1]]
        assert window_integrity(gold, [dict(obs[0], messages=bad)])["value"] == 0
    assert window_integrity(gold, [])["value"] is None


def test_conflicting_resolution_and_incomplete_types_do_not_pass():
    g = {"read_id":"r","ref_id":"T1","scope_id":"a","version":1,"projection_sha256":"h"}
    a = dict(g, is_error=False)
    assert reference_integrity([g], [a, dict(a, projection_sha256='other')])['value'] is None
    assert reference_integrity([g], [dict(a, is_error='false')])['value'] is None
    assert reference_integrity([g], [dict(a, version=True)])['value'] is None
    with pytest.raises(ValueError):
        reference_integrity([g,g], [a])
    commits = [{'task_id':'a','version':1,'sequence':1}]
    req = {'request_id':'r','expected_task_id':'a','prepare_seq':2,
           'state_blocks':[{'task_id':'a','version':True}]}
    assert state_freshness(commits,[req],commits_complete=True)['value'] is None


def test_recovery_after_budget_or_deadline_does_not_count():
    first = {'type':'tool_execution_end','toolCallId':'a','evaluation_operation_id':'op',
             'sequence':1,'isError':True,'evaluation_state':{'hash':'A'}}
    late = dict(first, toolCallId='b', sequence=7, isError=False, evaluation_state={'hash':'B'})
    contract = {'op':{'recoverable':True,'retry_budget':1,'deadline_seq':5,
                     'observed_through_seq':9,'expected_state':{'hash':'B'},'final_state':{'hash':'A'}}}
    assert logical_operation_metrics([first,late],contract)['recovery']['value'] == 0
    late['sequence'] = 3
    contract['op']['retry_budget'] = 0
    assert logical_operation_metrics([first,late],contract)['recovery']['value'] == 0
    conflict = dict(first, evaluation_state={'hash':'B'})
    assert logical_operation_metrics([first,conflict],contract)['mapping_coverage'] == 0
