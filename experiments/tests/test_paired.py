import threading
import time

import pytest

from memweave_eval.paired import ResourcePool, interleave, pair_weight


def test_pair_envelope_includes_grader_and_reserves():
    row = {
        "suite": "tb",
        "tier": "hard",
        "resources": {"cpus": 2, "memory_mb": 4096, "storage_mb": 4096},
        "verifier_resources": {"cpus": 1, "memory_mb": 4096, "storage_mb": 4096},
    }
    reserve = row | {"resources": {"cpus": 4, "memory_mb": 8192, "storage_mb": 10240}}
    assert pair_weight(row, {"reserves": [reserve]}) == (8, 16384, 20480)


def test_resource_pool_caps_ten_swe_solves_and_never_overbooks():
    pool = ResourcePool((12, 42000, 200000))
    for _ in range(5):
        pool.acquire((2, 8192, 20480), lambda: False)
    assert pool.used == [10, 40960, 102400]
    with pytest.raises(TimeoutError):
        pool.acquire((2, 8192, 20480), lambda: True)
    pool.release((2, 8192, 20480))
    assert pool.used == [8, 32768, 81920]
    with pytest.raises(ValueError):
        pool.acquire((14, 8192, 20480), lambda: False)


def test_resource_wait_wakes_and_cancel_does_not_leak_ticket():
    pool = ResourcePool((2, 8, 20))
    pool.acquire((2, 8, 20), lambda: False)
    result = []

    def work():
        pool.acquire((2, 8, 20), lambda: False)
        result.append(True)
        pool.release((2, 8, 20))

    thread = threading.Thread(target=work)
    thread.start()
    time.sleep(0.02)
    assert result == []
    pool.release((2, 8, 20))
    thread.join(timeout=2)
    assert result == [True]
    assert pool.used == [0, 0, 0]


def test_task_order_keeps_both_suites_and_every_slot_once():
    swe = [{"task_id": "s" + str(i)} for i in range(34)]
    tb = [{"task_id": "t" + str(i)} for i in range(14)]
    rows = interleave(swe, tb)
    assert len(rows) == 48
    assert len({r["task_id"] for r in rows}) == 48
    assert rows[:5] == swe[:5]
    assert rows[5] == tb[0]


def test_bootstrap_import_keeps_cost_deadline_and_rejects_unknown_cost(tmp_path, monkeypatch):

    from test_campaign import spec

    import memweave_eval.campaign_report as reports
    from memweave_eval.paired import bootstrap_info
    from memweave_eval.spec import REPOSITORY
    from memweave_eval.storage import atomic_json, file_digest

    s = spec(tmp_path)
    parent = s.root / "runs/parent"
    atomic_json(
        parent / "experiment.lock.json",
        {
            "phase": "bootstrap",
            "config": s.model_dump(mode="json"),
            "implementation_files": {
                "experiments/src/memweave_eval/" + n: file_digest(
                    REPOSITORY / "experiments/src/memweave_eval" / n
                )
                for n in ("pi_agent.py", "runtime_cache.py", "runner.py", "images.py")
            },
        },
    )
    atomic_json(
        parent / "run.json",
        {
            "window_started_at": "2026-10-28T10:48:39+00:00",
            "window_deadline_at": "2026-10-30T10:48:39+00:00",
        },
    )
    for name in ("live.json", "evidence-index.json"):
        atomic_json(parent / name, {})
    rows = [
        {
            "task_id": "first",
            "variant_id": v,
            "success": True,
            "solve_status": "completed_patch",
            "peak_estimated_cost_usd": 0.1,
            "session_diagnostics": {"model_responses_with_usage": 1},
        }
        for v in ("pi-native", "pi-memweave")
    ]
    summary = {"complete": True, "rows": rows, "estimated_known_cost_usd": 0.2}
    monkeypatch.setattr(reports, "generate_campaign_report", lambda _: summary)
    s.bootstrap_parent = parent
    info, old = bootstrap_info(s, {"selected": [{"task_id": "first"}]})
    assert info["known_cost_usd"] == 0.2
    assert info["window_deadline_at"] == "2026-10-30T10:48:39+00:00"
    assert len(old) == 2
    summary["estimated_known_cost_usd"] = float("nan")
    with pytest.raises(ValueError, match="cost"):
        bootstrap_info(s, {"selected": [{"task_id": "first"}]})
    summary["estimated_known_cost_usd"] = 0.2
    rows[1]["solve_status"] = "infrastructure_error"
    with pytest.raises(ValueError, match="healthy"):
        bootstrap_info(s, {"selected": [{"task_id": "first"}]})


def test_report_merges_completed_bootstrap_without_reducing_plan(tmp_path, monkeypatch):
    import memweave_eval.campaign_report as module
    from memweave_eval.report import normalize_trial
    from memweave_eval.storage import atomic_json

    root, parent = tmp_path / "runs/current", tmp_path / "runs/parent"

    def plan(task):
        return [
            {
                "task_id": task,
                "variant_id": v,
                "repetition": 1,
                "suite_id": "swe-bench-pro-v2",
                "tier": "simple",
                "display_id": task,
                "title": task,
            }
            for v in ("pi-native", "pi-memweave")
        ]

    old_plan, active = plan("first"), plan("second")
    old_rows = [
        normalize_trial(
            {
                "verifier_result": {"rewards": {"reward": 1}},
                "agent_result": {
                    "cost_usd": 0.1,
                    "n_input_tokens": 1,
                    "n_output_tokens": 1,
                    "n_cache_tokens": 0,
                },
            },
            p,
        )
        for p in old_plan
    ]
    for row in old_rows:
        row.update(
            actual_task_id=row["task_id"],
            actual_display_id=row["display_id"],
            actual_title=row["title"],
        )
    atomic_json(parent / "evidence-index.json", {"files": []})
    atomic_json(
        root / "experiment.lock.json",
        {
            "schema_version": 2,
            "run_id": "current",
            "phase": "full",
            "plan": active,
            "full_plan": old_plan + active,
            "bootstrap_lineage": {"parent": str(parent), "hashes": {}, "known_cost_usd": 0.2},
        },
    )
    atomic_json(root / "run.json", {"complete": False, "tasks": {}})
    atomic_json(root / "live.json", {"estimated_cost_usd": 0.3})
    atomic_json(root / "evidence-index.json", {"files": []})
    real = module.generate_campaign_report

    def generate(path):
        if path == parent:
            return {"complete": True, "run_id": "parent", "rows": old_rows}
        return real(path)

    monkeypatch.setattr(module, "generate_campaign_report", generate)
    report = real(root)
    assert len(report["rows"]) == 4
    assert report["overall_planned_model_trials"] == 4
    assert report["phase_planned_model_trials"] == 2
    assert report["estimated_known_cost_usd"] == pytest.approx(0.5)
    assert report["variants"]["pi-native"]["planned"] == 2
    assert report["variants"]["pi-native"]["scored"] == 1
    assert report["rows"][0]["origin_run_id"] == "parent"
