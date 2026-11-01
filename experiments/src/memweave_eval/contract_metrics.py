"""P0 mechanical contracts over explicit evaluator evidence, never guessed retries.

State event creation times are deliberately not accepted as commit boundaries.
These functions do not inspect arbitrary model text to infer business correctness.
"""

from __future__ import annotations

import math
from collections import defaultdict


def _item(identity, value=None, reason=None, *, na=False, evidence=None):
    return {"id": identity, "value": value, "status": "not_applicable" if na else
            "unknown" if value is None else "scored", "reason": reason,
            "evidence_ids": evidence or []}


def summarize(items, *, reason=None):
    known = [x for x in items if x["status"] == "scored"]
    unknown = sum(x["status"] == "unknown" for x in items)
    na = sum(x["status"] == "not_applicable" for x in items)
    return {"numerator": sum(x["value"] for x in known), "denominator": len(known),
            "unknown": unknown, "not_applicable": na,
            "value": sum(x["value"] for x in known) / len(known) if known else None,
            "coverage": len(known) / (len(known) + unknown) if known or unknown else None,
            "status": "partial" if known and unknown else "scored" if known else
            "unknown" if unknown else "not_applicable", "reason": reason, "items": items}


def _integer(value):
    return type(value) is int and value >= 0


def _matches(expected, observed):
    return isinstance(observed, dict) and all(observed.get(k) == v for k, v in expected.items())


def logical_operation_metrics(events, metadata=None):
    """Explicit operation IDs plus externally confirmed projections define recovery.

    metadata is evaluator-owned: recoverability, retry budget, deadline, observation
    cutoff and expected external projection. A success receipt alone is insufficient.
    """
    metadata = metadata or {}
    starts, attempts, conflicts = {}, {}, set()
    for seq, event in enumerate(events, 1):
        kind = event.get("type")
        key = (event.get("session_id"), event.get("toolCallId"))
        if kind == "tool_execution_start":
            starts[key] = event
        elif kind == "tool_execution_end":
            start = starts.pop(key, {})
            value = dict(event)
            operation = event.get('evaluation_operation_id', start.get('evaluation_operation_id',
                                  attempts.get(key, {}).get('evaluation_operation_id')))
            if operation is not None:
                value['evaluation_operation_id'] = operation
            value.setdefault("sequence", seq)
            if key in attempts and attempts[key] != value:
                # Ignore transport replay sequence when comparing the same receipt.
                a, b = dict(attempts[key]), dict(value)
                a.pop("sequence", None)
                b.pop("sequence", None)
                if a != b:
                    conflicts.add(key)
            else:
                attempts[key] = value
    for key, event in starts.items():
        attempts[key] = dict(event, isError=None)
    grouped = defaultdict(list)
    unmapped = 0
    for key, event in attempts.items():
        operation = event.get("evaluation_operation_id")
        if not isinstance(key[1], str) or not key[1] or not isinstance(operation, str) or not operation or key in conflicts:
            unmapped += 1
        else:
            grouped[operation].append(event)
    recovery, load, durations, costs = [], [], [], []
    for identity in sorted(set(grouped) | set(metadata)):
        values = grouped[identity]
        if not values or not all(_integer(v.get("sequence")) for v in values):
            recovery.append(_item(identity, reason="attempts_missing_or_unordered"))
            continue
        values.sort(key=lambda v: v["sequence"])
        for n, event in enumerate(values):
            load.append(_item(str(event.get("toolCallId")), n > 0))
            if n:
                duration, cost = event.get("durationMs"), event.get("evaluation_cost_usd")
                durations.append(duration if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0 else None)
                costs.append(cost if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0 else None)
        first, contract = values[0], metadata.get(identity, {})
        if first.get("isError") is False:
            recovery.append(_item(identity, reason="first_attempt_not_failed", na=True))
            continue
        if contract.get("recoverable") is False:
            recovery.append(_item(identity, reason="preregistered_unrecoverable", na=True))
            continue
        expected = contract.get("expected_state")
        deadline, cutoff, budget = (contract.get(k) for k in
                                    ("deadline_seq", "observed_through_seq", "retry_budget"))
        if (first.get("isError") is not True or contract.get("recoverable") is not True
                or not isinstance(expected, dict) or not expected
                or not all(_integer(v) for v in (deadline, cutoff, budget))):
            recovery.append(_item(identity, reason="recovery_contract_or_result_missing"))
            continue
        if deadline < first['sequence']:
            recovery.append(_item(identity, reason='deadline_precedes_operation'))
            continue
        if cutoff < deadline:
            recovery.append(_item(identity, reason="observation_cutoff_not_reached"))
            continue
        allowed = [v for n, v in enumerate(values) if n <= budget and v["sequence"] <= deadline]
        if any(_matches(expected, v.get("evaluation_state")) for v in allowed):
            recovery.append(_item(identity, True, evidence=[v["toolCallId"] for v in allowed]))
        elif isinstance(contract.get("final_state"), dict) and not _matches(expected, contract["final_state"]):
            recovery.append(_item(identity, False, "external_postcondition_not_met"))
        elif allowed and all(isinstance(v.get("evaluation_state"), dict) for v in allowed):
            recovery.append(_item(identity, False, "not_confirmed_within_retry_budget"))
        else:
            recovery.append(_item(identity, reason="external_state_or_confirmation_timing_unknown"))
    load.extend(_item(f"unmapped-{i}", reason="explicit_operation_identity_missing") for i in range(unmapped))
    recovery_summary = summarize(recovery)
    if attempts and not grouped:
        recovery_summary.update(status="unknown", reason="explicit_operation_identity_missing",
                                numerator=None, denominator=None, value=None)
    return {"raw_tool_attempts": len(attempts), "mapped_attempts": len(attempts)-unmapped,
            "mapping_coverage": (len(attempts)-unmapped)/len(attempts) if attempts else None,
            "logical_operations": len(grouped) if grouped else None if attempts else 0,
            "recovery": recovery_summary, "retry_load": summarize(load),
            "retry_duration_ms": sum(durations) if grouped and all(v is not None for v in durations) else None,
            "retry_cost_usd": sum(costs) if grouped and all(v is not None for v in costs) else None,
            "retry_duration_samples": sum(v is not None for v in durations),
            "retry_attempts": len(durations) if grouped else None if attempts else 0}


