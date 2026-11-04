"""Continuous telemetry from original Pi events and the shared transport boundary."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def quantile(values, probability):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (
        position - lower
    )


def error_class(result):
    content = json.dumps(result, ensure_ascii=False)
    for name, pattern in (
        ("schema", r"INVALID_|schema|missing required|validation"),
        ("permission_path", r"EACCES|EPERM|ENOENT|permission denied|No such file"),
        ("content_match", r"not found|could not find|did not match|not unique"),
        ("conflict", r"CONFLICT|version mismatch|already archived|already committed"),
        ("storage", r"COMMIT|ENOSPC|EIO|write failed"),
        ("timeout_dependency", r"timeout|timed out|ECONN|dependency"),
        ("parse", r"parse|malformed|CORRUPT_|invalid JSON"),
    ):
        if re.search(pattern, content, re.IGNORECASE):
            return name
    return "unclassified"


def read_events(path: Path | None):
    if path is None or not path.is_file():
        return [], "missing"
    values = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                values.append(value)
        except ValueError:
            # pi.txt may include startup text; only JSON objects are execution events.
            continue
    return values, "available"


def task_engineering_metrics(agent: Path) -> dict:
    events, status = read_events(agent / "pi.txt")
    transport, transport_status = read_events(agent / "request-trace.jsonl")
    if transport_status=='available' and not any(e.get('event') in
        ('guard_attached','request_ready','http_attempt','request_denied') for e in transport):
        transport_status='missing_guard_instrumentation'
    tools = defaultdict(
        lambda: {
            "attempts": 0,
            "errors": 0,
            "unknown_results": 0,
            "error_classes": defaultdict(int),
            "durations_ms": [],
        }
    )
    starts = {}
    for event in events:
        kind = event.get("type")
        if kind == "tool_execution_start":
            identity = event.get("toolCallId")
            starts[identity] = event.get("toolName")
            tools[event.get("toolName", "unknown")]["attempts"] += 1
        elif kind == "tool_execution_end":
            identity = event.get("toolCallId")
            name = event.get("toolName") or starts.get(identity, "unknown")
            metric = tools[name]
            if identity not in starts:
                metric["attempts"] += 1
            error = event.get("isError")
            if type(error) is not bool:
                metric["unknown_results"] += 1
            elif error:
                metric["errors"] += 1
                metric["error_classes"][error_class(event.get("result"))] += 1
            elapsed = event.get("durationMs")
            if type(elapsed) in (int, float) and elapsed >= 0:
                metric["durations_ms"].append(elapsed)
            starts.pop(identity, None)
    for name in starts.values():
        tools[name]["unknown_results"] += 1
    for metric in tools.values():
        metric["error_rate"] = (
            metric["errors"] / metric["attempts"]
            if metric["attempts"] and not metric["unknown_results"]
            else None
        )
        values = metric.pop("durations_ms")
        metric["duration_ms"] = {
            "samples": len(values),
            "p50": quantile(values, 0.5),
            "p95": quantile(values, 0.95),
            "max": max(values) if values else None,
        }
        metric["error_classes"] = dict(metric["error_classes"])
    ready = [e for e in transport if e.get("event") == "request_ready"]
    attempts = [e for e in transport if e.get("event") == "http_attempt"]
    ended = [e for e in transport if e.get("event") == "request_end"]
    starts_by_id = {e.get("request_id"): e for e in attempts}
    elapsed = []
    for event in ended:
        start = starts_by_id.get(event.get("request_id"), {})
        try:
            value = (
                datetime.fromisoformat(event["timestamp"])
                - datetime.fromisoformat(start["timestamp"])
            ).total_seconds()
            if value >= 0:
                elapsed.append(value)
        except (KeyError, TypeError, ValueError):
            pass
    resources = [e["process_usage"] for e in ready if isinstance(e.get("process_usage"), dict)]
    return {
        "source_status": status,
        "tools": dict(sorted(tools.items())),
        "transport_source_status": transport_status,
        "http_attempts": len(attempts) if transport_status == "available" else None,
        "request_ready": len(ready) if transport_status == "available" else None,
        "usage_confirmed_attempts": sum(e.get("settled") is True for e in ended)
        if transport_status == "available"
        else None,
        "unknown_charge_attempts": len(attempts) - sum(e.get("settled") is True for e in ended)
        if transport_status == "available"
        else None,
        "request_ready_coverage": len(ready) / len(attempts) if attempts else None,
        "state_delivered_requests": sum(bool(e.get("state_blocks")) for e in ready)
        if ready
        else None,
        "unresolved_template_requests": sum(e.get("unresolved_template") is True for e in ready)
        if ready
        else None,
        "scope": "HTTP attempts include native compaction and provider retries; not assistant-return count",
        "request_wall_seconds": {
            "samples": len(elapsed),
            "p50": quantile(elapsed, 0.5),
            "p95": quantile(elapsed, 0.95),
        },
        "pi_process_cpu_seconds": max(
            (r.get("userCPUTime", 0) + r.get("systemCPUTime", 0) for r in resources), default=0
        )
        / 1_000_000
        if resources
        else None,
        "pi_process_peak_rss_kb": max((r.get("maxRSS", 0) for r in resources), default=None),
        "resource_scope": "Pi process CPU/RSS; child tools require Docker resource samples; payload sizes are bytes, not tokenizer counts",
    }
