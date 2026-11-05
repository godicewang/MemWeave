import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from memweave_eval.budget_guard import change, initialize


def test_shared_admission_reserves_inflight_and_unknown(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 1.0, 2000)

    def reserve(i):
        try:
            return change(path, {"action": "reserve", "id": str(i), "max_output": 384000}, now=1000)
        except ValueError:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(r is not None for r in results) == 1
    ledger = json.loads(path.read_text())
    assert ledger["exposure_usd"] == pytest.approx(0.7753728)
    identity = next(iter(ledger["requests"]))
    change(path, {"action": "settle", "id": identity, "input": 10000, "output": 1000}, now=1001)
    assert json.loads(path.read_text())["exposure_usd"] == pytest.approx(0.0042)
    reserve("next")
    assert json.loads(path.read_text())["exposure_usd"] < 1


def test_replay_deadline_and_invalid_usage_fail_closed(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 29.0, 2000)
    op = {"action": "reserve", "id": "a", "max_output": 1000}
    change(path, op, now=1000)
    with pytest.raises(ValueError):
        change(path, op, now=1000)
    with pytest.raises(ValueError):
        change(path, dict(op, id="b"), now=2000)
    with pytest.raises(ValueError):
        change(path, {"action": "settle", "id": "a", "input": -1, "output": 0}, now=1001)
    assert json.loads(path.read_text())["exposure_usd"] == pytest.approx(0.3157728)
    settle = {"action": "settle", "id": "a", "input": 10, "output": 2}
    change(path, settle, now=1001)
    before = path.read_bytes()
    change(path, settle, now=1002)
    assert before == path.read_bytes()


def test_usage_cannot_refund_after_inconsistent_bill(tmp_path):
    path = tmp_path / "quota.json"
    initialize(path, 29.0, 2000)
    change(path, {"action": "reserve", "id": "a", "max_output": 1000}, now=1000)
    with pytest.raises(ValueError):
        change(path, {"action": "settle", "id": "a", "input": 1048577, "output": 1}, now=1001)
    assert json.loads(path.read_text())["requests"]["a"]["status"] == "reserved"


def test_distinct_processes_share_flock_admission(tmp_path):
    import subprocess
    import sys
    import time
    from pathlib import Path

    script = Path(__file__).parents[1] / "src/memweave_eval/budget_guard.py"
    path = tmp_path / "quota.json"
    initialize(path, 1.0, time.time() + 60)
    processes = []
    for i in range(2):
        process = subprocess.Popen(
            [sys.executable, str(script), str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        process.stdin.write(json.dumps({"action": "reserve", "id": str(i), "max_output": 384000}))
        process.stdin.close()
        processes.append(process)
    for process in processes:
        process.wait(timeout=5)
    assert sorted(p.returncode for p in processes) == [0, 2]
    assert len(json.loads(path.read_text())["requests"]) == 1