def state_freshness(commits, requests, *, commits_complete=False, enabled=True):
    if not enabled:
        return summarize([_item("scope", reason="State unavailable in native mode", na=True)])
    valid = all(isinstance(c.get("task_id"), str) and _integer(c.get("version")) and c['version'] > 0
                and _integer(c.get("sequence")) for c in commits)
    versions = {}
    for commit in commits:
        key = (commit.get('task_id'), commit.get('version'))
        if key in versions and versions[key] != commit.get('sequence'):
            valid = False
        versions[key] = commit.get('sequence')
    checks = []
    for request in requests:
        identity = request.get("request_id")
        task = request.get("expected_task_id")
        if "expected_task_id" in request and task is None:
            checks.append(_item(identity, reason="unbound_request", na=True))
        elif not valid or not commits_complete or not isinstance(task, str) or not _integer(request.get("prepare_seq")):
            checks.append(_item(identity, reason="authoritative_commit_or_prepare_boundary_missing"))
        elif not isinstance(request.get("state_blocks"), list):
            checks.append(_item(identity, reason="delivered_State_observation_missing"))
        elif any(not isinstance(b, dict) or not isinstance(b.get('task_id'), str)
                 or type(b.get('version')) is not int for b in request['state_blocks']):
            checks.append(_item(identity, reason='delivered_State_metadata_incomplete'))
        else:
            versions = [c["version"] for c in commits if c["task_id"] == task
                        and c["sequence"] <= request["prepare_seq"]]
            blocks = request["state_blocks"]
            correct = bool(versions) and len(blocks) == 1 and blocks[0].get("task_id") == task and blocks[0].get("version") == max(versions)
            checks.append(_item(identity, correct, None if correct else "State_version_or_scope_mismatch"))
    return summarize(checks)


