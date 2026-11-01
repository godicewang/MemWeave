import json

import pytest

from memweave_eval.budget_guard import change, initialize
from memweave_eval.engineering_metrics import task_engineering_metrics


def test_workspace_only_trace_does_not_claim_zero_model_requests(tmp_path):
    (tmp_path / "request-trace.jsonl").write_text(
        json.dumps({"event": "workspace_checkpoint"}) + "\n"
    )
    result = task_engineering_metrics(tmp_path)
    assert result["http_attempts"] is None
    assert result["transport_source_status"] == "missing_guard_instrumentation"


def test_canary_request_limit_survives_settlement_and_new_process_identity(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 2.0, 2000)
    change(
        path,
        {
            "action": "reserve",
            "id": "first",
            "arm": "native",
            "episode": "canary",
            "max_requests": 1,
            "max_output": 128,
        },
        now=1000,
    )
    change(path, {"action": "settle", "id": "first", "input": 10, "output": 2}, now=1000)
    with pytest.raises(ValueError, match="request limit"):
        change(
            path,
            {
                "action": "reserve",
                "id": "second",
                "arm": "native",
                "episode": "canary",
                "max_requests": 1,
                "max_output": 128,
            },
            now=1000,
        )


def test_equal_episode_ceiling_is_independent_of_total_arm_headroom(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 2.0, 2000, arm_limits={"native": 1.5, "plugin": 1.5})
    change(
        path,
        {
            "action": "reserve",
            "id": "a",
            "arm": "native",
            "episode": "pair",
            "episode_budget": 0.4,
            "max_output": 1000,
        },
        now=1000,
    )
    with pytest.raises(ValueError, match="episode budget"):
        change(
            path,
            {
                "action": "reserve",
                "id": "b",
                "arm": "native",
                "episode": "pair",
                "episode_budget": 0.4,
                "max_output": 1000,
            },
            now=1000,
        )
    change(
        path,
        {
            "action": "reserve",
            "id": "c",
            "arm": "plugin",
            "episode": "pair",
            "episode_budget": 0.4,
            "max_output": 1000,
        },
        now=1000,
    )
