import copy

import pytest

from memweave_eval.case_oracles import score_case_suite


@pytest.mark.parametrize(
    "scenario",
    [
        "C1-retention",
        "C2-exception",
        "C3-intermediate",
        "C4-long-horizon",
        "C5-correction",
        "C6-scope",
        "C7-indirect",
        "C8-abstention",
    ],
)
def test_normalized_checkpoint_gold_negative_and_missing(scenario):
    fact = {"entity": "deploy", "value": "B", "unit": "ms", "negated": False, "scope": "project:v2"}
    case = {
        "id": scenario,
        "kind": "memory",
        "predicates": [
            {
                "name": "retained",
                "kind": "required_facts",
                "checkpoint": "after-eviction",
                "facts": [fact],
            },
            {
                "name": "old_inactive",
                "kind": "old_inactive",
                "checkpoint": "after-eviction",
                "old_ids": ["old"],
            },
            {
                "name": "used",
                "kind": "action_fields",
                "action_id": "deploy",
                "expected": {"value": "B", "scope": "project:v2"},
            },
            {
                "name": "timely",
                "kind": "before_boundary",
                "first": "write_seq",
                "second": "dependent_seq",
            },
            {"name": "eviction", "kind": "window_evicted", "source_id": "early"},
        ],
    }
    observation = {
        "snapshots": [
            {
                "checkpoint": "after-eviction",
                "complete": True,
                "facts": [dict(fact, id="new", active=True), dict(fact, id="old", active=False)],
                "evidence_ids": ["state:2"],
            }
        ],
        "actions": [
            {
                "id": "deploy",
                "complete": True,
                "value": "B",
                "scope": "project:v2",
                "evidence_ids": ["action:3"],
            }
        ],
        "write_seq": 1,
        "dependent_seq": 3,
        "sequence_evidence_ids": ["seq:1-3"],
        "original_event_ids": ["early"],
        "visible_event_ids": ["later"],
        "request_evidence_ids": ["request:4"],
    }
    gold = {"version": "controlled-v1", "cases": [case]}
    assert score_case_suite(gold, {scenario: observation})["cases"][0]["value"] == 1
    bad = copy.deepcopy(observation)
    bad["snapshots"][0]["facts"][0]["scope"] = "other-project"
    assert score_case_suite(gold, {scenario: bad})["cases"][0]["value"] == 0
    assert score_case_suite(gold, {})["cases"][0]["value"] is None


def test_clarification_and_false_adoption_negative_controls():
    case = {
        "id": "C8",
        "kind": "memory",
        "predicates": [
            {"name": "asked", "kind": "clarify_before_action"},
            {
                "name": "clean",
                "kind": "no_active_contradiction",
                "checkpoint": "c",
                "forbidden": [{"value": "guess"}],
            },
        ],
    }
    gold = {"version": "v", "cases": [case]}
    obs = {
        "clarification_complete": True,
        "clarify_seq": 1,
        "dependent_seq": 2,
        "sequence_evidence_ids": ["seq"],
        "snapshots": [
            {"checkpoint": "c", "complete": True, "facts": [], "evidence_ids": ["state"]}
        ],
    }
    assert score_case_suite(gold, {"C8": obs})["cases"][0]["value"] == 1
    obs["clarify_seq"] = 3
    assert score_case_suite(gold, {"C8": obs})["cases"][0]["value"] == 0
