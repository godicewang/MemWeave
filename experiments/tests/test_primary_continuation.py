"""Experiment recovery boundaries; no model requests or Pi substitutes."""
from pathlib import Path

import pytest


def test_resume_partitions_individual_sides_and_keeps_first_zero(tmp_path):
    from memweave_eval.paired import partition_primary_rows
    from memweave_eval.storage import atomic_json

    rows = []
    for task, variant, score, status in (
        ("one", "pi-native", False, "completed_patch"),
        ("one", "pi-memweave", None, "cancelled"),
        ("two", "pi-native", None, "completed_patch"),
        ("two", "pi-memweave", True, "completed_patch"),
    ):
        path = tmp_path / f"groups/{task}/harbor/solve/{variant}/result.json"
        atomic_json(path, {"exception_info": ({"exception_type": "CancelledError"}
                                              if status == "cancelled" else None)})
        (path.parent / "agent").mkdir()
        (path.parent / "agent/model.patch").write_text(task + variant)
        rows.append({"task_id": task, "variant_id": variant,
                     "suite_id": "swe-bench-pro-v2", "solve_source": str(path),
                     "solve_status": status, "success": score,
                     "session_diagnostics": {"model_responses_with_usage": 2},
                     "peak_estimated_cost_usd": 0.1})
    keep, pending, history = partition_primary_rows(tmp_path, rows)
    assert {(r["task_id"], r["variant_id"]) for r in keep} == {
        ("one", "pi-native"), ("two", "pi-memweave")}
    assert keep[0]["success"] is False
    assert len(pending) == 1 and pending[0]["task_id"] == "two"
    assert len(history) == 1 and history[0]["variant_id"] == "pi-memweave"
    assert history[0]["retained_interrupted"]
    assert Path(pending[0]["solve_source"]).read_text().startswith("{")
    assert pending[0]["result_sha256"] and pending[0]["patch_sha256"]
    # A normal zero survives even when its counterpart was cancelled.
    assert not any(r["task_id"] == "one" and r["variant_id"] == "pi-native" for r in history)


def test_tampered_or_missing_completed_patch_cannot_be_reused_as_score_only(tmp_path):
    from memweave_eval.paired import partition_primary_rows
    from memweave_eval.storage import atomic_json

    path = tmp_path / "groups/one/harbor/solve/native/result.json"
    atomic_json(path, {"exception_info": None})
    row = {"task_id": "one", "variant_id": "pi-native", "suite_id": "swe-bench-pro-v2",
           "solve_source": str(path), "solve_status": "completed_patch", "success": None,
           "session_diagnostics": {"model_responses_with_usage": 2},
           "peak_estimated_cost_usd": 0.1}
    with pytest.raises(ValueError, match="patch"):
        partition_primary_rows(tmp_path, [row])


def test_phase_plan_excludes_scored_sides_and_marks_ungraded_primary_as_score_only():
    from memweave_eval.paired import continuation_plan

    plan = [{"task_id": t, "variant_id": v} for t in ("one", "two")
            for v in ("pi-native", "pi-memweave")]
    keep = [{"task_id": "one", "variant_id": "pi-native", "success": False}]
    pending = [{"task_id": "two", "variant_id": "pi-memweave"}]
    result = continuation_plan(plan, keep, pending)
    assert len(result) == 3
    assert [(p["task_id"], p["variant_id"]) for p in result if p["operation"] == "score_only"] == [
        ("two", "pi-memweave")]
    assert sum(p["operation"] == "solve" for p in result) == 2


def test_current_probe_failure_is_zero_only_before_any_pi_evidence(tmp_path):
    from memweave_eval.paired import pre_pi_failure
    from memweave_eval.storage import atomic_json

    path = tmp_path / "groups/one/harbor/solve/plugin/result.json"
    atomic_json(path, {"exception_info": {
        "exception_type": "RuntimeError",
        "exception_message": "Pro offline/model-endpoint network probes failed; see network-probe.json",
    }, "agent_result": {"cost_usd": None, "n_input_tokens": None}})
    (path.parent / "agent").mkdir()
    (path.parent / "agent/model.patch").write_text("")
    atomic_json(path.parent / "agent/network-probe.json", {
        "passed": False, "credential_free": True,
        "checks": {"model": {"ok": False, "status": None, "error": "TOTAL_TIMEOUT"},
                   "outside": {"ok": False, "status": None, "error": "ECONNRESET"}},
    })
    row = {"solve_source": str(path), "session_diagnostics": None,
           "peak_estimated_cost_usd": None}
    digest = "0680e465b92628bc7478be41b7cf04b8d5ff3024c6cf0fb2083cbf8bc82c8abf"
    assert pre_pi_failure(tmp_path, row, digest)
    # Missing stdout/Session evidence is necessary but not enough: the exact
    # audited adapter, error and strictly blocked external network also matter.
    assert not pre_pi_failure(tmp_path, row, "f" * 64)
    (path.parent / "agent/pi.txt").write_text("")
    assert not pre_pi_failure(tmp_path, row, digest)


