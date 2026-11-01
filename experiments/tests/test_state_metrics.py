import io
import json
import tarfile

import pytest

from memweave_eval.state_metrics import stable_id, task_state_metrics


def originals(tmp_path, calls=40, writes=None):
    """A real-shaped Session plus its committed State evidence, never model output guesses."""
    writes = writes or {}
    directory = tmp_path / "agent"
    sessions = directory / "pi/sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    entries = [{"type": "session", "id": "session"}]
    state = [{"op_id": "initial", "op": "update_goal", "goal": "g", "evidence": {}}]
    fact = 0
    parent = None
    for position in range(1, calls + 1):
        key = f"a{position}"
        parts = []
        if position in writes:
            count, failed = writes[position]
            parts = [{"type": "toolCall", "name": "state_append", "id": "reused-id",
                      "arguments": {"items": [{}] * count}}]
            if not failed:
                operation = stable_id("task_x", "session", key, "reused-id")
                for index in range(count):
                    fact += 1
                    state.append({"op_id": stable_id(operation, index), "op": "append_fact",
                                  "id": f"F{fact}", "fact": "f", "evidence": {"U1": "u"}})
        entries.append({"type": "message", "id": key, "parentId": parent,
                        "message": {"role": "assistant", "usage": {"input": 1},
                                    "content": parts}})
        parent = key
        if parts:
            parent = f"r{position}"
            entries.append({"type": "message", "id": parent, "parentId": key,
                            "message": {"role": "toolResult", "toolCallId": "reused-id",
                                        "toolName": "state_append", "isError": failed}})
    path = sessions / "s.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    archive = directory / "memory.tar.gz"
    save_state(archive, state)
    return path, archive, entries, state


def save_state(path, state):
    data = "".join(json.dumps(e) + "\n" for e in state).encode()
    with tarfile.open(path, "w:gz") as output:
        member = tarfile.TarInfo("memory/work/tasks/task_x/state.json")
        member.size = len(data)
        output.addfile(member, io.BytesIO(data))


@pytest.mark.parametrize("events,status", [(0, "too_sparse"), (1, "too_sparse"),
                                          (2, "ok"), (4, "ok"), (5, "too_dense")])
def test_ratio_counts_items_and_closed_boundaries(tmp_path, events, status):
    path, archive, _, _ = originals(tmp_path, writes={10: (events, False)} if events else {})
    metrics = task_state_metrics([path], archive)
    assert metrics["model_responses_with_usage"] == 40
    assert metrics["model_request_attempts"] is None
    assert metrics["fd_events_added"] == events
    assert metrics["event_model_ratio"] == events / 40
    assert metrics["ratio_status"] == status
    assert bool(metrics["warnings"]) == (status != "ok")
    assert metrics["writes"]["state_append"]["attempts"] == bool(events)


def test_failure_retry_and_duplicate_originals_do_not_inflate_events(tmp_path):
    path, archive, entries, _ = originals(tmp_path, writes={1: (2, True), 2: (2, False)})
    path.write_text(path.read_text() + "".join(json.dumps(e) + "\n" for e in entries[1:]))
    result = task_state_metrics([path, path], archive)
    assert result["writes"]["state_append"] == {
        "attempts": 2, "successes": 1, "failures": 1, "unknown": 0, "success_rate": 0.5}
    assert result["fd_events_added"] == 2
    assert result["write_model_positions"] == [2]
    assert result["uniformity"]["status"] == "insufficient_sample"
    # A failed return can still have a committed operation (derived write failed).
    entries[4]["message"]["isError"] = True  # r2: new F/D committed, derived update failed
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    partial = task_state_metrics([path], archive)
    assert partial["writes"]["state_append"]["failures"] == 2
    assert partial["fd_events_added"] == 2
    assert partial["write_model_positions"] == [2]


@pytest.mark.parametrize("positions,intervals,cv", [([10, 25, 40], [15, 15], 0),
                                                  ([1, 2, 40], [1, 38], 37 / 39)])
def test_uniformity_is_batch_spacing_and_edges_are_separate(tmp_path, positions, intervals, cv):
    path, archive, _, _ = originals(tmp_path, calls=50,
                                  writes={p: (2, False) for p in positions})
    result = task_state_metrics([path], archive)
    uniformity = result["uniformity"]
    assert result["fd_events_added"] == 6
    assert uniformity["intervals"] == intervals
    assert uniformity["mean_interval"] == sum(intervals) / len(intervals)
    assert uniformity["cv"] == pytest.approx(cv)
    assert uniformity["max_interval"] == max(intervals)
    assert uniformity["head_calls"] == positions[0]
    assert uniformity["tail_calls"] == 50 - positions[-1]


