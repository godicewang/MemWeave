"""Task-scoped, offline diagnostics from native Session and committed State originals."""

from __future__ import annotations

import hashlib
import json
import math
import tarfile
from itertools import pairwise
from pathlib import Path, PurePosixPath
from statistics import mean, pstdev

WRITE_TOOLS = ("state_append", "modify_fact", "update_goal", "state_remain", "task_create")


def stable_id(*parts) -> str:
    # Match src/storage/identity.ts, including UTF-8 and compact JSON separators.
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
                          .encode()).hexdigest()


def _sessions(paths):
    sessions, errors = [], []
    for path in sorted(set(paths)):
        entries, header, seen = [], {}, {}
        try:
            for line in path.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    if not isinstance(entry, dict):
                        raise TypeError("non-object entry")
                    message = entry.get("message")
                    if message is not None and not isinstance(message, dict):
                        raise TypeError("non-object message")
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        content = message.get("content")
                        if content is not None and not isinstance(content, list):
                            raise TypeError("non-list assistant content")
                    if entry.get("type") == "session":
                        header = entry
                        continue
                    key = entry.get("id")
                    if key is not None and key in seen:
                        if seen[key] != entry:
                            raise ValueError("conflicting entry ID")
                        continue
                    if key is not None:
                        seen[key] = entry
                    entries.append(entry)
                except (ValueError, TypeError):
                    errors.append("invalid_session_entry")
            sessions.append((header, entries, str(path)))
        except (OSError, UnicodeError):
            errors.append("unreadable_session")
    sessions.sort(key=lambda s: (s[0].get("timestamp", ""), s[2]))
    return sessions, errors


def _archive_journals(archive):
    """Read originals without extracting files or synthesizing a runtime store."""
    if archive is None:
        return None
    journals={}
    try:
        with tarfile.open(archive, "r:gz") as source:
            for member in source:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not (member.isdir() or member.isfile()):
                    raise ValueError("unsafe memory archive")
                if not (member.isfile() and path.name == "state.json"):
                    continue
                if len(path.parts) < 4 or path.parts[-3] != "tasks":
                    raise ValueError("unexpected State path")
                task = path.parts[-2]
                if task in journals:raise ValueError('duplicate Task in archive')
                journals[task]=[json.loads(line)for line in source.extractfile(member).read().decode().splitlines()]
        return journals
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tarfile.TarError, EOFError):
        return None


def _reduce_committed(journals):
    operations,active={},0
    try:
        if not isinstance(journals,dict):raise TypeError('Task journal mapping required')
        for task,rows in journals.items():
            if not isinstance(task,str)or not task or not isinstance(rows,list)or not rows:raise ValueError('empty or invalid State')
            entries,counts={},{'fact':0,'decision':0}
            for position,event in enumerate(rows,1):
                op, operation = event["op"], event["op_id"]
                if not isinstance(operation, str) or not operation:
                    raise ValueError("invalid State operation ID")
                key = (task, operation)
                if key in operations:
                    raise ValueError("duplicate State operation")
                if position == 1 and op != "update_goal":
                    raise ValueError("missing initial Goal")
                added = op in ("append_fact", "append_decision", "modify_fact")
                if op == "modify_fact":
                    if not event["archive"]:
                        raise ValueError("empty archive")
                    for identity in event["archive"]:
                        entry = entries[identity]
                        if entry["archived"]:
                            raise ValueError("already archived")
                        entry.update(active=False, archived=True)
                if added:
                    kind = "decision" if op == "append_decision" else "fact"
                    counts[kind] += 1
                    identity = ("D" if kind == "decision" else "F") + str(counts[kind])
                    if op != "modify_fact" and event["id"] != identity:
                        raise ValueError("noncontiguous State IDs")
                    entries[identity] = {"position": position, "active": True, "archived": False}
                elif op == "slide_window":
                    bounds, kept = event["evicted_range"], set(event["retained_ids"])
                    if event["status"] != "committed" or bounds["from"] > bounds["to"]:
                        raise ValueError("invalid State slide")
                    for identity, entry in entries.items():
                        if bounds["from"] <= entry["position"] <= bounds["to"] and identity not in kept:
                            entry["active"] = False
                elif op != "update_goal":
                    raise ValueError("unknown State operation")
                operations[key] = {"op": op, "added": int(added)}
            active += sum(e["active"] and not e["archived"] for e in entries.values())
        return operations, active
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, None


