import pytest

from memweave_eval.behavior_metrics import evaluate_behavior


def run(case, observation):
    return evaluate_behavior({"version": "test-v1", "cases": [case]}, {case["id"]: observation})


def test_retrieval_limits_best_subset_and_deduplication():
    case = {"id": "q", "kind": "retrieval", "k": 3, "relevant": ["a", "b"], "best": ["a"]}
    result = run(case, {"limit": 3, "candidates": ["b", "b", "a"], "complete": True})
    assert result["metrics"]["hit_at_k"]["value"] == 1
    assert result["metrics"]["recall_at_k"]["value"] == 1
    assert result["metrics"]["best_top1"]["value"] == 0
    assert result["metrics"]["top1_given_best_hit"]["denominator"] == 1
    assert result["metrics"]["top1_given_best_hit"]["value"] == 0
    short = run(case, {"limit": 2, "candidates": ["a"], "complete": True})
    assert short["metrics"]["hit_at_k"]["value"] is None
    assert short["metrics"]["hit_at_k"]["unknown"] == 1
    empty = run(case, {"limit": 3, "candidates": [], "complete": True, "error": True})
    assert empty["metrics"]["hit_at_k"]["value"] == 0
    assert empty["metrics"]["top1_given_best_hit"]["value"] is None


def test_restore_keeps_missed_intents_and_does_not_require_search():
    cases = [{"id": str(i), "kind": "restore", "targets": ["a"]} for i in range(3)]
    evidence = {
        "0": {"complete": True, "bound": "a", "request_current": True, "action_passed": True},
        "1": {"complete": True, "bound": None, "request_current": False, "action_passed": False},
        "2": {"complete": False},
    }
    result = evaluate_behavior({"version": "v", "cases": cases}, evidence)
    metric = result["metrics"]["restore_end_to_end"]
    assert metric["numerator"] == 1 and metric["denominator"] == 2 and metric["unknown"] == 1
    assert result["metrics"]["restore_after_binding"]["value"] == 1


def test_known_wrong_restore_is_failure_even_if_followup_action_evidence_missing():
    result=run({'id':'restore','kind':'restore','targets':['correct']},
        {'complete':True,'bound':'wrong','request_current':None,'action_passed':None})
    assert result['metrics']['restore_end_to_end']['value']==0
    assert result['metrics']['restore_after_binding']['not_applicable']==1


@pytest.mark.parametrize('returned,expected',[(True,1),(False,0),(None,None)])
def test_simple_interruption_can_require_a_separate_real_return_action(returned,expected):
    result=run({'id':'s','kind':'route','allowed':['continue'],'simple':True,'return_opportunity_id':'return'},
        {'complete':True,'route':'continue','created_ids':[],'create_attempts':0,
            'answer_passed':True,'protected_unchanged':True,'return_action_passed':returned})
    assert result['cases'][0]['value']==expected


@pytest.mark.parametrize(
    "created,answer,expected", [([], True, 1), ([], False, 0), (["new"], True, 0)]
)
def test_simple_requires_completion_and_no_persistent_creation(created, answer, expected):
    result = run(
        {
            "id": "s",
            "kind": "route",
            "allowed": ["no-persistent-task", "continue"],
            "simple": True,
            "must_create": False,
        },
        {
            "complete": True,
            "route": "continue",
            "created_ids": created,
            "create_attempts": 1,
            "answer_passed": answer,
            "protected_unchanged": True,
        },
    )
    assert result["metrics"]["simple_no_create_and_complete"]["value"] == expected
    assert result["metrics"]["unnecessary_create_attempt"]["value"] == 1


def test_create_retries_unique_objects_deadline_and_scope():
    case = {"id": "c", "kind": "route", "allowed": ["create"], "must_create": True}
    good = {
        "complete": True,
        "route": "create",
        "created_ids": ["a", "a"],
        "bound": "a",
        "goal_scope_correct": True,
        "before_deadline": True,
    }
    result = run(case, good)
    assert result["metrics"]["create_precision"]["value"] == 1
    assert result["metrics"]["create_recall"]["value"] == 1
    bad = run(case, dict(good, created_ids=["a", "b"]))
    assert bad["metrics"]["extra_created_objects"]["numerator"] == 1
    assert bad["metrics"]["create_precision"]["value"] == 0


def test_binary_assertions_require_evidence_and_missing_is_unknown():
    case = {
        "id": "c5",
        "kind": "checkpoint",
        "assertions": ["old_inactive", "new_current", "action_B"],
    }
    good = {key: {"value": True, "evidence_ids": ["commit:1"]} for key in case["assertions"]}
    assert run(case, good)["cases"][0]["value"] == 1
    assert (
        run(case, dict(good, action_B={"value": False, "evidence_ids": ["action:2"]}))["cases"][0][
            "value"
        ]
        == 0
    )
    assert (
        run(case, dict(good, new_current={"value": True, "evidence_ids": []}))["cases"][0]["value"]
        is None
    )
    assert run(case, {})["cases"][0]["status"] == "unknown"


def test_empty_gold_does_not_report_perfect_behavior():
    assert evaluate_behavior({"version": "v", "cases": []}, {})["metrics"] == {}


def test_route_case_cannot_pass_when_mandatory_subchecks_fail_or_are_missing():
    case = {"id": "s", "kind": "route", "allowed": ["continue"], "simple": True}
    known = {
        "complete": True,
        "route": "continue",
        "created_ids": [],
        "answer_passed": False,
        "protected_unchanged": True,
    }
    assert run(case, known)["cases"][0]["value"] == 0
    missing = dict(known, answer_passed=True)
    del missing["created_ids"]
    assert run(case, missing)["cases"][0]["value"] is None
    create = {"id": "n", "kind": "route", "allowed": ["create", "continue"], "must_create": True}
    assert (
        run(create, {"complete": True, "route": "continue", "created_ids": []})["cases"][0]["value"]
        == 0
    )


def test_trigger_absence_is_explicit_na_with_reason():
    case = {"id": "c", "kind": "checkpoint", "assertions": ["evicted"]}
    result = run(case, {"applicable": False, "reason": "source never left actual request"})
    assert result["cases"][0]["status"] == "not_applicable"
    assert result["cases"][0]["reason"] == "source never left actual request"


def test_null_deadline_is_unknown_not_a_known_create_failure():
    case = {"id": "c", "kind": "route", "allowed": ["create"], "must_create": True}
    result = run(
        case,
        {
            "complete": True,
            "route": "create",
            "created_ids": ["a"],
            "bound": "a",
            "goal_scope_correct": True,
            "before_deadline": None,
        },
    )
    assert result["metrics"]["create_recall"]["value"] is None
    assert result["cases"][0]["value"] is None
