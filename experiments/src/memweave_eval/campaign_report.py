"""Offline all-planned-row comparison for a paired campaign."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .report import duration, normalize_trial, session_diagnostics, summarize
from .storage import atomic_json, contained, file_digest


def retained_original(root, record):
    """Only a hashed original from this campaign's indexed run storage is reusable."""
    path = Path(record["solve_source"])
    if not path.is_absolute() or path.resolve() != path or len(path.parents) < 6:
        raise ValueError("invalid retained primary path")
    source = path.parents[5]
    parts = path.relative_to(source).parts
    if (source.parent != root.parent or len(parts) != 6 or parts[0] != "groups"
            or not re.fullmatch(r"g[0-9]{2}", parts[1])
            or parts[2:4] != ("harbor", "solve") or parts[-1] != "result.json"):
        raise ValueError("retained primary is outside campaign run storage")
    index = {e["path"]: e["sha256"] for e in json.loads((source / "evidence-index.json").read_text())["files"]}
    group_lock = path.parents[3] / "group.lock.json"
    required = [(path, record["result_sha256"]), (group_lock, record["group_lock_sha256"])]
    if record.get("suite_id") == "swe-bench-pro-v2":
        required.append((path.parent / "agent/model.patch", record["patch_sha256"]))
    sessions = list((path.parent / "agent/pi/sessions").glob("*.jsonl"))
    if not sessions or not session_diagnostics(sessions)["model_responses_with_usage"]:
        raise ValueError("retained primary lacks real Pi model evidence")
    required.extend((p, index.get(p.relative_to(source).as_posix())) for p in sessions)
    for file, digest in required:
        if (file.resolve() != file or not file.is_file() or file_digest(file) != digest
                or index.get(file.relative_to(source).as_posix()) != digest):
            raise ValueError("retained primary evidence changed or is unindexed")
    if json.loads(group_lock.read_text())["images"] != record["images"]:
        raise ValueError("retained primary image binding changed")
    raw = json.loads(path.read_text())
    if (raw.get("exception_info") or raw.get("task_name", "").split("/")[-1]
            != record.get("actual_task_id", record["task_id"])
            or raw.get("config", {}).get("agent", {}).get("kwargs", {}).get("variant") != record["variant_id"]):
        raise ValueError("retained primary has a failed or different task/variant")
    return path, raw


def valid_replay_binding(root, group, variant, actual_task, original_path, score, lock, indexed):
    if original_path is None:
        return False
    handoff = group / "replay-sources" / variant
    manifest_path = handoff / "handoff.json"
    patch = original_path.parent / "agent/model.patch"
    if not manifest_path.is_file() or not patch.is_file():
        return False
    external = not original_path.is_relative_to(root)
    if external:
        records = [r for r in (lock.get("bootstrap_lineage") or {}).get("retained_primary_attempts", [])
                   if r["variant_id"] == variant and Path(r["solve_source"]) == original_path]
        if len(records) != 1 or retained_original(root, records[0])[0] != original_path:
            return False
    required = (manifest_path,) if external else (manifest_path, patch, original_path)
    if any(p.relative_to(root).as_posix() not in indexed for p in required):
        return False
    manifest = json.loads(manifest_path.read_text())
    entries = [e for e in manifest["patches"] if e["task_id"] == actual_task]
    if manifest["variant"] != variant or len(entries) != 1:
        return False
    entry = entries[0]
    frozen_root = Path(lock["config"]["root"]) / "runs" / lock["run_id"]
    expected_handoff = frozen_root / handoff.relative_to(root)
    source_job = score.get("config", {}).get("agent", {}).get("kwargs", {}).get("source_job")
    target = contained(handoff, entry["destination"] + "/agent/model.patch")
    copied_result = contained(handoff, entry["destination"] + "/result.json")
    if any(p.relative_to(root).as_posix() not in indexed for p in (target, copied_result)):
        return False
    return (
        source_job == str(expected_handoff)
        and entry["source"] == str(patch if external else frozen_root / patch.relative_to(root))
        and file_digest(patch) == entry["sha256"]
        and file_digest(original_path) == entry["result_sha256"]
        and target.is_file()
        and file_digest(target) == entry["sha256"]
        and copied_result.is_file()
        and file_digest(copied_result) == entry["result_sha256"]
    )