def _committed(archive):
    """Compatibility adapter for existing report/contract readers."""
    journals,_=_select_journals(archive,None)
    return _reduce_committed(journals)


def _select_journals(archives,committed):
    paths=archives if isinstance(archives,list)else[archives]if archives is not None else[]
    candidates=[_archive_journals(p)for p in paths];valid=[v for v in candidates if v is not None]
    def prefix(older,newer):
        return all(task in newer and newer[task][:len(rows)]==rows for task,rows in older.items())
    if committed is not None:
        if not isinstance(committed,dict)or any(not prefix(v,committed)for v in valid):return None,'conflicting_state_originals'
        return committed,'memory_archive'if committed in valid else'terminal_task_registry'
    if not valid or len(valid)!=len(candidates):return None,'missing_or_invalid_state'
    dominant=[v for v in valid if all(prefix(other,v)for other in valid)]
    return (dominant[0],'memory_archive')if dominant else(None,'conflicting_state_originals')


def _uniformity(positions, total, known):
    intervals = [b - a for a, b in pairwise(positions)]
    average = mean(intervals) if intervals else None
    enough = known and len(intervals) >= 2
    head = positions[0] if positions else None
    tail = total - positions[-1] if positions and total is not None else None
    gaps = [v for v in [head, *intervals, tail] if v is not None]
    return {
        "status": "unknown" if not known else "ok" if enough and average else "insufficient_sample",
        "intervals": intervals if known else None,
        "mean_interval": average if known else None,
        "cv": pstdev(intervals) / average if enough and average else None,
        "max_interval": max(intervals) if known and intervals else None,
        "head_calls": head if known else None,
        "tail_calls": tail if known else None,
        "max_observed_gap": max(gaps) if known and gaps else total if known else None,
    }


