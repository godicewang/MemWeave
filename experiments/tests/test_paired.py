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


def test_warm_preflight_bypasses_cold_installer_lock(tmp_path, monkeypatch):
    import memweave_eval.paired as module

    monkeypatch.setattr(module, "software_cached", lambda *_: True)
    monkeypatch.setattr(module, "prepare_runtimes", lambda *args: "checked")
    lock = threading.Lock()
    lock.acquire()
    assert module.prepare_pair_runtimes(
        None, tmp_path, [], {}, lock, lambda: None, lambda: True, 1
    ) == "checked"
    lock.release()


def test_cold_preflight_serializes_and_checks_stop(tmp_path, monkeypatch):
    import memweave_eval.paired as module

    monkeypatch.setattr(module, "software_cached", lambda *_: False)
    monkeypatch.setattr(module, "software_writer_busy", lambda *_: False)
    lock = threading.Lock()
    calls = []

    def prepare(*args):
        assert lock.locked()
        calls.append(True)
        raise ValueError("failed installation")

    monkeypatch.setattr(module, "prepare_runtimes", prepare)
    with pytest.raises(ValueError, match="failed installation"):
        module.prepare_pair_runtimes(None, tmp_path, [], {}, lock, lambda: None, lambda: True, 1)
    assert not lock.locked()
    assert calls == [True]
    lock.acquire()

    def stop():
        raise TimeoutError("stop before another installation")

    with pytest.raises(TimeoutError, match="stop before"):
        module.prepare_pair_runtimes(None, tmp_path, [], {}, lock, stop, lambda: True, 1)
    lock.release()
    assert calls == [True]