@pytest.mark.parametrize("calls,writes", [(0, {}), (3, {}), (10, {5: (1, False)}),
                                         (20, {5: (1, False), 15: (1, False)})])
def test_empty_and_short_samples_never_look_perfect(tmp_path, calls, writes):
    path, archive, _, _ = originals(tmp_path, calls=calls, writes=writes)
    result = task_state_metrics([path], archive)
    assert result["uniformity"]["cv"] is None
    assert result["uniformity"]["status"] == "insufficient_sample"
    if not calls:
        assert result["event_model_ratio"] is None
        assert result["ratio_status"] == "zero_model_responses"
    elif calls < 20:
        assert result["sample_status"] == "short_sample"


def test_old_incomplete_traces_keep_unknowns_and_goal_is_not_fd(tmp_path):
    path, archive, entries, _ = originals(tmp_path, writes={5: (1, False)})
    entries[6]["message"].pop("isError")
    entries[1]["message"].pop("usage")
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    result = task_state_metrics([path], archive)
    assert result["writes"]["state_append"]["unknown"] == 1
    assert result["writes"]["state_append"]["success_rate"] is None
    assert result["ratio_status"] == "unknown"
    assert result["uniformity"]["status"] == "unknown"
    assert task_state_metrics([path], None)["fd_events_added"] is None
    assert task_state_metrics([], None)["model_responses_with_usage"] is None


def test_modify_fact_counts_new_fact_but_not_archives_or_goals(tmp_path):
    path, archive, entries, state = originals(tmp_path, writes={5: (2, False)})
    call = {"type": "toolCall", "name": "modify_fact", "id": "modify", "arguments": {}}
    entries[11]["message"]["content"] = [call]  # a10, after r5
    state.append({"op_id": stable_id("task_x", "session", "a10", "modify"),
                  "op": "modify_fact", "archive": ["F1", "F2"],
                  "append_fact": {"content": "correction", "evidence": {"U1": "u"}}})
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    save_state(archive, state)
    result = task_state_metrics([path], archive)
    assert result["fd_events_added"] == 3
    assert result["fd_events_active"] == 1
    assert result["write_model_positions"] == [5, 10]
    assert result["writes"]["modify_fact"]["unknown"] == 1  # committed, missing receipt


def test_slides_and_goals_affect_stock_but_not_cumulative_events(tmp_path):
    path, archive, _, state = originals(tmp_path, writes={10: (2, False)})
    state[2].update(op="append_decision", id="D1", decision="d")
    state[2].pop("fact")
    state += [{"op_id": "goal-update", "op": "update_goal", "goal": "next", "evidence": {}},
              {"op_id": "slide", "op": "slide_window", "status": "committed",
               "evicted_range": {"from": 2, "to": 3}, "retained_ids": ["D1"]}]
    save_state(archive, state)
    result = task_state_metrics([path], archive)
    assert result["fd_events_added"] == 2
    assert result["fd_events_active"] == 1


def test_missing_operation_attribution_preserves_total_but_not_uniformity(tmp_path):
    path, archive, _, state = originals(tmp_path, writes={10: (1, False)})
    state[-1]["op_id"] = "unlocatable-legacy-operation"
    save_state(archive, state)
    result = task_state_metrics([path], archive)
    assert result["fd_events_added"] == 1
    assert result["event_model_ratio"] == 0.025
    assert result["uniformity"]["status"] == "unknown"


def test_malformed_archive_or_session_and_auxiliary_calls(tmp_path):
    path, archive, _, _ = originals(tmp_path)
    path.write_text(path.read_text() + json.dumps({"type": "compaction", "usage": {"input": 1}}) + "\n")
    assert task_state_metrics([path], archive)["model_responses_with_usage"] == 40
    path.write_text(path.read_text() + "unfinished{")
    result = task_state_metrics([path], archive)
    assert result["ratio_status"] == "unknown"
    assert result["source_status"] == "invalid_session"
    archive.write_bytes(b"bad archive")
    assert task_state_metrics([path], archive)["fd_events_added"] is None


def test_all_state_write_tools_are_separate_from_fd_events(tmp_path):
    path, archive, entries, _ = originals(tmp_path)
    for index, name in [(5, "task_create"), (10, "update_goal"), (15, "state_remain")]:
        entries[index]["message"]["content"] = [
            {"type": "toolCall", "name": name, "id": name, "arguments": {}}]
        entries.append({"type": "message", "id": name, "parentId": f"a{index}",
                        "message": {"role": "toolResult", "toolCallId": name,
                                    "toolName": name, "isError": False}})
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    m = task_state_metrics([path], archive)
    assert m["fd_events_added"] == 0
    assert m["writes"]["state_append"]["attempts"] == 0
    for name in ("task_create", "update_goal", "state_remain"):
        assert m["writes"][name]["successes"] == 1


