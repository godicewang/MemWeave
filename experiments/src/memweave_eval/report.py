"""Deterministic, offline reports. Missing evidence is never an implicit zero score."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from pathlib import Path

from .storage import atomic_json, contained, file_digest


def normalize_trial(raw: dict | None, plan: dict) -> dict:
    row = dict(plan)
    row.update(
        execution_status="not_run",
        native_reward=None,
        success=None,
        usage={"input_tokens": None, "cache_tokens": None, "output_tokens": None, "cost_usd": None},
        error_type=None,
    )
    if raw is None:
        return row
    row["harbor_trial"] = raw.get("trial_name")
    row["error_type"] = (raw.get("exception_info") or {}).get("exception_type")
    error = row["error_type"] or ""
    if "Cancel" in error:
        status = "cancelled"
    elif "Verifier" in error or "Reward" in error:
        status = "verifier_error"
    elif "Agent" in error or "Token" in error or "ContextWindow" in error:
        status = "agent_error"
    elif error:
        status = "infrastructure_error"
    else:
        status = "invalid_result"
    reward = (raw.get("verifier_result") or {}).get("rewards")
    # Preserve valid JSON values. Non-finite native output stays in the original file.
    try:
        json.dumps(reward, allow_nan=False)
        row["native_reward"] = reward
    except (ValueError, TypeError):
        row["native_reward"] = None
    if reward is not None:
        value = reward.get("reward") if isinstance(reward, dict) else None
        if type(value) in (int, float) and math.isfinite(value) and value in (0, 1):
            row["success"] = value == 1
            if not error:
                status = "scored"
        else:
            status = "invalid_result"
    row["execution_status"] = status
    contexts = (
        [raw["agent_result"]]
        if raw.get("agent_result")
        else [s["agent_result"] for s in raw.get("step_results") or [] if s.get("agent_result")]
    )
    for source, target in [
        ("n_input_tokens", "input_tokens"),
        ("n_cache_tokens", "cache_tokens"),
        ("n_output_tokens", "output_tokens"),
        ("cost_usd", "cost_usd"),
    ]:
        values = [c.get(source) for c in contexts]
        if values and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values):
            row["usage"][target] = sum(values)
    for phase in ("environment_setup", "agent_setup", "agent_execution", "verifier"):
        row[phase] = raw.get(phase)
    row["started_at"], row["finished_at"] = raw.get("started_at"), raw.get("finished_at")
    return row


def summarize(rows: list[dict]) -> dict:
    result = {
        "variants": {},
        "pairs": {"both": 0, "native_only": 0, "memweave_only": 0, "neither": 0, "missing": 0},
    }
    groups, pairs = defaultdict(list), defaultdict(dict)
    for row in rows:
        groups[row["variant_id"]].append(row)
        pairs[(row["task_id"], row["repetition"])][row["variant_id"]] = row["success"]
    for variant, items in groups.items():
        scored = [r for r in items if r["success"] is not None]
        successes = sum(r["success"] is True for r in items)
        costs = [r["usage"]["cost_usd"] for r in items]
        result["variants"][variant] = {
            "planned": len(items),
            "scored": len(scored),
            "successes": successes,
            "coverage_success_rate": successes / len(items),
            "valid_success_rate": successes / len(scored) if scored else None,
            "cost_usd": sum(costs) if all(c is not None for c in costs) else None,
            "known_cost_usd": sum(c for c in costs if c is not None),
            "missing_cost_count": sum(c is None for c in costs),
        }
    for pair in pairs.values():
        a, b = pair.get("pi-native"), pair.get("pi-memweave")
        label = (
            "missing"
            if a is None or b is None
            else "both"
            if a and b
            else "native_only"
            if a
            else "memweave_only"
            if b
            else "neither"
        )
        result["pairs"][label] += 1
    return result


def generate_report(root: Path) -> dict:
    lock = json.loads((root / "experiment.lock.json").read_text())
    state = json.loads((root / "run.json").read_text())
    evidence = json.loads((root / "evidence-index.json").read_text())
    invalid = set()
    for item in evidence["files"]:
        p = contained(root, item["path"])
        if not p.is_file() or file_digest(p) != item["sha256"]:
            invalid.add(item["path"])
    rows = []
    for plan in lock["plan"]:
        job_name = f"{plan['variant_id']}-r{plan['repetition']}"
        job = state.get("jobs", {}).get(job_name, {})
        source = (
            job.get("regrade") if lock["suite"]["protocol"] == "swe-pro-v2" else job.get("path")
        )
        matches = []
        if source:
            for item in evidence["files"]:
                if item["path"].startswith(source + "/") and item["path"].endswith("/result.json"):
                    p = contained(root, item["path"])
                    if item["path"] in invalid:
                        continue
                    data = json.loads(p.read_text())
                    if data.get("task_name", "").split("/")[-1] == plan["task_id"]:
                        matches.append((item["path"], data))
        row = normalize_trial(matches[0][1] if len(matches) == 1 else None, plan)
        if len(matches) > 1 or invalid:
            row.update(execution_status="invalid_result", success=None)
        if matches:
            row["score_source"] = matches[0][0]
        # Replaying a patch makes no inference. Attribute usage to its original attempt.
        if lock["suite"]["protocol"] == "swe-pro-v2" and job.get("path"):
            originals = []
            for item in evidence["files"]:
                if item["path"].startswith(job["path"] + "/") and item["path"].endswith(
                    "/result.json"
                ):
                    if item["path"] in invalid:
                        continue
                    raw = json.loads(contained(root, item["path"]).read_text())
                    if raw.get("task_name", "").split("/")[-1] == plan["task_id"]:
                        originals.append(raw)
            if len(originals) == 1:
                original = normalize_trial(originals[0], plan)
                row["usage"] = original["usage"]
                row["error_type"] = original["error_type"]
                row["original_trial"] = originals[0].get("trial_name")
                if original["error_type"] and row["execution_status"] == "scored":
                    row["execution_status"] = original["execution_status"]
                if not matches:
                    row["execution_status"] = original["execution_status"]
                patch = job.get("patches", {}).get(plan["task_id"])
                if patch:
                    row["patch_source"] = patch["path"]
                    row["patch_sha256"] = patch["sha256"]
                    recorded = next(
                        (item for item in evidence["files"] if item["path"] == patch["path"]), None
                    )
                    if not recorded or recorded["sha256"] != patch["sha256"]:
                        row.update(execution_status="invalid_result", success=None)
                else:
                    row.update(execution_status="invalid_result", success=None)
            else:
                row.update(execution_status="invalid_result", success=None)
        rows.append(row)
    summary = summarize(rows)
    summary["complete"] = (
        not invalid and not state.get("stop_reason") and all(r["success"] is not None for r in rows)
    )
    summary["suite"] = lock["suite"]["id"]
    output = root / "reports"
    atomic_json(output / "results.json", {"schema_version": 1, "summary": summary, "trials": rows})
    for filename, records in [
        ("trials.csv", rows),
        ("comparison.csv", [dict(variant=k, **v) for k, v in summary["variants"].items()]),
    ]:
        stream = io.StringIO()
        keys = list(dict.fromkeys(k for row in records for k in row))
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                    for k, v in record.items()
                }
            )
        (output / filename).write_text(stream.getvalue())
    lines = [
        f"# {lock['suite']['id']} 实际重跑对照",
        "",
        f"运行：{lock['run_id']}",
        "",
        "仅代表冻结的本机子集；不导入公开榜单成绩。",
        "",
        "| 变体 | 计划 | 有效评分 | 成功 | 计划成功覆盖率 | 有效样本成功率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant, s in summary["variants"].items():
        valid = f"{s['valid_success_rate']:.1%}" if s["valid_success_rate"] is not None else "未知"
        lines.append(
            f"| {variant} | {s['planned']} | {s['scored']} | {s['successes']} | "
            f"{s['coverage_success_rate']:.1%} | {valid} |"
        )
    lines += [
        "",
        f"成对结果：`{json.dumps(summary['pairs'], ensure_ascii=False)}`",
        "",
        f"结果完整：{summary['complete']}；停止原因：{state.get('stop_reason') or '正常结束'}。",
        "",
        "缺失用量和评分保留为未知，失败与未运行行不从计划分母删除。",
        "",
        "任务未触发记忆机制时，本次结果不能证明长程记忆收益；仿真耗时不外推到原生 Linux。",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines))
    return summary
