"""Resident observation of original evidence; no copied conversation or model requests."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .storage import atomic_json


class LiveObserver:
    def __init__(self, root: Path):
        self.root = root
        self.cursors = {}
        self.seen = set()
        self.sessions = {}
        self.active = {}
        self.peak_solves = 0
        self.last_write = 0
        self.previous = None

    def lines(self, path):
        stat = path.stat()
        key = str(path.relative_to(self.root))
        old = self.cursors.get(key, (stat.st_ino, 0))
        if old[0] != stat.st_ino or stat.st_size < old[1]:
            raise ValueError("observed evidence replaced or truncated: " + key)
        with path.open("rb") as stream:
            stream.seek(old[1])
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line.endswith(b"\n"):
                    break
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise TypeError()
                except (ValueError, TypeError) as exc:
                    raise ValueError("invalid completed observation record: " + key) from exc
                self.cursors[key] = (stat.st_ino, stream.tell())
                yield key, offset, value

    def scan(self):
        lifecycle = []
        for path in sorted(self.root.glob("groups/*/lifecycle/*.jsonl")):
            for key, offset, event in self.lines(path):
                if event.get("purpose") == "solve":
                    lifecycle.append((event.get("timestamp", ""), key, offset, event))
        # Different Jobs append different files. File order can invent an overlap
        # when one Job ended before another started between two observation scans.
        for _timestamp, key, _offset, event in sorted(lifecycle):
            identity = (key, event["trial"])
            if event["event"] == "agent-start":
                self.active[identity] = event["variant"]
            elif event["event"] in ("agent-end", "end", "cancel"):
                self.active.pop(identity, None)
            self.peak_solves = max(self.peak_solves, len(self.active))
        for path in sorted(self.root.glob("groups/*/harbor/*/*/agent/pi/sessions/*.jsonl")):
            key = path.relative_to(self.root).as_posix()
            item = self.sessions.setdefault(
                key,
                {
                    "model_responses": 0,
                    "input": 0,
                    "cacheRead": 0,
                    "output": 0,
                    "native_cost_usd": 0.0,
                    "estimated_cost_usd": 0.0,
                    "tools": Counter(),
                    "tool_errors": 0,
                    "assistant_errors": 0,
                    "compactions": 0,
                },
            )
            for _key, offset, event in self.lines(path):
                identity = (key, event.get("id", offset))
                if identity in self.seen:
                    continue
                self.seen.add(identity)
                message = event.get("message") or {}
                if event.get("type") == "compaction":
                    item["compactions"] += 1
                if message.get("role") == "toolResult" and message.get("isError"):
                    item["tool_errors"] += 1
                if message.get("role") == "assistant":
                    item["assistant_errors"] += message.get("stopReason") in ("error", "aborted")
                    for part in message.get("content") or []:
                        if isinstance(part, dict) and part.get("type") == "toolCall":
                            item["tools"][part["name"]] += 1
                usage = message.get("usage") or event.get("usage")
                if usage is None:
                    continue
                values = [usage.get(k) for k in ("input", "cacheRead", "output")]
                native = (usage.get("cost") or {}).get("total")
                if (
                    any(
                        type(v) not in (int, float) or not math.isfinite(v) or v < 0
                        for v in [*values, native]
                    )
                    or usage.get("cacheWrite", 0) != 0
                ):
                    raise ValueError("unrecognized live usage; cost confidence lost: " + key)
                miss, cached, output = values
                estimate = (miss * 0.3 + cached * 0.006 + output * 1.2) / 1_000_000
                item["model_responses"] += 1
                for field, value in zip(("input", "cacheRead", "output"), values, strict=True):
                    item[field] += value
                item["native_cost_usd"] += native
                item["estimated_cost_usd"] += max(native, estimate)
        return {
            "estimated_cost_usd": sum(s["estimated_cost_usd"] for s in self.sessions.values()),
            "native_cost_usd": sum(s["native_cost_usd"] for s in self.sessions.values()),
            "model_responses": sum(s["model_responses"] for s in self.sessions.values()),
            "active_solves": dict(Counter(self.active.values())),
            "peak_solves": self.peak_solves,
            "sessions": self.sessions,
            "cursors": self.cursors,
        }

    def tick(self, *, force=False):
        status = self.scan()
        # Session counts change frequently, so bound writes while preserving lifecycle changes.
        signature = (status["active_solves"], status["model_responses"])
        now = time.monotonic()
        if force or now - self.last_write >= 15 or signature[0] != (self.previous or ({}, 0))[0]:
            at = datetime.now(UTC).isoformat()
            atomic_json(self.root / "live.json", status | {"observed_at": at})
            event = {
                k: status[k]
                for k in (
                    "estimated_cost_usd",
                    "native_cost_usd",
                    "model_responses",
                    "active_solves",
                    "peak_solves",
                )
            }
            event["observed_at"] = at
            with (self.root / "events.jsonl").open("a") as stream:
                stream.write(json.dumps(event) + "\n")
            with (self.root / "observations.md").open("a") as stream:
                stream.write(
                    f"\n- {at}: solving={status['active_solves']}; "
                    f"responses={status['model_responses']}; "
                    f"estimated=${status['estimated_cost_usd']:.6f}.\n"
                )
            self.last_write, self.previous = now, signature
        return status