def test_separate_writes_in_one_model_response_have_zero_gaps_not_perfect_cv(tmp_path):
    path, archive, entries, state = originals(tmp_path, writes={10: (1, False)})
    for i in (2, 3):
        entries[10]["message"]["content"].append(
            {"type": "toolCall", "name": "state_append", "id": f"more-{i}",
             "arguments": {"items": [{}]}})
        state.append({"op_id": stable_id(stable_id("task_x", "session", "a10", f"more-{i}"), 0),
                      "op": "append_fact", "id": f"F{i}", "fact": "f", "evidence": {"U1": "u"}})
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    save_state(archive, state)
    m = task_state_metrics([path], archive)
    assert m["write_model_positions"] == [10, 10, 10]
    assert m["uniformity"]["intervals"] == [0, 0]
    assert m["uniformity"]["mean_interval"] == 0
    assert m["uniformity"]["cv"] is None


@pytest.mark.parametrize("schema", [1, 2])
def test_reports_emit_task_metrics_to_json_csv_and_markdown_without_mixing_retries(tmp_path, schema):
    import csv

    from memweave_eval.report import generate_report
    from memweave_eval.storage import atomic_json, evidence_index, file_digest

    plans, jobs = [], {}
    for variant in ("pi-native", "pi-memweave"):
        plans.append({"task_id": "x", "variant_id": variant, "repetition": 1,
                      "suite_id": "terminal-bench-4", "display_id": "S01", "tier": "simple"})
        name = variant + "-r1"
        base = (tmp_path / "groups/g01/harbor/solve" / variant if schema == 2
                else tmp_path / "harbor" / name / "trial")
        originals(base, calls=50, writes={10: (1, False), 20: (1, False),
                                        30: (1, False), 40: (2, True)})
        atomic_json(base / "result.json", {
            "task_name": "x", "trial_name": variant,
            "config": {"agent": {"kwargs": {"variant": variant}}},
            "verifier_result": {"rewards": {"reward": 1}}})
        jobs[name] = {"path": "harbor/" + name}
    # This diagnostic retry must never be folded into a primary task's counters.
    originals(tmp_path / "harbor/historical-retry/trial", calls=100, writes={1: (20, False)})
    lock = {"schema_version": schema, "run_id": "test", "plan": plans,
            "suite": {"id": "terminal-bench-4", "protocol": "tb4"}}
    atomic_json(tmp_path / "experiment.lock.json", lock)
    atomic_json(tmp_path / "run.json", {"complete": True, "jobs": jobs,
                "tasks": {"x": {"group": "g01", "actual_task_id": "x"}}})
    indexed = evidence_index(tmp_path) if schema == 1 else [
        {"path": p.relative_to(tmp_path).as_posix(), "sha256": file_digest(p)}
        for p in tmp_path.rglob("*") if p.is_file() and
        ("agent" in p.parts or p.name == "result.json")]
    atomic_json(tmp_path / "evidence-index.json", {"files": indexed})
    summary = generate_report(tmp_path)
    rows = (summary["rows"] if schema == 2 else
            json.loads((tmp_path / "reports/results.json").read_text())["trials"])
    row = next(r for r in rows if r["variant_id"] == "pi-memweave")
    assert row["state_metrics"]["model_responses_with_usage"] == 50
    assert row["state_append_attempts"] == 4
    assert row["state_append_success_rate"] == 0.75
    assert row["fd_events_added"] == 3
    assert row["state_event_model_ratio"] == 0.06
    assert row["state_write_cv"] == 0
    report_root = tmp_path if schema == 2 else tmp_path / "reports"
    csv_path = report_root / ("comparison.csv" if schema == 2 else "trials.csv")
    with csv_path.open() as source:
        records = list(csv.DictReader(source))
    assert json.loads(records[1]["state_metrics"])["fd_events_added"] == 3
    assert "任务级 State 诊断" in (report_root / "report.md").read_text()
    # Reports are derived and deterministic; modifying evidence makes metrics unknown.
    assert generate_report(tmp_path) == summary
    (base / "agent/memory.tar.gz").write_bytes(b"changed")
    damaged = generate_report(tmp_path)
    rows = damaged["rows"] if schema == 2 else json.loads(
        (tmp_path / "reports/results.json").read_text())["trials"]
    assert rows[1]["state_metrics"]["fd_events_added"] is None
    assert rows[1]["state_metrics"]["source_status"] == "invalid_evidence"