def generate_campaign_report(root: Path):
    lock = json.loads((root / "experiment.lock.json").read_text())
    state = json.loads((root / "run.json").read_text())
    evidence = json.loads((root / "evidence-index.json").read_text())
    invalid = [
        r["path"]
        for r in evidence["files"]
        if not contained(root, r["path"]).is_file()
        or file_digest(contained(root, r["path"])) != r["sha256"]
    ]
    indexed = {r["path"] for r in evidence["files"]}
    invalid.extend(
        p.relative_to(root).as_posix()
        for p in root.glob("groups/*/harbor/*/*/result.json")
        if p.relative_to(root).as_posix() not in indexed
    )
    for lineage in (lock.get("preflight_lineage"), lock.get("bootstrap_lineage")):
        if not lineage:
            continue
        parent = Path(lineage["parent"])
        if parent.resolve().parent != root.resolve().parent or parent.is_symlink():
            invalid.append("preflight_parent/path")
        else:
            for name, digest in lineage["hashes"].items():
                if name not in (
                    "experiment.lock.json",
                    "run.json",
                    "live.json",
                    "evidence-index.json",
                ):
                    raise ValueError("unknown preflight lineage evidence")
                if not (parent / name).is_file() or file_digest(parent / name) != digest:
                    invalid.append("preflight_parent/" + name)
            if not invalid:
                for item in json.loads((parent / "evidence-index.json").read_text())["files"]:
                    path = contained(parent, item["path"])
                    if not path.is_file() or file_digest(path) != item["sha256"]:
                        invalid.append("preflight_parent/" + item["path"])
    live_path = root / "live.json"
    live = json.loads(live_path.read_text()) if live_path.exists() else {}
    rows = []
    for plan in lock["plan"]:
        task, variant = plan["task_id"], plan["variant_id"]
        admission = state["tasks"].get(task, {})
        actual_task = admission.get("actual_task_id", task)
        group = root / "groups" / admission.get("group", "_not_run")
        originals = []
        for path in (group / "harbor/solve").glob("*/result.json"):
            if path.relative_to(root).as_posix() not in indexed:
                continue
            raw = json.loads(path.read_text())
            if (
                raw.get("task_name", "").split("/")[-1] == actual_task
                and raw.get("config", {}).get("agent", {}).get("kwargs", {}).get("variant")
                == variant
            ):
                originals.append((path, raw))
        if len(originals) > 1:
            raise ValueError("ambiguous campaign solve result")
        original_path, original = originals[0] if originals else (None, None)
        retained = [r for r in (lock.get("bootstrap_lineage") or {}).get("retained_primary_attempts", [])
                    if (r["task_id"], r["variant_id"]) == (task, variant)]
        if len(retained) > 1 or (original and retained):
            raise ValueError("duplicate retained primary; never rerun completed inference")
        if retained:
            original_path, original = retained_original(root, retained[0])
            if not admission:
                actual_task = retained[0].get("actual_task_id", task)
        row = normalize_trial(original, plan)
        row["actual_task_id"] = actual_task
        row["actual_title"] = admission.get("actual_title", plan.get("title"))
        row["actual_display_id"] = admission.get("actual_display_id", plan["display_id"])
        row["solve_status"] = row["execution_status"]
        row["admission"] = admission
        if original_path:
            external = not original_path.is_relative_to(root)
            row["solve_source"] = str(original_path) if external else original_path.relative_to(root).as_posix()
            sessions = list((original_path.parent / "agent/pi/sessions").glob("*.jsonl"))
            row["session_diagnostics"] = session_diagnostics(sessions)
            row["session_sources"] = [str(p) if external else p.relative_to(root).as_posix() for p in sessions]
            usage = [live.get("sessions", {}).get(p.relative_to(root).as_posix()) for p in sessions] if not external else []
            row["peak_estimated_cost_usd"] = (
                sum(u["estimated_cost_usd"] for u in usage)
                if usage and all(u is not None for u in usage)
                else None
            )
            if external:
                row["peak_estimated_cost_usd"] = retained[0]["peak_estimated_cost_usd"]
                row["origin_run_id"] = retained[0].get("origin_run_id", original_path.parents[5].name)
                row["source_run_dir"] = str(original_path.parents[5])
        if plan["suite_id"] == "swe-bench-pro-v2":
            if original and not original.get("exception_info"):
                row["solve_status"] = (
                    "completed_patch"
                    if (original_path.parent / "agent/model.patch").is_file()
                    else "missing_patch"
                )
            scores = []
            for job_name in ("regrade-" + variant, "regrade"):
                for p in (group / "harbor" / job_name).glob("*/result.json"):
                    if p.relative_to(root).as_posix() not in indexed:
                        continue
                    raw = json.loads(p.read_text())
                    source_job = (
                        raw.get("config", {})
                        .get("agent", {})
                        .get("kwargs", {})
                        .get("source_job", "")
                    )
                    if job_name == "regrade" and Path(source_job).name != variant:
                        continue
                    if raw.get("task_name", "").split("/")[-1] == actual_task:
                        scores.append((p, raw))
            if len(scores) > 1:
                raise ValueError("ambiguous campaign regrade result")
            score = normalize_trial(scores[0][1] if scores else None, plan)
            for k in ("success", "native_reward"):
                row[k] = score[k]
            row["score_status"] = score["execution_status"]
            if scores:
                row["score_source"] = scores[0][0].relative_to(root).as_posix()
                row["grading_seconds"] = score["elapsed_seconds"]
                row["grading_error_type"] = score["error_type"]
                if score["success"] is not None and not valid_replay_binding(
                    root, group, variant, actual_task, original_path, scores[0][1], lock, indexed
                ):
                    row["success"] = None
                    row["score_status"] = "invalid_replay_binding"
            row["execution_status"] = (
                "scored"
                if row["success"] is not None
                else row["solve_status"]
                if original
                else "not_run"
            )
            if row["score_status"] == "invalid_replay_binding":
                row["execution_status"] = "invalid_replay_binding"
        else:
            row["score_status"] = row["execution_status"]
            row["score_source"] = row.get("solve_source")
        if admission.get("status") == "blocked":
            row.update(execution_status="blocked", score_status="blocked", success=None)
        if invalid:
            row.update(execution_status="invalid_evidence", success=None)
        rows.append(row)
    inherited_cost = 0
    lineage = lock.get("bootstrap_lineage")
    if lineage:
        parent = Path(lineage["parent"])
        previous = generate_campaign_report(parent)
        subset = lineage.get("kind") == "completed_pairs"
        if previous.get("invalid_evidence") or (not subset and not previous["complete"]):
            invalid.append("bootstrap_parent/incomplete")
        inherited_cost = lineage["known_cost_usd"]
        included = {tuple(k) for k in lineage.get("included_keys", [])} if subset else None
        originals = [r for r in previous["rows"] if included is None or
                     (r["task_id"], r["variant_id"]) in included]
        if subset and (
            not included
            or {(r["task_id"], r["variant_id"]) for r in originals} != included
            or any(r["success"] is None and r["task_id"] not in
                   lineage.get("retained_interrupted_tasks", []) for r in originals)
        ):
            invalid.append("completed_parent/incomplete_included_pairs")
        for old in originals:
            row = dict(old, inherited=True)
            row.setdefault("origin_run_id", previous["run_id"])
            row.setdefault("source_run_dir", str(parent))
            if row["task_id"] in lineage.get("retained_interrupted_tasks", []):
                row.update(retained_interrupted=True, comparison_eligible=False)
            for field in ("solve_source", "score_source"):
                if row.get(field):
                    row[field] = str(parent / row[field])
            rows.append(row)
        order = {(r["task_id"], r["variant_id"]): i for i, r in enumerate(lock["full_plan"])}
        if len({(r["task_id"], r["variant_id"]) for r in rows}) != len(rows):
            raise ValueError("duplicate inherited attempt; never silently rerun a bootstrap slot")
        rows.sort(key=lambda r: order[(r["task_id"], r["variant_id"])])
    for row in rows:
        row.setdefault("origin_run_id", lock["run_id"])
        if invalid:
            row.update(execution_status="invalid_evidence", success=None)
    summary = summarize(rows)
    blocked_attempt_rows = [
        dict(
            failure,
            variant_id=variant,
            execution_status="blocked",
            success=None,
            model_attempted=False,
        )
        for failure in state.get("admission_failures", [])
        for variant in ("pi-native", "pi-memweave")
    ]
    summary.update(
        schema_version=2,
        phase=lock.get("phase", "full"),
        overall_planned_model_trials=len(lock.get("full_plan", lock["plan"])),
        phase_planned_model_trials=sum(p.get("operation") != "score_only" for p in lock["plan"]),
        run_id=lock["run_id"],
        complete=bool(
            state["complete"] and not invalid and all(r["success"] is not None for r in rows)
        ),
        stop_reason=state.get("stop_reason"),
        rows=rows,
        blocked_attempt_rows=blocked_attempt_rows,
        pre_pi_failures=(lineage or {}).get("pre_pi_failures", []),
        historical_attempts=(lineage or {}).get("historical_attempts", []),
        invalid_evidence=invalid,
        overall_wall_seconds=duration(
            dict(state, started_at=state.get("window_started_at", state.get("started_at")))
        ),
        current_run_wall_seconds=duration(state),
        window_deadline_at=state.get("window_deadline_at"),
        peak_solves=live.get("peak_solves"),
        estimated_known_cost_usd=inherited_cost + live.get("estimated_cost_usd", 0),
        by_suite={
            suite: summarize([r for r in rows if r["suite_id"] == suite])
            for suite in sorted({r["suite_id"] for r in rows})
        },
        by_tier={
            tier: summarize([r for r in rows if r["tier"] == tier])
            for tier in ("simple", "medium", "hard", "extreme")
        },
    )
    atomic_json(root / "summary.json", summary)
    columns = [
        "display_id",
        "suite_id",
        "tier",
        "task_id",
        "actual_task_id",
        "actual_display_id",
        "actual_title",
        "variant_id",
        "origin_run_id",
        "execution_status",
        "score_status",
        "success",
        "error_type",
        "peak_estimated_cost_usd",
        "elapsed_seconds",
        "solve_source",
        "score_source",
    ]
    with (root / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    text = [
        "# 单题双变体闭环" if lock.get("phase") == "bootstrap" else "# 49题双变体实验",
        "",
        f"完整完成：{summary['complete']}；停止：{summary['stop_reason']}",
        f"实测解题峰值：{summary['peak_solves']}；已知估算费用：{summary['estimated_known_cost_usd']}",
        "",
        "| 题号 | 档位 | 原生Pi | MemWeave Pi |",
        "|---|---|---|---|",
    ]

    def value(row):
        return (
            ("通过" if row["success"] else "未通过")
            if row["success"] is not None
            else row["execution_status"]
        )

    for i in range(0, len(rows), 2):
        a, b = rows[i : i + 2]
        label = a["display_id"] + (
            "→" + a["actual_display_id"] if a["actual_task_id"] != a["task_id"] else ""
        )
        text.append(f"| {label} | {a['tier']} | {value(a)} | {value(b)} |")
    if blocked_attempt_rows:
        text += [
            "",
            "准入阻断原件（不计作模型失败）：",
            "",
            "| 原槽位 | 失败题 | 阶段 |",
            "|---|---|---|",
        ]
        for failure in state.get("admission_failures", []):
            text.append(
                f"| {failure['slot_task_id']} | {failure['task_id']} | {failure.get('phase')} |"
            )
    (root / "report.md").write_text("\n".join(text) + "\n")
    return summary
