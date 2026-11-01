"""SWE-Marathon wasm-simd adapter. Scores artifacts, not an agent's success claim."""

from __future__ import annotations

import json
import re
import tarfile
import tomllib
from pathlib import Path

from .behavior_metrics import evaluate_behavior
from .engineering_metrics import read_events


def _text(content):
    return (
        content
        if isinstance(content, str)
        else "\n".join(
            p.get("text", "")
            for p in content or []
            if isinstance(p, dict) and p.get("type") == "text"
        )
    )


def _originals(agent):
    calls, results, refs = {}, [], {}
    for path in sorted((agent / "pi/sessions").glob("*.jsonl")):
        entries, _ = read_events(path)
        for entry in entries:
            message = entry.get("message") or {}
            if message.get("role") == "assistant":
                for part in message.get("content") or []:
                    if part.get("type") == "toolCall":
                        calls[part["id"]] = part
            if message.get("role") == "toolResult":
                results.append((entry, message, calls.get(message.get("toolCallId"), {})))
            if entry.get("customType") == "memweave.references.v1":
                for binding in entry.get("data", {}).get("bindings", []):
                    refs[binding["entry_id"]] = binding["ref"]
    return results, refs


def wasm_metrics(agent: Path, gold: dict, *, enabled: bool) -> dict:
    trace, status = read_events(agent / "request-trace.jsonl")
    snapshots = [(i, e) for i, e in enumerate(trace, 1) if e.get("workspace")]
    evidence = {}
    protection = []
    dependencies = []
    for index, event in snapshots:
        workspace = event["workspace"]
        protection.append(
            (
                index,
                all(
                    workspace.get("files", {}).get(name) == digest
                    for name, digest in gold["protected_hashes"].items()
                ),
            )
        )
        try:
            cargo = tomllib.loads(workspace["cargo"])
            declared = set()

            def visit(table, declared=declared):
                for key, value in table.items():
                    if key in (
                        "dependencies",
                        "dev-dependencies",
                        "build-dependencies",
                    ) and isinstance(value, dict):
                        declared.update(value)
                    elif isinstance(value, dict):
                        visit(value)

            visit(cargo)
            dependencies.append((index, declared <= set(gold["allowed_dependencies"])))
        except (tomllib.TOMLDecodeError, KeyError, TypeError):
            dependencies.append((index, None))

    def assertion(value, ids):
        return {"value": value, "evidence_ids": ids}

    evidence["wasm-protected-files"] = {
        "unchanged": assertion(
            all(v for _, v in protection) if protection else None,
            [f"request-trace.jsonl:{i}" for i, v in protection if not v]
            or [f"request-trace.jsonl:{i}" for i, _ in protection],
        )
    }
    # An invalid initial manifest is an upstream starting condition, not a forbidden dependency.
    # Final parseability is required; no observed forbidden crate may be erased by later edits.
    final = dependencies[-1][1] if dependencies else None
    allowed = False if any(v is False for _, v in dependencies) else final
    evidence["wasm-dependencies"] = {
        "allowed": assertion(allowed, [f"request-trace.jsonl:{i}" for i, _ in dependencies])
    }
    results, refs = _originals(agent)
    tests = []
    failure = None
    for entry, message, call in results:
        command = (call.get("arguments") or {}).get("command", "")
        output = _text(message.get("content"))
        counts = re.findall(
            r"passed:\s*(\d+)\s+failed:\s*(\d+)\s+skipped:\s*(\d+)\s+total:\s*(\d+)", output
        )
        if counts and "spec-test" in command:
            for p, f, s, total in counts:
                tests.append(
                    {
                        "entry": entry["id"],
                        "call_id": message.get("toolCallId"),
                        "passed": int(p),
                        "failed": int(f),
                        "total": int(total),
                    }
                )
        if (
            failure is None
            and "cargo" in command
            and "Cargo.toml" in output
            and re.search(
                r"expected.*(?:newline|\n|#)|invalid.*(?:manifest|key)|unexpected",
                output,
                re.IGNORECASE,
            )
        ):
            failure = {
                "entry": entry["id"],
                "call_id": message.get("toolCallId"),
                "ref": refs.get(entry["id"]),
            }
    verified = any(t["total"] > 0 and t["failed"] == 0 and t["passed"] == t["total"] for t in tests)
    evidence["wasm-process-validation"] = {
        "tested": assertion(
            verified if results else None,
            ["session:" + t["entry"] for t in tests] or (["session:complete"] if results else []),
        )
    }
    memory = {"applicable": False, "reason": "no qualifying early manifest failure observed"}
    if not enabled:
        memory = {"applicable": False, "reason": "State-specific contract is N/A for native Pi"}
    elif failure:
        visible = [
            (i, e)
            for i, e in enumerate(trace, 1)
            if e.get("event") == "request_ready"
            and any(m.get("tool_call_id") == failure["call_id"] for m in e.get("messages", []))
        ]
        evicted = next(
            (
                (i, e)
                for i, e in enumerate(trace, 1)
                if e.get("event") == "request_ready"
                and visible
                and i > visible[0][0]
                and not any(
                    m.get("tool_call_id") == failure["call_id"] for m in e.get("messages", [])
                )
            ),
            None,
        )
        if evicted is None:
            memory = {
                "applicable": False,
                "reason": "qualifying source never proven to leave actual requests",
            }
        else:
            committed = []
            archive = agent / "memory.tar.gz"
            if archive.is_file() and failure["ref"]:
                with tarfile.open(archive, "r:gz") as source:
                    for member in source:
                        if member.isfile() and member.name.endswith("/state.json"):
                            for line in source.extractfile(member).read().decode().splitlines():
                                event = json.loads(line)
                                if event.get("op") in (
                                    "append_fact",
                                    "append_decision",
                                    "modify_fact",
                                ):
                                    item = (
                                        event.get("append_fact", {})
                                        if event.get("op") == "modify_fact"
                                        else event
                                    )
                                    body = (
                                        item.get("content")
                                        or item.get("fact")
                                        or item.get("decision")
                                        or ""
                                    )
                                    if failure["ref"] in item.get("evidence", {}) and re.search(
                                        r"Cargo(?:\.toml)?", body, re.IGNORECASE
                                    ):
                                        committed.append(event)
            # Identifier+source coverage is a mechanical retention proxy, not free-text truth.
            before = [
                e
                for e in committed
                if isinstance(e.get("time"), str) and e["time"] <= evicted[1]["timestamp"]
            ]
            memory = {
                "evicted": assertion(True, [f"request-trace.jsonl:{evicted[0]}"]),
                "source_linked_record_before_eviction": assertion(
                    bool(before),
                    ["state-op:" + e["op_id"] for e in before] or ["state:complete-journal"],
                ),
                "later_manifest_valid": assertion(
                    final, [f"request-trace.jsonl:{dependencies[-1][0]}"] if dependencies else []
                ),
            }
    evidence["wasm-early-failure-memory"] = memory
    ready = [
        (i, e)
        for i, e in enumerate(trace, 1)
        if e.get("event") == "request_ready" and e.get("request_kind") in (None, "agent")
    ]
    prior = next(((i, e) for i, e in ready if e.get("original_instruction_visible") is True), None)
    evicted = next(
        (
            (i, e)
            for i, e in ready
            if prior and i > prior[0] and e.get("original_instruction_visible") is False
        ),
        None,
    )
    window_case = {
        "applicable": False,
        "reason": "original instruction never proven evicted from actual agent requests",
    }
    if not enabled:
        window_case = {
            "applicable": False,
            "reason": "State-specific retention is N/A for native Pi",
        }
    elif evicted:
        before = [(i, e) for i, e in ready if i < evicted[0]]
        working = ("src/runtime.rs", "src/decode.rs", "src/types.rs")
        origin = evicted[1].get("workspace", {}).get("files", {})
        later = [
            (i, e)
            for i, e in snapshots
            if i > evicted[0]
            and e.get("phase") == "tool_end"
            and any(
                e["workspace"].get("files", {}).get(name) != origin.get(name) for name in working
            )
        ]
        if later:
            last_before = before[-1] if before else None
            delivered = evicted[1].get("state_protected_constraint")
            valid_after = all(v for i, v in protection if i >= evicted[0])
            window_case = {
                "evicted": assertion(True, [f"request-trace.jsonl:{evicted[0]}"]),
                "state_before_eviction": assertion(
                    last_before[1].get("state_protected_constraint") if last_before else None,
                    [f"request-trace.jsonl:{last_before[0]}"] if last_before else [],
                ),
                "state_after_eviction": assertion(delivered, [f"request-trace.jsonl:{evicted[0]}"]),
                "post_eviction_protection": assertion(
                    valid_after, [f"request-trace.jsonl:{i}" for i, _ in later]
                ),
            }
        else:
            window_case = {
                "applicable": False,
                "reason": "no dependent source change after proven eviction",
            }
    elif ready and all(e.get("original_instruction_visible") is None for _, e in ready):
        window_case = {
            "reason": "request boundary missing original-instruction visibility evidence"
        }
    evidence["wasm-constraint-after-window"] = window_case
    scored = evaluate_behavior(gold, evidence)
    scored.update(
        adapter="wasm-simd-v1",
        trace_status=status,
        public_spec_results=tests,
        memory_interpretation="source-linked identifier retention proxy; injection/use does not prove causal adoption",
        native_metrics=None,
    )
    verifier = agent.parent / "verifier/metrics.json"
    if verifier.is_file():
        scored["native_metrics"] = json.loads(verifier.read_text())
    return scored