def task_state_metrics(paths: list[Path], archive: Path | list[Path] | None, *, enabled=True,
                       committed_journals=None,baseline_journals=None,episode_returns=None,
                       require_initial_inventory=False) -> dict:
    sessions, errors = _sessions(paths)
    calls, results, seen_entries = {}, {}, {}
    responses = missing_usage = 0
    for header, entries, path in sessions:
        session = header.get("id")
        namespace = session or path
        by_id = {e.get("id"): e for e in entries if e.get("id") is not None}
        for index, entry in enumerate(entries):
            identity = entry.get("id", f"missing-{index}")
            entry_key = (namespace, identity)
            if entry_key in seen_entries:
                if seen_entries[entry_key] != entry:
                    errors.append("conflicting_session_originals")
                continue
            seen_entries[entry_key] = entry
            message = entry.get("message") or {}
            if message.get("role") == "assistant":
                has_usage = isinstance(message.get("usage"), dict)
                responses += has_usage
                missing_usage += not has_usage
                for part in message.get("content") or []:
                    if not isinstance(part, dict) or part.get("type") != "toolCall":
                        continue
                    if part.get("name") not in WRITE_TOOLS:
                        continue
                    call_id = part.get("id")
                    key = (namespace, identity, call_id)
                    calls[key] = {"name": part["name"], "position": responses if has_usage else None,
                                  "session": session, "assistant": entry.get("id"), "call": call_id,
                                  "arguments": part.get("arguments")}
            elif message.get("role") == "toolResult":
                # Follow native ancestry so reused call IDs on different branches cannot pair.
                parent, visited = entry.get("parentId"), set()
                while parent in by_id and parent not in visited:
                    visited.add(parent)
                    ancestor = by_id[parent]
                    content = (ancestor.get("message") or {}).get("content") or []
                    if isinstance(content, list) and any(
                        isinstance(p, dict) and p.get("type") == "toolCall"
                        and p.get("id") == message.get("toolCallId") for p in content
                    ):
                        results[(namespace, parent, message.get("toolCallId"))] = message.get("isError")
                        break
                    parent = ancestor.get("parentId")
    writes = {}
    for name in WRITE_TOOLS:
        outcomes = [results.get(key) for key, c in calls.items() if c["name"] == name]
        success = sum(o is False for o in outcomes)
        failure = sum(o is True for o in outcomes)
        unknown = len(outcomes) - success - failure
        writes[name] = {"attempts": len(outcomes), "successes": success, "failures": failure,
                        "unknown": unknown,
                        "success_rate": success / len(outcomes) if outcomes and not unknown else None}
    journals,evidence_source=_select_journals(archive,committed_journals)if enabled else(None,'not_applicable')
    operations, active = _reduce_committed(journals) if enabled else (None, None)
    baseline_keys=set()
    if enabled and baseline_journals is not None and operations is not None:
        baseline,_=_reduce_committed(baseline_journals)
        if baseline is None or any(key not in operations or operations[key]!=value for key,value in baseline.items()):
            operations,active=None,None;evidence_source='invalid_initial_inventory'
        else:baseline_keys=set(baseline)
    added = sum(e["added"] for key,e in operations.items()if key not in baseline_keys) if operations is not None else None
    journal_total=sum(e['added']for e in operations.values())if operations is not None else None
    if require_initial_inventory and baseline_journals is None:added=None
    tasks = sorted({task for task, _ in operations}) if operations is not None else []
    located, positions = set(), []
    if operations is not None:
        for call in calls.values():
            if call["name"] not in ("state_append", "modify_fact"):
                continue
            if not all(isinstance(call[k], str) for k in ("session", "assistant", "call")):
                continue
            committed = set()
            for task in tasks:
                operation = stable_id(task, call["session"], call["assistant"], call["call"])
                if call["name"] == "state_append":
                    arguments = call["arguments"]
                    items = arguments.get("items") if isinstance(arguments, dict) else None
                    keys = [(task, stable_id(operation, i)) for i in range(len(items))] if isinstance(items, list) else []
                else:
                    keys = [(task, operation)]
                committed.update(k for k in keys if k in operations and operations[k]["added"])
            committed -= located|baseline_keys
            if committed and call["position"] is not None:
                located.update(committed)
                positions.append(call["position"])
    positions.sort()
    matrix={name:0 for name in ('success_committed','success_not_committed',
        'error_committed','error_not_committed','partial_commit','unknown')}
    for key,call in calls.items():
        if call['name'] not in ('state_append','modify_fact'):
            continue
        receipt=results.get(key)
        if operations is None or type(receipt) is not bool or not all(
            isinstance(call[k],str) for k in ('session','assistant','call')):
            matrix['unknown']+=1
            continue
        items=(call.get('arguments') or {}).get('items') if isinstance(call.get('arguments'),dict) else None
        if call['name']=='state_append' and not isinstance(items,list):
            matrix['unknown']+=1
            continue
        committed_count=0
        expected=len(items) if call['name']=='state_append' else 1
        for task in tasks:
            operation=stable_id(task,call['session'],call['assistant'],call['call'])
            keys=[(task,stable_id(operation,i)) for i in range(expected)] if call['name']=='state_append' else [(task,operation)]
            committed_count+=sum(k in operations for k in keys)
        if 0<committed_count<expected:
            matrix['partial_commit']+=1
        else:
            matrix[('error' if receipt else 'success')+('_committed' if committed_count else '_not_committed')]+=1
    response_scope_consistent=episode_returns is None or responses==episode_returns
    known = bool(paths) and not errors and not missing_usage and response_scope_consistent
    ratio_known = known and added is not None
    ratio = added / responses if ratio_known and responses else None
    ratio_status = ("not_applicable" if not enabled else "unknown" if not ratio_known
                    else "zero_model_responses" if not responses else "too_sparse" if ratio < 0.05
                    else "too_dense" if ratio > 0.10 else "ok")
    return {
        "model_responses_with_usage": responses if paths and not errors and response_scope_consistent else None,
        "session_model_responses_with_usage":responses if paths and not errors else None,
        "model_responses_without_usage": missing_usage if paths and not errors else None,
        "episode_return_scope_consistent":response_scope_consistent,
        "session_counts_status": "missing" if not paths else "observed_partial" if errors else "complete",
        "model_request_attempts": None,
        "request_attempts_status": "unknown_not_recorded_in_session",
        "sample_status": "unknown" if not known else "short_sample" if responses < 20 else "ok",
        "writes": writes if paths and not errors and response_scope_consistent else None,
        "fd_events_added": added, "fd_events_active": active,
        "fd_events_journal_total":journal_total,
        "commit_evidence_source":evidence_source,
        "fd_added_scope":"not_applicable"if not enabled else"episode_delta_from_initial_inventory"if baseline_journals is not None else
            "unknown_initial_inventory"if require_initial_inventory else"final_journal_total_without_initial_baseline",
        "fd_events_located": len(located) if operations is not None else None,
        "fd_write_receipt_commit_matrix": matrix if enabled else None,
        "receipt_commit_scope": 'state_append/modify_fact only; actual journal operations, not tool success or input guesses',
        "state_task_ids": tasks,
        "event_model_ratio": ratio,
        "ratio_status": ratio_status,
        "warnings": ["state_event_ratio_" + ratio_status] if ratio_status in ("too_sparse", "too_dense") else [],
        "write_model_positions": positions if known and added == len(located) else None,
        "uniformity": _uniformity(positions, responses if paths else None,
                                  known and added is not None and added == len(located)),
        "uniformity_distinct_return_positions": _uniformity(sorted(set(positions)), responses if paths else None,
                                  known and added is not None and added == len(located)),
        "source_status": "invalid_session" if errors else "missing_session" if not paths
        else "ambiguous_session_return_scope"if not response_scope_consistent
        else "not_applicable" if not enabled else "missing_or_invalid_state" if operations is None
        else "missing_initial_inventory"if require_initial_inventory and baseline_journals is None
        else "ok",
    }


