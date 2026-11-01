import json

import pytest

from memweave_eval.budget_guard import change, initialize


def test_equal_arm_caps_prevent_fast_arm_consuming_other_allocation(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 1.0, 2000, arm_limits={"native": 0.4, "plugin": 0.4})
    change(path, {"action": "reserve", "id": "n1", "arm": "native", "max_output": 1000}, now=1000)
    with pytest.raises(ValueError, match="arm"):
        change(
            path, {"action": "reserve", "id": "n2", "arm": "native", "max_output": 1000}, now=1000
        )
    change(path, {"action": "reserve", "id": "p1", "arm": "plugin", "max_output": 1000}, now=1000)
    assert len(json.loads(path.read_text())["requests"]) == 2
    with pytest.raises(ValueError):
        initialize(path, 1.0, 2000)


def test_confirmed_cache_usage_refunds_only_verified_tokens(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 1.0, 2000)
    change(path, {"action": "reserve", "id": "a", "max_output": 1000}, now=1000)
    change(
        path,
        {"action": "settle", "id": "a", "input": 1000000, "cache_input": 1000000, "output": 1},
        now=1000,
    )
    assert json.loads(path.read_text())["exposure_usd"] == pytest.approx(0.0060012)
    with pytest.raises(ValueError, match="conflicting"):
        change(
            path,
            {"action": "settle", "id": "a", "input": 1000000, "cache_input": 0, "output": 1},
            now=1000,
        )