def reference_integrity(gold, observations):
    if len({e['read_id'] for e in gold}) != len(gold):
        raise ValueError('duplicate reference gold opportunity')
    by_id, conflicts = {}, set()
    for observed in observations:
        identity = observed.get('read_id')
        if identity in by_id and by_id[identity] != observed:
            conflicts.add(identity)
        by_id[identity] = observed
    checks = []
    for expected in gold:
        identity = expected["read_id"]
        observed = by_id.get(identity)
        required = ("ref_id", "scope_id", "version", "projection_sha256")
        if identity in conflicts:
            checks.append(_item(identity, reason='conflicting_reference_observations'))
        elif not observed or type(observed.get("is_error")) is not bool:
            checks.append(_item(identity, reason="read_result_missing"))
        elif observed.get("is_error") is True:
            checks.append(_item(identity, False, "reference_read_failed"))
        elif (not all(isinstance(expected.get(k), str) and expected[k]
                      and isinstance(observed.get(k), str) and observed[k]
                      for k in ('ref_id', 'scope_id', 'projection_sha256'))
              or type(expected.get('version')) is not int or type(observed.get('version')) is not int):
            checks.append(_item(identity, reason="expected_or_actual_reference_projection_missing"))
        else:
            value = all(expected[k] == observed[k] for k in required)
            checks.append(_item(identity, value, None if value else "reference_scope_version_or_content_mismatch",
                                evidence=[observed.get("evidence_id")]))
    if not gold and observations:
        checks = [_item(o.get("read_id"), reason="reference_gold_missing") for o in observations]
    return summarize(checks, reason="no_reference_read_opportunities" if not gold and not observations else None)


def window_integrity(gold, observations):
    if len({e['window_id'] for e in gold}) != len(gold):
        raise ValueError('duplicate window gold opportunity')
    by_id, conflicts = {}, set()
    for observed in observations:
        identity = observed.get('window_id')
        if identity in by_id and by_id[identity] != observed:
            conflicts.add(identity)
        by_id[identity] = observed
    fields = ("event_id", "scope_id", "kind", "sha256")

    def project(message):
        return tuple(message.get(k) for k in (*fields, 'call_id'))

    checks = []
    for expected in gold:
        identity, observed = expected["window_id"], by_id.get(expected["window_id"])
        if identity in conflicts or not observed or observed.get("complete") is not True:
            checks.append(_item(identity, reason="window_observation_missing"))
            continue
        wanted, actual = expected.get("messages"), observed.get("messages")
        if not isinstance(wanted, list) or not isinstance(actual, list) or not all(
                isinstance(m, dict) and all(isinstance(m.get(k), str) and m[k] for k in fields)
                and m['kind'] in ('call', 'result', 'message', 'user', 'assistant')
                and (m.get("kind") not in ("call", "result") or isinstance(m.get("call_id"), str))
                for m in [*wanted, *actual]):
            checks.append(_item(identity, reason="event_projection_or_pair_metadata_missing"))
            continue
        same = [project(m) for m in wanted] == [project(m) for m in actual]
        calls, results, pairing = {}, set(), True
        pending = set(expected.get("allowed_pending_call_ids", []))
        for message in actual:
            call = message.get("call_id")
            if message["kind"] == "call":
                pairing &= call not in calls
                calls[call] = (message['event_id'], message['scope_id'])
            elif message["kind"] == "result":
                pairing &= call in calls and call not in results and calls[call] == (message['event_id'], message['scope_id'])
                results.add(call)
        pairing &= set(calls)-results <= pending
        checks.append(_item(identity, bool(same and pairing), None if same and pairing else
                            "event_pair_order_scope_or_projection_mismatch"))
    if not gold and observations:
        checks = [_item(o.get("window_id"), reason="expected_window_projection_missing") for o in observations]
    return summarize(checks)
