"""Continuous telemetry from original Pi events and the shared transport boundary."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def episode_phase_seconds(raw):
    def duration(value):
        try:
            seconds=(datetime.fromisoformat(value['finished_at'])-datetime.fromisoformat(value['started_at'])).total_seconds()
            return seconds if seconds>=0 else None
        except (KeyError,TypeError,ValueError):return None
    result={}
    for phase in ['environment_setup','agent_setup','agent_execution','verifier']:
        if raw.get(phase)is not None:result[phase]=duration(raw[phase]);continue
        values=[duration(s.get(phase))for s in raw.get('step_results')or[]]
        result[phase]=sum(values)if values and all(v is not None for v in values)else None
    return result


def episode_telemetry(events,transport,request_ids):
    """All-stage request timing and per-producer sampled CPU/RSS, not full CPU."""
    ready={e['request_id']:e for e in events if e.get('event')=='request_ready'and e.get('request_id')in request_ids}
    transport_ready={e['request_id']:e for e in transport if e.get('event')=='request_ready'and e.get('request_id')in request_ids}
    resource_complete=set(ready)==set(request_ids)and bool(request_ids);cpu={};rss=[]
    for event in ready.values():
        sample=event if 'process_usage'in event else transport_ready.get(event['request_id'],{})
        resource=sample.get('process_usage')or{};producer=event.get('producer_id')
        values=[resource.get(k)for k in ['userCPUTime','systemCPUTime','maxRSS']]
        valid=isinstance(producer,str)and bool(producer)and all(type(v)in (int,float)and math.isfinite(v)and v>=0 for v in values)
        resource_complete &= valid
        if valid:
            cpu[producer]=max(cpu.get(producer,0),values[0]+values[1]);rss.append(values[2])
    by={};bad=set()
    for event in transport:
        kind=event.get('event');identity=event.get('request_id')
        if kind not in {'http_attempt','request_end'}or identity not in request_ids:continue
        key=identity,kind
        if key in by and by[key]!=event:bad.add(identity)
        by[key]=event
    elapsed=[]
    for identity in request_ids:
        try:
            value=(datetime.fromisoformat(by[identity,'request_end']['timestamp'])-
                datetime.fromisoformat(by[identity,'http_attempt']['timestamp'])).total_seconds()
            if identity not in bad and value>=0:elapsed.append(value)
        except (KeyError,TypeError,ValueError):pass
    full=len(elapsed)==len(request_ids)and bool(request_ids)
    return {'pi_process_cpu_seconds':sum(cpu.values())/1e6 if resource_complete else None,
        'pi_process_peak_rss_kb':max(rss)if resource_complete and rss else None,'resource_producers':len(cpu),
        'request_wall_seconds':{'samples':len(elapsed),'p50':quantile(elapsed,.5)if full else None,
            'p95':quantile(elapsed,.95)if full else None},
        'resource_scope':'All actor request-ready snapshots: sum of each distinct Pi evidence producer maximum observed cumulative CPU; sampled lower bound, excludes child tools and post-last-sample CPU. RSS is observed producer maxRSS in KiB, not an unsampled whole-run peak.'}


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
