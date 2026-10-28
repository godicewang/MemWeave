"""Offline all-planned-row comparison for a paired campaign."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .report import duration, normalize_trial, session_diagnostics, summarize
from .storage import atomic_json, contained, file_digest


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
    live_path = root / "live.json"
    live = json.loads(live_path.read_text()) if live_path.exists() else {}
    rows = []
    for plan in lock["plan"]:
        task, variant = plan["task_id"], plan["variant_id"]
        admission = state["tasks"].get(task, {})
        group = root / "groups" / admission.get("group", "_not_run")
        originals = []
        for path in (group / "harbor/solve").glob("*/result.json"):
            raw = json.loads(path.read_text())
            if (
                raw.get("task_name", "").split("/")[-1] == task
                and raw.get("config", {}).get("agent", {}).get("kwargs", {}).get("variant")
                == variant
            ):
                originals.append((path, raw))
        if len(originals) > 1:
            raise ValueError("ambiguous campaign solve result")
        original_path, original = originals[0] if originals else (None, None)
        row = normalize_trial(original, plan)
        row["solve_status"] = row["execution_status"]
        row["admission"] = admission
        if original_path:
            row["solve_source"] = original_path.relative_to(root).as_posix()
            sessions = list((original_path.parent / "agent/pi/sessions").glob("*.jsonl"))
            row["session_diagnostics"] = session_diagnostics(sessions)
            row["session_sources"] = [p.relative_to(root).as_posix() for p in sessions]
            usage = [live.get("sessions", {}).get(p.relative_to(root).as_posix()) for p in sessions]
            row["peak_estimated_cost_usd"] = (
                sum(u["estimated_cost_usd"] for u in usage)
                if usage and all(u is not None for u in usage)
                else None
            )
        if plan["suite_id"] == "swe-bench-pro-v2":
            scores = []
            for p in (group / "harbor" / ("regrade-" + variant)).glob("*/result.json"):
                raw = json.loads(p.read_text())
                if raw.get("task_name", "").split("/")[-1] == task:
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
            row["execution_status"] = (
                "scored"
                if score["success"] is not None
                else row["solve_status"]
                if original
                else "not_run"
            )
        else:
            row["score_status"] = row["execution_status"]
            row["score_source"] = row.get("solve_source")
        if admission.get("status") == "blocked":
            row.update(execution_status="blocked", score_status="blocked", success=None)
        if invalid:
            row.update(execution_status="invalid_evidence", success=None)
        rows.append(row)
    summary = summarize(rows)
    summary.update(
        schema_version=2,
        run_id=lock["run_id"],
        complete=bool(
            state["complete"] and not invalid and all(r["success"] is not None for r in rows)
        ),
        stop_reason=state.get("stop_reason"),
        rows=rows,
        invalid_evidence=invalid,
        overall_wall_seconds=duration(state),
        peak_solves=live.get("peak_solves"),
        estimated_known_cost_usd=live.get("estimated_cost_usd"),
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
        "variant_id",
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
        "# 49题双变体实验",
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
        text.append(f"| {a['display_id']} | {a['tier']} | {value(a)} | {value(b)} |")
    (root / "report.md").write_text("\n".join(text) + "\n")
    return summary