def metric_columns(metrics):
    """Stable scalar columns for both CSV report formats."""
    uniformity = metrics["uniformity"]
    return {
        "model_responses_with_usage": metrics["model_responses_with_usage"],
        "model_request_attempts": metrics["model_request_attempts"],
        **{name + "_" + k: ((metrics.get("writes") or {}).get(name) or {}).get(k)
           for name in WRITE_TOOLS for k in
           ("attempts", "successes", "failures", "unknown", "success_rate")},
        "fd_events_added": metrics["fd_events_added"],
        "fd_events_active": metrics["fd_events_active"],
        "state_event_model_ratio": metrics["event_model_ratio"],
        "state_ratio_status": metrics["ratio_status"],
        **{"state_write_" + k: uniformity[k] for k in
           ("mean_interval", "cv", "max_interval", "head_calls", "tail_calls")},
    }


def metrics_markdown(rows):
    lines = ["", "## 任务级 State 诊断", "",
             "本节模型量为 Session 中带 usage 的 assistant 返回；HTTP 请求尝试数见工程统计，缺传输轨迹的历史运行才记未知。F/D 为累计落地条目，非批次数。",
             "少于20次返回标短样本；均匀度CV只在至少两个内部间隔时计算，无预设告警阈值。完整定义见实验系统《有价值指标》。",
             "", "| 任务 | 变体 | 模型返回 | append尝试/成功/失败/未知 | 成功率 | 新增F/D | F/D/模型 | 密度 | 样本 | 间隔均值/CV/最大 | 首段/尾段 | 均匀度样本 |",
             "|---|---|---:|---|---:|---:|---:|---|---|---|---|---|"]

    def display(value):
        if value is None:
            return "未知"
        return f"{value:.4g}" if isinstance(value, float) and math.isfinite(value) else str(value)

    for row in rows:
        m = row["state_metrics"]
        a = (m.get("writes") or {}).get("state_append") or {}
        u = m["uniformity"]
        cells = [row.get("display_id", row["task_id"]), row["variant_id"],
                 display(m["model_responses_with_usage"]),
                 "/".join(display(a.get(k)) for k in ("attempts", "successes", "failures", "unknown")),
                 display(a.get("success_rate")), display(m["fd_events_added"]),
                 display(m["event_model_ratio"]),
                 ("⚠ " if m["warnings"] else "") + m["ratio_status"], m["sample_status"],
                 "/".join(display(u[k]) for k in ("mean_interval", "cv", "max_interval")),
                 "/".join(display(u[k]) for k in ("head_calls", "tail_calls")), u["status"]]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    lines += ["", "其他 State 写工具（仅列有尝试的任务；task_create 单列初始 Goal）：", "",
              "| 任务 | 变体 | 工具 | 尝试 | 成功 | 失败 | 未知 | 成功率 |",
              "|---|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        for name, stats in (row["state_metrics"].get("writes") or {}).items():
            if name == "state_append" or not stats["attempts"]:
                continue
            cells = [row.get("display_id", row["task_id"]), row["variant_id"], name,
                     *(display(stats[k]) for k in ("attempts", "successes", "failures", "unknown", "success_rate"))]
            lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
    return lines