def test_score_only_report_binds_original_patch_and_preserves_counterpart_zero(tmp_path, monkeypatch):
    import json
    import shutil

    import memweave_eval.campaign_report as reports
    from memweave_eval.paired import primary_evidence
    from memweave_eval.report import normalize_trial
    from memweave_eval.storage import atomic_json, file_digest

    parent, root = tmp_path / "runs/parent", tmp_path / "runs/current"
    task = "instance_task"
    plan = [{"task_id": task, "variant_id": v, "suite_id": "swe-bench-pro-v2",
             "display_id": "S01", "tier": "simple", "title": "synthetic fixture", "repetition": 1}
            for v in ("pi-native", "pi-memweave")]
    original = parent / "groups/g01/harbor/solve/instance_original/result.json"
    raw = {"task_name": "suite/" + task, "trial_name": "instance_original", "exception_info": None,
           "config": {"agent": {"kwargs": {"variant": "pi-native"}}},
           "agent_result": {"cost_usd": 0.1, "n_input_tokens": 2, "n_output_tokens": 1}}
    atomic_json(original, raw)
    agent = original.parent / "agent"
    agent.mkdir()
    patch = agent / "model.patch"
    patch.write_text("original captured patch")
    session = agent / "pi/sessions/session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(json.dumps({"type": "message", "message": {
        "role": "assistant", "content": [], "usage": {"input": 2, "output": 1}}}) + "\n")
    atomic_json(parent / "groups/g01/group.lock.json", {"images": {task: {"id": "frozen", "platform": "linux/amd64"}}})
    pending = primary_evidence(dict(plan[0], actual_task_id=task, solve_source=str(original),
                                    peak_estimated_cost_usd=0.1))
    kept = normalize_trial({"verifier_result": {"rewards": {"reward": 0}}}, plan[1])
    kept.update(actual_task_id=task, actual_display_id="S01", actual_title="fixture")

    def index(directory):
        atomic_json(directory / "evidence-index.json", {"files": [
            {"path": p.relative_to(directory).as_posix(), "sha256": file_digest(p)}
            for p in directory.rglob("*") if p.is_file() and p.name != "evidence-index.json"]})

    index(parent)
    handoff = root / "groups/g01/replay-sources/pi-native"
    target = handoff / "instance_original"
    (target / "agent").mkdir(parents=True)
    shutil.copyfile(original, target / "result.json")
    shutil.copyfile(patch, target / "agent/model.patch")
    atomic_json(handoff / "handoff.json", {"variant": "pi-native", "patches": [{
        "task_id": task, "source": str(patch), "sha256": file_digest(patch),
        "result_sha256": file_digest(original), "destination": "instance_original"}]})
    score = root / "groups/g01/harbor/regrade/score/result.json"
    atomic_json(score, {"task_name": "suite/" + task, "exception_info": None,
                       "verifier_result": {"rewards": {"reward": 0}},
                       "config": {"agent": {"kwargs": {"source_job": str(handoff)}}}})
    atomic_json(root / "experiment.lock.json", {
        "run_id": "current", "phase": "full", "config": {"root": str(tmp_path)},
        "full_plan": plan, "plan": [dict(plan[0], operation="score_only")],
        "bootstrap_lineage": {"kind": "completed_pairs", "parent": str(parent), "hashes": {},
                              "known_cost_usd": 0.2, "included_keys": [[task, "pi-memweave"]],
                              "retained_primary_attempts": [pending]}})
    atomic_json(root / "run.json", {"complete": True, "tasks": {task: {"group": "g01", "actual_task_id": task}}})
    atomic_json(root / "live.json", {"estimated_cost_usd": 0})
    index(root)
    real = reports.generate_campaign_report
    monkeypatch.setattr(reports, "generate_campaign_report", lambda p: {
        "run_id": "parent", "complete": False, "rows": [kept], "invalid_evidence": []
    } if p == parent else real(p))
    summary = real(root)
    assert not summary["invalid_evidence"] and summary["complete"]
    assert summary["phase_planned_model_trials"] == 0 and len(summary["rows"]) == 2
    assert all(r["success"] is False for r in summary["rows"])
    assert summary["estimated_known_cost_usd"] == 0.2
    assert summary["rows"][0]["solve_source"] == str(original)
    assert summary["rows"][0]["peak_estimated_cost_usd"] == 0.1
    assert not list(root.rglob("session.jsonl")), "do not create another Session copy"
    (target / "agent/model.patch").write_text("different patch")
    index(root)
    changed = real(root)
    assert changed["rows"][0]["success"] is None
    assert changed["rows"][0]["score_status"] == "invalid_replay_binding"
    patch.write_text("tampered original")
    with pytest.raises(ValueError, match="changed|unindexed"):
        reports.retained_original(root, pending)


def test_registered_solve_cannot_hide_a_missing_dispatched_variant(tmp_path):
    from memweave_eval.paired import validate_registered_solve
    from memweave_eval.storage import atomic_json

    job = tmp_path / "groups/g01/harbor/solve"
    atomic_json(tmp_path / "groups/g01/configs/solve.json", {"agents": [
        {"kwargs": {"variant": v}} for v in ("pi-native", "pi-memweave")]})
    for variant in ("pi-native",):
        atomic_json(job / variant / "result.json", {"task_name": "suite/task",
                    "config": {"agent": {"kwargs": {"variant": variant}}}})
    with pytest.raises(ValueError, match="missing|dispatched"):
        validate_registered_solve(tmp_path, "g01", "task")
    atomic_json(job / "pi-memweave/result.json", {"task_name": "suite/task",
                "config": {"agent": {"kwargs": {"variant": "pi-memweave"}}}})
    validate_registered_solve(tmp_path, "g01", "task")