def test_external_preparation_writer_is_observed_before_start(tmp_path, monkeypatch):
    import fcntl

    import memweave_eval.paired as module

    plan = {"cache": str(tmp_path), "entries": {"image": {
        k: {"key": k} for k in ("base", "addon", "models")
    }}}
    monkeypatch.setattr(module, "create_plan", lambda *_: plan)
    with (tmp_path / "addon.lock").open("a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert module.software_writer_busy(None, {})
    assert not module.software_writer_busy(None, {})


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
                for n in ("pi_agent.py", "runtime_cache.py", "runner.py", "images.py", "network_probe.py", "public_archive.py")
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


@pytest.mark.parametrize("completed", [False, True])
def test_report_merges_completed_bootstrap_without_reducing_plan(tmp_path, monkeypatch, completed):
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
        if completed:
            row.update(origin_run_id="grandparent", source_run_dir="/original/source")
    lineage = {"parent": str(parent), "hashes": {}, "known_cost_usd": 0.2}
    if completed:
        lineage.update(kind="completed_pairs", included_keys=[
            [r["task_id"], r["variant_id"]] for r in old_rows
        ])
    atomic_json(parent / "evidence-index.json", {"files": []})
    atomic_json(
        root / "experiment.lock.json",
        {
            "schema_version": 2,
            "run_id": "current",
            "phase": "full",
            "plan": active,
            "full_plan": old_plan + active,
            "bootstrap_lineage": lineage,
        },
    )
    atomic_json(root / "run.json", {"complete": False, "tasks": {}})
    atomic_json(root / "live.json", {"estimated_cost_usd": 0.3})
    atomic_json(root / "evidence-index.json", {"files": []})
    real = module.generate_campaign_report

    def generate(path):
        if path == parent:
            return {"complete": not completed, "run_id": "parent", "rows": old_rows,
                    "invalid_evidence": []}
        return real(path)

    monkeypatch.setattr(module, "generate_campaign_report", generate)
    report = real(root)
    assert len(report["rows"]) == 4
    assert report["overall_planned_model_trials"] == 4
    assert report["phase_planned_model_trials"] == 2
    assert report["estimated_known_cost_usd"] == pytest.approx(0.5)
    assert report["variants"]["pi-native"]["planned"] == 2
    assert report["variants"]["pi-native"]["scored"] == 1
    assert report["rows"][0]["origin_run_id"] == ("grandparent" if completed else "parent")
    if completed:
        assert report["rows"][0]["source_run_dir"] == "/original/source"


def test_completed_parent_keeps_all_started_pairs_and_first_zero_scores(tmp_path, monkeypatch):
    from test_campaign import spec

    import memweave_eval.campaign_report as reports
    from memweave_eval.paired import completed_info
    from memweave_eval.spec import REPOSITORY
    from memweave_eval.storage import atomic_json, file_digest

    s = spec(tmp_path)
    parent = s.root / "runs/parent"
    atomic_json(parent / "experiment.lock.json", {
        "phase": "full", "config": s.model_dump(mode="json"),
        "implementation_files": {
            "experiments/src/memweave_eval/" + n: file_digest(
                REPOSITORY / "experiments/src/memweave_eval" / n
            ) for n in ("pi_agent.py", "runtime_cache.py", "runner.py", "images.py", "network_probe.py", "public_archive.py")
        },
    })
    state = {
        "finished_at": "2026-10-28T14:00:00+00:00",
        "window_started_at": "2026-10-28T10:48:39+00:00",
        "window_deadline_at": "2026-10-30T10:48:39+00:00",
        "estimated_known_cost_usd": 0.4,
        "jobs": {"g02/solve": {"purpose": "solve", "path": "groups/g02/harbor/solve"}},
        "tasks": {"second": {"group": "g02", "actual_task_id": "second"}},
        "admission_failures": [{"task_id": "third", "phase": "official_image", "reason": "timeout"}],
    }
    atomic_json(parent / "run.json", state)
    for name in ("live.json", "evidence-index.json"):
        atomic_json(parent / name, {})
    rows = [
        {"task_id": t, "variant_id": v, "solve_source": "some-result",
         "success": t == "first", "solve_status": "completed_patch",
         "peak_estimated_cost_usd": 0.1,
         "session_diagnostics": {"model_responses_with_usage": 1}}
        for t in ("first", "second") for v in ("pi-native", "pi-memweave")
    ]
    summary = {"complete": False, "rows": rows, "invalid_evidence": [],
               "estimated_known_cost_usd": 0.4}
    monkeypatch.setattr(reports, "generate_campaign_report", lambda _: summary)
    s.completed_parent = parent
    catalog = {"selected": [{"task_id": t} for t in ("first", "second", "third")]}
    info, old = completed_info(s, catalog)
    assert info["known_cost_usd"] == 0.4
    assert info["window_deadline_at"] == state["window_deadline_at"]
    assert len(old) == 4 and old[2]["success"] is False
    assert info["blocked_admissions"]["third"]["phase"] == "official_image"
    summary["rows"] = rows[:-1]
    with pytest.raises(ValueError, match="pair"):
        completed_info(s, catalog)
    summary["rows"] = rows
    state["tasks"]["third"] = {"group": "g03"}
    state["jobs"]["g03/solve"] = {"purpose": "solve", "path": "groups/g03/harbor/solve"}
    atomic_json(parent / "run.json", state)
    with pytest.raises(ValueError, match="started"):
        completed_info(s, catalog)
    del state["jobs"]["g03/solve"]
    atomic_json(parent / "run.json", state)
    summary["estimated_known_cost_usd"] = 0.5
    with pytest.raises(ValueError, match="cost"):
        completed_info(s, catalog)
    summary["estimated_known_cost_usd"] = 0.4
    for row in rows[2:]:
        row["success"] = None
        row["solve_source"] = "groups/g02/harbor/solve/" + row["variant_id"] + "/result.json"
        p = parent / row["solve_source"]
        atomic_json(p, {})
        (p.parent / "agent").mkdir()
        (p.parent / "agent/model.patch").write_text("captured patch")
    rows[3].update(solve_status="cancelled", error_type="CancelledError")
    info, imported = completed_info(s, catalog)
    assert info["retained_interrupted_tasks"] == ["second"]
    assert len(imported) == 4
    s.completion_mode = "all_tasks"
    info, imported = completed_info(s, catalog)
    assert len(imported) == 2
    assert len(info["historical_attempts"]) == 2
    assert info["known_cost_usd"] == 0.4


def test_all_tasks_window_has_no_deadline_and_keeps_origin(tmp_path):
    from datetime import UTC, datetime

    from test_campaign import spec

    from memweave_eval.paired import campaign_window

    s = spec(tmp_path)
    old = {"window_started_at": "2026-10-01T00:00:00+00:00",
           "window_deadline_at": "2026-10-02T00:00:00+00:00"}
    with pytest.raises(TimeoutError):
        campaign_window(s, old, datetime(2026, 10, 29, tzinfo=UTC))
    s.completion_mode = "all_tasks"
    start, end, deadline = campaign_window(s, old, datetime(2026, 10, 29, tzinfo=UTC))
    assert start == old["window_started_at"] and end is None and deadline == float("inf")


def test_zero_model_proof_requires_exact_pre_pi_failure(tmp_path):
    from memweave_eval.paired import pre_pi_failure
    from memweave_eval.storage import atomic_json

    path = tmp_path / "groups/g05/harbor/solve/trial/result.json"
    atomic_json(path, {"exception_info": {
        "exception_type": "RuntimeError",
        "exception_message": "Pro offline/model-endpoint network probes failed",
    }, "agent_result": None})
    (path.parent / "agent").mkdir()
    (path.parent / "agent/model.patch").write_text("")
    row = {"solve_source": str(path), "session_diagnostics": None,
           "peak_estimated_cost_usd": None}
    digest = "67b9481b7e7b9cc08e00b91dfd1855e10ca6825df3ed60c131f85996d79f0192"
    assert pre_pi_failure(tmp_path, row, digest)
    assert not pre_pi_failure(tmp_path, row, "f" * 64)
    (path.parent / "agent/pi.txt").write_text("some Pi output")
    assert not pre_pi_failure(tmp_path, row, digest)


def test_shared_model_stop_allows_observed_grading_but_not_observer_failure(tmp_path):
    from types import SimpleNamespace

    from memweave_eval.paired import PairService

    service = PairService(tmp_path)
    service.thread = SimpleNamespace(is_alive=lambda: True)
    service.fatal.set()
    with pytest.raises(TimeoutError):
        service.check()
    assert service.check_grading() == 0
    service.error = "observation unavailable"
    with pytest.raises(ValueError, match="observation"):
        service.check_grading()


def test_only_approved_probe_adapter_change_can_cross_lineage(tmp_path):
    from memweave_eval.paired import verify_adapters
    from memweave_eval.spec import REPOSITORY
    from memweave_eval.storage import file_digest

    files = {"experiments/src/memweave_eval/" + n: file_digest(
        REPOSITORY / "experiments/src/memweave_eval" / n
    ) for n in ("pi_agent.py", "runtime_cache.py", "runner.py", "images.py", "network_probe.py", "public_archive.py")}
    assert verify_adapters({"implementation_files": files}) is None
    files.pop("experiments/src/memweave_eval/network_probe.py")
    files.pop("experiments/src/memweave_eval/public_archive.py")
    files["experiments/src/memweave_eval/pi_agent.py"] = (
        "67b9481b7e7b9cc08e00b91dfd1855e10ca6825df3ed60c131f85996d79f0192"
    )
    assert verify_adapters({"implementation_files": files})["reason"] == "approved preparation and Node probe"
    files["experiments/src/memweave_eval/pi_agent.py"] = "0" * 64
    with pytest.raises(ValueError, match="adapter changed"):
        verify_adapters({"implementation_files": files})
