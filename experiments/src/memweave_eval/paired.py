"""Ready task-pair pipelines; Harbor owns all Trials and environments."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import math
import subprocess
import threading
import time
import tomllib
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from .campaign import (
    VARIANTS,
    ObservationService,
    _index,
    admit_group,
    campaign_plan,
    execute_job,
    load_catalog,
    mixed_job,
    next_reserve,
    preflight_lineage,
    replay_handoff,
    variant_results,
)
from .images import verify_prepared_task
from .private_runtime import image_libc
from .report import session_diagnostics
from .runner import (
    auth_file,
    build_job_config,
    docker_preflight,
    image_snapshot,
    prepare_runtimes,
    tool_environment,
    verify_package,
)
from .runtime_cache import create_plan, snapshot
from .spec import REPOSITORY, Suite
from .storage import atomic_json, check_private_evidence, file_digest
from .suites import resolve_suite, task_digest, task_info


class ResourcePool:
    """FIFO host quota for whole task pairs, including their possible reserves."""

    def __init__(self, limits):
        self.limits = list(limits)
        self.used = [0, 0, 0]
        self.waiting = []
        self.condition = threading.Condition()

    def acquire(self, weight, stopped):
        if any(w > cap for w, cap in zip(weight, self.limits, strict=True)):
            raise ValueError("official pair envelope exceeds available host resources")
        ticket = (object(), tuple(weight))
        with self.condition:
            self.waiting.append(ticket)
            try:
                while True:
                    if stopped():
                        raise TimeoutError("campaign stopped while waiting for pair resources")
                    fitting = next((t for t in self.waiting if all(
                        u + w <= cap
                        for u, w, cap in zip(self.used, t[1], self.limits, strict=True)
                    )), None)
                    if fitting is ticket:
                        self.used = [u + w for u, w in zip(self.used, weight, strict=True)]
                        return
                    self.condition.wait(0.5)
            finally:
                self.waiting.remove(ticket)
                self.condition.notify_all()

    def release(self, weight):
        with self.condition:
            self.used = [u - w for u, w in zip(self.used, weight, strict=True)]
            if any(x < 0 for x in self.used):
                raise ValueError("unbalanced resource release")
            self.condition.notify_all()

    def update_disk(self, available_mb):
        with self.condition:
            self.limits[2] = available_mb
            self.condition.notify_all()


def pair_weight(row, catalog):
    candidates = [row] + [
        r for r in catalog["reserves"] if (r["suite"], r["tier"]) == (row["suite"], row["tier"])
    ]
    envelopes = [e for r in candidates for e in (r["resources"], r.get("verifier_resources")) if e]
    return tuple(2 * max(e[k] for e in envelopes) for k in ("cpus", "memory_mb", "storage_mb"))


def interleave(swe, tb):
    swe, tb = list(swe), list(tb)
    result, swe = swe[:5], swe[5:]
    while swe or tb:
        if tb:
            result.append(tb.pop(0))
        result.extend(swe[:2])
        swe = swe[2:]
    return result


def bootstrap_info(spec, catalog):
    """Import one healthy completed pair, never its cognitive state or a retry."""
    if spec.completed_parent is not None:
        return completed_info(spec, catalog)
    if spec.bootstrap_parent is None:
        return None, []
    from .campaign_report import generate_campaign_report

    parent = spec.bootstrap_parent.resolve()
    if parent.parent != (spec.root / "runs").resolve() or parent.is_symlink():
        raise ValueError("bootstrap parent must belong to this run root")
    lock = json.loads((parent / "experiment.lock.json").read_text())
    state = json.loads((parent / "run.json").read_text())
    if lock.get("phase") != "bootstrap" or lock.get("bootstrap_lineage"):
        raise ValueError("only the one-pair bootstrap may be imported")
    config = spec.model_dump(mode="json")
    for field in ("catalog_sha256", "subject", "runtime", "model", "variants", "execution"):
        if lock["config"][field] != config[field]:
            raise ValueError("bootstrap identity mismatch: " + field)
    for name in ("pi_agent.py", "runtime_cache.py", "runner.py", "images.py"):
        relative = "experiments/src/memweave_eval/" + name
        if lock["implementation_files"].get(relative) != file_digest(REPOSITORY / relative):
            raise ValueError("Pi/protocol adapter changed since bootstrap: " + name)
    summary = generate_campaign_report(parent)
    expected = {(catalog["selected"][0]["task_id"], v) for v in VARIANTS}
    if (
        not summary["complete"]
        or len(summary["rows"]) != 2
        or {(r["task_id"], r["variant_id"]) for r in summary["rows"]} != expected
        or any(
            r["solve_status"] != "completed_patch"
            or r["success"] is None
            or not r.get("session_diagnostics", {}).get("model_responses_with_usage")
            for r in summary["rows"]
        )
    ):
        raise ValueError("bootstrap must contain one healthy, officially scored real Pi pair")
    cost = summary["estimated_known_cost_usd"]
    amounts = [r.get("peak_estimated_cost_usd") for r in summary["rows"]]
    if (
        type(cost) not in (float, int)
        or not math.isfinite(cost)
        or cost < 0
        or any(type(c) not in (float, int) or not math.isfinite(c) or c < 0 for c in amounts)
        or not math.isclose(sum(amounts), cost, abs_tol=1e-9)
    ):
        raise ValueError("bootstrap cost is unknown")
    if spec.limits.max_cost_usd > lock["config"]["limits"]["max_cost_usd"]:
        raise ValueError("cannot enlarge original campaign allowance")
    if cost >= spec.limits.max_cost_usd:
        raise TimeoutError("bootstrap has exhausted the shared budget")
    info = {
        "parent": str(parent),
        "known_cost_usd": cost,
        "window_started_at": state["window_started_at"],
        "window_deadline_at": state["window_deadline_at"],
        "hashes": {
            name: file_digest(parent / name)
            for name in ("experiment.lock.json", "run.json", "live.json", "evidence-index.json")
        },
    }
    return info, summary["rows"]


def completed_info(spec, catalog):
    """Import indexed originals; all_tasks may complete only a missing side or grade."""
    from .campaign_report import generate_campaign_report

    supplied = spec.completed_parent
    parent = supplied.resolve()
    if supplied.is_symlink() or parent.parent != (spec.root / "runs").resolve():
        raise ValueError("completed parent must belong to this run root")
    lock = json.loads((parent / "experiment.lock.json").read_text())
    state = json.loads((parent / "run.json").read_text())
    if not state.get("finished_at") or lock.get("phase") != "full":
        raise ValueError("completed parent must be a closed full phase")
    config = spec.model_dump(mode="json")
    for field in ("catalog_sha256", "subject", "runtime", "model", "variants", "execution"):
        if lock["config"][field] != config[field]:
            raise ValueError("completed parent identity mismatch: " + field)
    equivalence = verify_adapters(lock)
    summary = generate_campaign_report(parent)
    if summary.get("invalid_evidence"):
        raise ValueError("completed parent has damaged evidence")
    candidates = [r for r in summary["rows"] if r.get("solve_source")]
    zero = set()
    for task in {r["task_id"] for r in candidates}:
        pair = [r for r in candidates if r["task_id"] == task]
        if len(pair) == 2 and all(pre_pi_failure(
            parent, r, lock["implementation_files"]["experiments/src/memweave_eval/pi_agent.py"]
        ) for r in pair):
            zero.add(task)
    zero_keys = {(r["task_id"], r["variant_id"]) for r in candidates
                 if spec.completion_mode == "all_tasks" and pre_pi_failure(
                     parent, r, lock["implementation_files"]["experiments/src/memweave_eval/pi_agent.py"])}
    rows = [r for r in candidates if r["task_id"] not in zero
            and (r["task_id"], r["variant_id"]) not in zero_keys]
    selected = {r["task_id"] for r in catalog["selected"]}
    keys = {(r["task_id"], r["variant_id"]) for r in rows}
    tasks = {r["task_id"] for r in rows}
    if (not rows or len(keys) != len(rows) or
            (spec.completion_mode != "all_tasks" and
             keys != {(t, v) for t in tasks for v in VARIANTS})):
        raise ValueError("completed parent must contain whole unique pairs")
    if not tasks <= selected:
        raise ValueError("completed parent task is outside frozen selection")
    for row in rows:
        validate_started_row(parent, row, interrupted=False)
    interrupted = sorted({r["task_id"] for r in rows if r.get("success") is None
                          or r.get("solve_status") == "cancelled"
                          or r.get("retained_interrupted")})
    for row in rows:
        if row["task_id"] in interrupted:
            validate_started_row(parent, row, interrupted=True)
    groups = set()
    for job in state["jobs"].values():
        if job["purpose"] != "solve":
            continue
        path = Path(job["path"])
        if len(path.parts) != 4 or path.parts[0] != "groups" or path.parts[2:] != ("harbor", "solve"):
            raise ValueError("unknown started model Job path")
        group = path.parts[1]
        groups.add(group)
        bound = {t for t, a in state["tasks"].items() if a.get("group") == group}
        if len(bound) != 1 or not bound <= tasks | zero:
            raise ValueError("started model pair missing complete primary evidence")
        if spec.completion_mode == "all_tasks":
            admission = state["tasks"][next(iter(bound))]
            validate_registered_solve(parent, group, admission.get("actual_task_id", next(iter(bound))))
    for session in parent.glob("groups/*/harbor/solve/*/agent/pi/sessions/*.jsonl"):
        if session.relative_to(parent).parts[1] not in groups:
            raise ValueError("unregistered started model Session")
    cost = summary["estimated_known_cost_usd"]
    history = list(summary.get("historical_attempts", []))
    financial = {}
    for row in rows + history:
        source = Path(row["solve_source"])
        financial[(row["task_id"], row["variant_id"], str(source if source.is_absolute() else parent / source))] = row
    amounts = [r.get("peak_estimated_cost_usd") for r in financial.values()]
    if (
        type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0
        or any(type(c) not in (int, float) or not math.isfinite(c) or c < 0 for c in amounts)
        or not math.isclose(sum(amounts), cost, abs_tol=1e-9)
        or not math.isclose(state["estimated_known_cost_usd"], cost, abs_tol=1e-9)
    ):
        raise ValueError("completed parent cost is unknown or unaccounted")
    if not spec.unlimited_cost and spec.limits.max_cost_usd > lock["config"]["limits"]["max_cost_usd"]:
        raise ValueError("cannot enlarge original campaign allowance")
    if not spec.unlimited_cost and cost >= spec.limits.max_cost_usd:
        raise TimeoutError("completed parent has exhausted the shared budget")
    blocks = {
        f["task_id"]: dict(f, inherited_from=str(parent))
        for f in state.get("admission_failures", [])
        if f["phase"] in ("official_image", "official_controls")
    }
    pending = []
    if spec.completion_mode == "all_tasks":
        rows, pending, past = partition_primary_rows(parent, rows)
        history.extend(past)
        keys = {(r["task_id"], r["variant_id"]) for r in rows}
        interrupted = []
        # Keep an already chosen reserve binding; re-admit other image/control failures.
        replaced = {t for t, a in state["tasks"].items()
                    if a.get("actual_task_id") and a["actual_task_id"] != t}
        blocks = {t: b for t, b in blocks.items() if t in replaced}
    return {
        "kind": "completed_pairs", "parent": str(parent), "known_cost_usd": cost,
        "adapter_equivalence": equivalence,
        "included_keys": [list(k) for k in sorted(keys)], "blocked_admissions": blocks,
        "retained_interrupted_tasks": interrupted,
        "historical_attempts": list({r["solve_source"]: r for r in history}.values()),
        "retained_primary_attempts": pending,
        "pre_pi_failures": list(summary.get("pre_pi_failures", [])) + [
            r for r in candidates if r["task_id"] in zero
            or (r["task_id"], r["variant_id"]) in zero_keys],
        "window_started_at": state["window_started_at"],
        "window_deadline_at": state["window_deadline_at"],
        "hashes": {
            name: file_digest(parent / name)
            for name in ("experiment.lock.json", "run.json", "live.json", "evidence-index.json")
        },
    }, rows



def validate_started_row(parent, row, *, interrupted):
    allowed = {"completed_patch", "cancelled"}
    if row.get("suite_id") == "terminal-bench-4":
        allowed.add("scored")
    if (row.get("solve_status") not in allowed
            or not row.get("session_diagnostics", {}).get("model_responses_with_usage")):
        raise ValueError("completed pair has incomplete solve/primary score/model evidence")
    if interrupted:
        path = Path(row["solve_source"])
        path = path if path.is_absolute() else parent / path
        if row.get("suite_id") == "terminal-bench-4":
            if not path.is_file():
                raise ValueError("interrupted TB pair has no original result")
        elif not (path.parent / "agent/model.patch").is_file():
            raise ValueError("interrupted model pair has no captured patch")


def continuation_plan(plan, scored, pending):
    done = {(r["task_id"], r["variant_id"]) for r in scored}
    score_only = {(r["task_id"], r["variant_id"]) for r in pending}
    return [dict(p, operation="score_only" if (p["task_id"], p["variant_id"]) in score_only
                 else "solve") for p in plan if (p["task_id"], p["variant_id"]) not in done]


def primary_evidence(row):
    path = Path(row["solve_source"])
    group_lock = path.parents[3] / "group.lock.json"
    patch = path.parent / "agent/model.patch"
    if not path.is_absolute() or not group_lock.is_file():
        raise ValueError("retained primary needs its original frozen group")
    return dict(row, result_sha256=file_digest(path),
                patch_sha256=file_digest(patch) if patch.is_file() else None,
                group_lock_sha256=file_digest(group_lock),
                images=json.loads(group_lock.read_text())["images"])


def validate_registered_solve(parent, group, actual_task):
    config = parent / "groups" / group / "configs/solve.json"
    if not config.is_file():
        raise ValueError("registered dispatched solve has no frozen config")
    agents = json.loads(config.read_text())["agents"]
    expected = [(actual_task, a["kwargs"]["variant"]) for a in agents]
    actual = variant_results(parent / "groups" / group / "harbor/solve")
    if (len(expected) != len(set(expected)) or not expected
            or any(v not in VARIANTS for _, v in expected) or set(actual) != set(expected)):
        raise ValueError("registered dispatched solve has missing or unexpected variant results")


def partition_primary_rows(parent, rows):
    """Preserve individual first scores; completed Pro inference only needs grading."""
    kept, pending, history = [], [], []
    for row in rows:
        validate_started_row(parent, row, interrupted=False)
        path = Path(row["solve_source"])
        path = path if path.is_absolute() else parent / path
        record = dict(row, solve_source=str(path),
                      source_run_dir=row.get("source_run_dir", str(parent)))
        if record.get("score_source"):
            record["score_source"] = str(parent / record["score_source"])
        interrupted = (row.get("solve_status") == "cancelled"
                       or row.get("retained_interrupted") or row.get("comparison_eligible") is False)
        if not interrupted and row.get("success") is not None:
            kept.append(record)
        elif not interrupted and row.get("suite_id") == "swe-bench-pro-v2" and row.get("solve_status") == "completed_patch":
            patch = path.parent / "agent/model.patch"
            if not patch.is_file() or not path.is_file():
                raise ValueError("completed primary has no captured patch/result")
            if json.loads(path.read_text()).get("exception_info"):
                raise ValueError("failed inference cannot be resumed as score-only")
            group_lock = path.parents[3] / "group.lock.json"
            record.update(result_sha256=file_digest(path), patch_sha256=file_digest(patch),
                          images=json.loads(group_lock.read_text())["images"] if group_lock.is_file() else None,
                          group_lock_sha256=file_digest(group_lock) if group_lock.is_file() else None)
            pending.append(record)
        else:
            validate_started_row(parent, row, interrupted=True)
            record.update(retained_interrupted=True, comparison_eligible=False)
            history.append(record)
    return kept, pending, history

def pre_pi_failure(parent, row, adapter_sha):
    """Only audited adapters and exact pre-Pi evidence can prove zero inference."""
    legacy = adapter_sha == "67b9481b7e7b9cc08e00b91dfd1855e10ca6825df3ed60c131f85996d79f0192"
    if not legacy and adapter_sha != "0680e465b92628bc7478be41b7cf04b8d5ff3024c6cf0fb2083cbf8bc82c8abf":
        return False
    path = Path(row["solve_source"])
    path = path if path.is_absolute() else parent / path
    if not path.is_file():
        return False
    raw = json.loads(path.read_text())
    error = raw.get("exception_info") or {}
    patch = path.parent / "agent/model.patch"
    probe_path = path.parent / "agent/network-probe.json"
    probe = json.loads(probe_path.read_text()) if probe_path.is_file() else {}
    network_failure = (error.get("exception_message") ==
                       "Pro offline/model-endpoint network probes failed" if legacy else
                       error.get("exception_message") ==
                       "Pro offline/model-endpoint network probes failed; see network-probe.json"
                       and probe.get("passed") is False and probe.get("credential_free") is True
                       and probe.get("checks", {}).get("model", {}).get("ok") is False
                       and probe.get("checks", {}).get("outside", {}).get("ok") is False)
    return bool(
        error.get("exception_type") == "RuntimeError"
        and network_failure
        and not (row.get("session_diagnostics") or {}).get("model_responses_with_usage")
        and row.get("peak_estimated_cost_usd") is None
        and not list((path.parent / "agent").rglob("*.jsonl"))
        and not (path.parent / "agent/pi.txt").exists()
        and patch.is_file() and patch.stat().st_size == 0
        and all(v is None for v in (raw.get("agent_result") or {}).values())
    )


def verify_adapters(lock):
    old = lock["implementation_files"]
    base = "experiments/src/memweave_eval/"
    pinned = {
        "pi_agent.py": "0680e465b92628bc7478be41b7cf04b8d5ff3024c6cf0fb2083cbf8bc82c8abf",
        "runtime_cache.py": "836c83bec3c6babf70e9082027b0a9c8a1101b5cdc83c62a803f2f267450552a",
        "runner.py": "5a753285ba1bbcd5a71002a68d6bbdbad12f6aa49c80d1931c25fa2f8ea2c58c",
        "images.py": "09897b3a1695458476b424b1ef9d73fcae107eed90da6e9983929b33b4d7a90c",
        "network_probe.py": "951263a2a9a7b424f1f833e20f097b286a35f0f033852cc9bf3a9b0fa707fe19",
        "public_archive.py": "c9f479fb64c2aaf821c794113181cee395b2b5844f609d138d3e6a4521bf59be",
        "private_runtime.py": "fc68bb73a39aac027a7263958325e043e480c8222524c19a51f89abd833f1b39",
    }
    current = {base+n: file_digest(REPOSITORY/(base+n)) for n in pinned}
    if all(old.get(path) == digest for path, digest in current.items()):
        return None
    if (all(old.get(base+n) == current[base+n] for n in pinned if n != "images.py")
            and old.get(base+"images.py") == "cd7e5ceecde76b5bd2b4df91f423ff72ff41d5b14117b54b520d9cf0bf90b3f5"
            and current[base+"images.py"] == pinned["images.py"]):
        return {"reason": "approved exact frozen preparation reuse",
                "approval": "user 2026-10-29 environment autonomy; run proposal section 24",
                "old": old.get(base+"images.py"), "current": current[base+"images.py"]}
    if (all(old.get(base+n) == current[base+n] for n in pinned if n != "network_probe.py")
            and old.get(base+"network_probe.py") == "57a62831b10be9fc29ac7683a225b82f8c92e3585513355769fddc66a2b8aa4b"
            and current[base+"network_probe.py"] == pinned["network_probe.py"]):
        return {"reason": "approved bounded credential-free transport retries",
                "approval": "user 2026-10-29 environment autonomy; run proposal section 22",
                "old": old.get(base+"network_probe.py"), "current": current[base+"network_probe.py"]}
    previous = {
        "pi_agent.py": {"67b9481b7e7b9cc08e00b91dfd1855e10ca6825df3ed60c131f85996d79f0192",
                        "2599b4fb16c93592eab936942c0ddd7e177ed13eb047d69fe40e745dd0954eed",
                        "551512dc149c519954a9cbf45394fdc72f6c979552006ad7f1bb7214e37442f6"},
        "runtime_cache.py": {"7cc13d6026e87cc44f5a2ac37d5d235cb63d547381025bca2b71eb6ae93910d2"},
        "runner.py": {"8d73afc35a334d3b4a3bcd9b2943b13b4d79cc3dd0d37d1ebc2b8cd51324dfe5"},
        "images.py": {"7ffc3eacce8481e584f2fa20b49b00e5fcf1bfca5ac8cc0fc901b0daeaf3a1a1", pinned["images.py"]},
        "network_probe.py": {None, "57a62831b10be9fc29ac7683a225b82f8c92e3585513355769fddc66a2b8aa4b", pinned["network_probe.py"]},
        "public_archive.py": {None, pinned["public_archive.py"]},
        "private_runtime.py": {None},
    }
    approved = all(current[base+n] == digest for n, digest in pinned.items()) and all(
        old.get(base+n) in allowed for n, allowed in previous.items())
    if not approved:
        changed = [n for n in pinned if old.get(base+n) != current[base+n]]
        raise ValueError("Pi/protocol adapter changed since completed phase: " + ",".join(changed))
    return {"reason": "approved preparation, Node probe and private musl runtime",
            "approval": "user 2026-10-29 environment autonomy; run proposal section 12",
            "old": {base+n: old.get(base+n) for n in pinned}, "current": current}


def software_cached(spec, images):
    plan = create_plan(spec, images)
    return all(
        (Path(plan["cache"]) / entry[k]["key"] / "manifest.json").is_file()
        for entry in plan["entries"].values()
        for k in ("base", "addon", "models")
    )


def software_writer_busy(spec, images):
    plan = create_plan(spec, images)
    for entry in plan["entries"].values():
        for kind in ("base", "addon", "models"):
            key = entry[kind]["key"]
            cache = Path(plan["cache"])
            if (cache / key / "manifest.json").is_file():
                continue
            path = cache / (key + ".lock")
            if path.exists():
                with path.open("a") as writer:
                    try:
                        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return True
    return False



class PairPreparationError(ValueError):
    """No inference was admitted; retain this image's failure without cancelling peers."""


def prepare_pair_runtimes(spec, group, paths, images, cold_lock, check, execute, deadline):
    check()
    try:
        if software_cached(spec, images):
            return prepare_runtimes(spec, group, paths, images, {"jobs": {}}, execute, deadline)
        while not cold_lock.acquire(timeout=0.5):
            check()
        try:
            check()
            while software_writer_busy(spec, images):
                check()
                time.sleep(0.5)
            return prepare_runtimes(spec, group, paths, images, {"jobs": {}}, execute, deadline)
        finally:
            cold_lock.release()
    except TimeoutError:
        raise
    except Exception as exc:
        check()  # Observation/financial failures must remain campaign-wide.
        raise PairPreparationError(str(exc)) from exc


def ready_order(slots, ranks):
    result = []
    for rank in sorted(set(ranks.values())):
        rows = [r for r in slots if ranks[r["task_id"]] == rank]
        result.extend(interleave([r for r in rows if r["suite"] == "swe-bench-pro-v2"],
                                 [r for r in rows if r["suite"] == "terminal-bench-4"]))
    return result


def readiness(spec, row, source, gid=None):
    """Advisory cache readiness; original builds and complete admission still run."""
    from harbor.models.task.config import TaskConfig
    from harbor.models.task.paths import TaskPaths
    from harbor.models.task.verifier_mode import resolve_verifier_environment_definition

    config = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    definitions = [("main", source / "environment", config.environment)]
    verifier = resolve_verifier_environment_definition(config, TaskPaths(source))
    if verifier is not None and verifier.bundled_tests:
        definitions.append(("verifier", verifier.directory, verifier.config))
    platform = spec.execution.platform if spec is not None else "linux/amd64"
    images = {}
    for role, directory, definition in definitions:
        refs = [definition.docker_image] if definition.docker_image else []
        if not refs and gid:
            context = task_digest(directory)
            key = hashlib.sha256(f"{gid}\0{source.name}\0{role}\0{platform}\0{context}".encode()).hexdigest()
            refs = ["memweave-eval:"+key, "memweave-eval-prewarm:"+key]
        found = None
        for ref in refs:
            query = subprocess.run(["docker", "image", "inspect", ref], check=False,
                                   capture_output=True, text=True, timeout=15)
            if not query.returncode:
                data = json.loads(query.stdout)[0]
                if data["Os"]+"/"+data["Architecture"] == platform:
                    found = {"reference": ref, "id": data["Id"], "platform": platform}
                    break
        if found is None:
            return 3
        key = row["task_id"] + (":verifier" if role == "verifier" else "")
        images[key] = found
    image = images[row["task_id"]]
    image["libc"] = image_libc(image["id"], image["platform"])
    return 0 if software_cached(spec, images) else 1


class PairService(ObservationService):
    def __init__(self, root):
        super().__init__(root)
        self.fatal = threading.Event()

    def check(self):
        if self.fatal.is_set():
            raise TimeoutError("campaign globally cancelled")
        return super().check()

    def check_grading(self):
        return super().check()


def run_pairs(spec):
    if importlib.metadata.version("harbor") != spec.runtime.harbor_version:
        raise ValueError("Harbor version mismatch")
    catalog = load_catalog(spec)
    preflight, blocks = preflight_lineage(spec)
    inherited, old_rows = bootstrap_info(spec, catalog)
    blocks.update((inherited or {}).get("blocked_admissions", {}))
    package = verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    if subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain", "--", "experiments"], text=True
    ):
        raise ValueError("commit experiment implementation before frozen run")
    commit = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    code = {
        p.relative_to(REPOSITORY).as_posix(): file_digest(p)
        for p in sorted((REPOSITORY / "experiments/src").rglob("*.py"))
    }
    pending_primary = (inherited or {}).get("retained_primary_attempts", [])
    completed = {r["task_id"] for r in old_rows
                 if {x["variant_id"] for x in old_rows if x["task_id"] == r["task_id"]} == set(VARIANTS)}
    slots = [r for r in catalog["selected"] if r["task_id"] not in completed]
    inherited_cost = (inherited or {}).get("known_cost_usd", 0)
    budget = math.inf if spec.unlimited_cost else spec.limits.max_cost_usd - inherited_cost
    spec.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (spec.root / ".run.lock").open("a") as lease:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another experiment is active") from exc
        now = datetime.now(UTC)
        start, window_end, deadline = campaign_window(spec, inherited or preflight or {}, now)
        run_id = now.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
        root = spec.root / "runs" / run_id
        root.mkdir(parents=True, mode=0o700)
        print("Campaign evidence: " + str(root), flush=True)
        state = {
            "schema_version": 2,
            "run_id": run_id,
            "jobs": {},
            "groups": [],
            "tasks": {},
            "admission_failures": [],
            "started_at": now.isoformat(),
            "complete": False,
            "stop_reason": None,
            "window_started_at": start,
            "window_deadline_at": window_end,
            "inherited_model_cost_usd": inherited_cost,
            "remaining_model_budget_usd": budget if math.isfinite(budget) else None,
        }
        atomic_json(root / "run.json", state)
        atomic_json(
            root / "experiment.lock.json",
            {
                "schema_version": 2,
                "phase": "full",
                "run_id": run_id,
                "config": spec.model_dump(mode="json"),
                "catalog": catalog,
                "experiment_commit": commit,
                "implementation_files": code,
                "package": package,
                "preflight_lineage": preflight,
                "bootstrap_lineage": inherited,
                "full_plan": campaign_plan(catalog),
                "plan": continuation_plan(campaign_plan(dict(catalog, selected=slots)), old_rows, pending_primary),
                "pricing": {
                    "currency": "USD",
                    "input_miss": 0.3,
                    "cache_hit": 0.006,
                    "output": 1.2,
                    "unit": "USD/million tokens",
                    "basis": "conservative peak estimate, not billed",
                    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
                    "checked_on": "2026-10-29",
                },
            },
            immutable=True,
        )
        service = PairService(root)
        service.thread.start()
        lock = threading.RLock()
        build_lock = threading.Lock()
        cold_lock = threading.Lock()
        used_reserves = {
            r["actual_task_id"] for r in old_rows if r["actual_task_id"] != r["task_id"]
        }
        bindings = {}
        for row in old_rows + pending_primary:
            if row["task_id"] not in completed and row["actual_task_id"] != row["task_id"]:
                bindings[row["task_id"]] = next(r for r in catalog["reserves"]
                                                if r["task_id"] == row["actual_task_id"])
        for slot in slots:
            if slot["task_id"] in blocks and slot["task_id"] not in bindings:
                reserve = next_reserve(catalog, slot, used_reserves)
                if reserve:
                    bindings[slot["task_id"]] = reserve
        credential = None
        try:
            sources, infos = {}, {}
            for suite_id, source in catalog["sources"].items():
                sources[suite_id] = resolve_suite(
                    Suite(
                        id=suite_id,
                        protocol="tb4" if suite_id == "terminal-bench-4" else "swe-pro-v2",
                        **source,
                    ),
                    spec.root / "cache",
                )
            for row in catalog["selected"] + catalog["reserves"]:
                source = (
                    sources[row["suite"]]
                    / catalog["sources"][row["suite"]]["tasks_dir"]
                    / row["task_id"]
                )
                info = task_info(source, row["suite"], catalog["resource_filter"])
                if (
                    info["reason"]
                    or info["sha256"] != row["task_sha256"]
                    or file_digest(source / "instruction.md") != row["instruction_sha256"]
                ):
                    raise ValueError("official task identity changed: " + row["task_id"])
                infos[row["task_id"]] = info
            atomic_json(root / "selection.json", infos, immutable=True)
            pair_spec = spec.model_copy(
                update={"execution": spec.execution.model_copy(update={"concurrency": 2})}
            )
            capacity = docker_preflight(pair_spec, [infos[slots[0]["task_id"]]])
            pool = ResourcePool(
                (capacity["cpus"], capacity["memory_mb"] - 512, capacity["available_disk_mb"] - 512)
            )
            rank = {}
            for slot in slots:
                actual = bindings.get(slot["task_id"], slot)
                source = (
                    sources[actual["suite"]]
                    / catalog["sources"][actual["suite"]]["tasks_dir"]
                    / actual["task_id"]
                )
                ordinal = next(i for i, r in enumerate(catalog["selected"], 1)
                               if r["task_id"] == slot["task_id"])
                rank[slot["task_id"]] = readiness(spec, actual, source, f"g{ordinal:02d}")
            ordered = ready_order(slots, rank)
            atomic_json(
                root / "schedule.lock.json",
                {
                    "task_order": [r["task_id"] for r in ordered],
                    "readiness_rank": rank,
                    "resource_capacity": capacity,
                    "max_pair_workers": spec.execution.concurrency // 2,
                    "reserved_replacements": bindings,
                },
                immutable=True,
            )
            credential = json.loads(auth_file().read_text())["deepseek"]["key"].encode()

            def stopped():
                return (
                    service.fatal.is_set()
                    or time.monotonic() >= deadline
                    or service.check() >= budget
                )

            def worker(slot):
                if stopped():
                    raise TimeoutError("shared time/cost stop before next pair")
                weight = pair_weight(slot, catalog)
                available = docker_preflight(pair_spec, [infos[slot["task_id"]]])
                pool.update_disk(available["available_disk_mb"] - 512)
                pool.acquire(weight, stopped)
                try:
                    if stopped():
                        raise TimeoutError("shared time/cost stop")
                    return _pair(
                        spec,
                        pair_spec,
                        catalog,
                        slot,
                        sources,
                        infos,
                        root,
                        state,
                        lock,
                        build_lock,
                        cold_lock,
                        service,
                        deadline,
                        budget,
                        blocks,
                        used_reserves,
                        bindings,
                        capacity,
                        code,
                        old_rows + pending_primary,
                    )
                finally:
                    pool.release(weight)

            executor = ThreadPoolExecutor(max_workers=spec.execution.concurrency // 2)
            futures = {executor.submit(worker, row): row for row in ordered}
            try:
                for future in as_completed(futures):
                    try:
                        future.result()
                    except TimeoutError as exc:
                        with lock:
                            state["stop_reason"] = state["stop_reason"] or str(exc)
                    except PairPreparationError as exc:
                        if spec.completion_mode != "all_tasks":
                            service.fatal.set()
                            state["stop_reason"] = str(exc)
                        with lock:
                            task = futures[future]["task_id"]
                            state["tasks"].setdefault(task, {}).update(
                                status="preparation_failed", preparation_error=str(exc))
                            for group in state["groups"]:
                                if task in group["tasks"]:
                                    group["status"] = "preparation_failed"
                            atomic_json(root / "run.json", state)
                    except Exception as exc:  # noqa: BLE001 -- shared pipeline must fail closed.
                        service.fatal.set()
                        with lock:
                            state["stop_reason"] = type(exc).__name__ + (
                                ": " + str(exc) if isinstance(exc, ValueError) else ""
                            )
            except BaseException:
                service.fatal.set()
                raise
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            state["complete"] = (
                not state["stop_reason"]
                and len(state["tasks"]) == len(slots)
                and len(state["groups"]) == len(slots)
                and all(g["status"] == "finished" for g in state["groups"])
            )
        except BaseException as exc:  # noqa: BLE001 -- preserve partial official results.
            state["stop_reason"] = state["stop_reason"] or type(exc).__name__ + (
                ": " + str(exc) if isinstance(exc, (ValueError, TimeoutError)) else ""
            )
        finally:
            try:
                service.close()
            except (ValueError, OSError):
                state["stop_reason"] = state["stop_reason"] or "final observation failed"
                state["complete"] = False
            state["finished_at"] = datetime.now(UTC).isoformat()
            state["estimated_known_cost_usd"] = inherited_cost + service.status.get(
                "estimated_cost_usd", 0
            )
            atomic_json(root / "run.json", state)
            if credential:
                check_private_evidence(root, credential)
            atomic_json(root / "evidence-index.json", {"files": _index(root)})
            from .campaign_report import generate_campaign_report

            generate_campaign_report(root)
        return root


def campaign_window(spec, inherited, now):
    start = inherited.get("window_started_at", now.isoformat())
    if spec.completion_mode == "all_tasks":
        return start, None, math.inf
    end = inherited.get("window_deadline_at") or (
        now + timedelta(seconds=spec.limits.max_elapsed_seconds)
    ).isoformat()
    remaining = min(spec.limits.max_elapsed_seconds,
                    (datetime.fromisoformat(end) - now).total_seconds())
    if remaining <= 0:
        raise TimeoutError("original window has ended")
    return start, end, time.monotonic() + remaining


def _pair(
    spec,
    pair_spec,
    catalog,
    slot,
    sources,
    infos,
    root,
    state,
    state_lock,
    build_lock,
    cold_lock,
    service,
    deadline,
    budget,
    blocks,
    used_reserves,
    bindings,
    capacity,
    code,
    inherited_rows=(),
):
    suite_id = slot["suite"]
    upstream = sources[suite_id]
    protocol = "tb4" if suite_id == "terminal-bench-4" else "swe-pro-v2"
    ordinal = next(
        i for i, r in enumerate(catalog["selected"], 1) if r["task_id"] == slot["task_id"]
    )
    gid = f"g{ordinal:02d}"
    group = root / "groups" / gid
    group.mkdir(parents=True)
    meta = {"id": gid, "suite_id": suite_id, "tasks": [slot["task_id"]], "status": "preparing"}
    with state_lock:
        state["groups"].append(meta)
        atomic_json(root / "run.json", state)
    env = tool_environment(spec, upstream)
    overlay = group / "platform.yaml"
    overlay.write_text(
        yaml.safe_dump({"services": {"main": {"platform": spec.execution.platform}}})
    )

    def mark(status):
        with state_lock:
            meta["status"] = status
            atomic_json(root / "run.json", state)

    def execute(cfg, *, required=True):
        name = cfg["job_name"]
        purpose = (
            "software_preflight"
            if name.startswith("runtime-preflight")
            else "solve"
            if name == "solve"
            else "regrade"
            if name.startswith("regrade")
            else "official_control"
        )
        cfg["environment"]["extra_docker_compose"] = [str(overlay)]
        with state_lock:
            state["jobs"][gid + "/" + name] = {
                "path": f"groups/{gid}/harbor/" + name,
                "purpose": purpose,
                "suite_id": suite_id,
            }
            atomic_json(root / "run.json", state)
        code = execute_job(
            cfg,
            group,
            env,
            deadline,
            budget,
            service,
            purpose=purpose,
            inference=purpose == "solve",
        )
        if code and required:
            raise ValueError("Harbor Job failed: " + gid + "/" + name)
        return code

    from .campaign_report import retained_original

    inherited_primary = [primary_evidence(r) for r in inherited_rows
                         if r["task_id"] == slot["task_id"]]
    frozen = {}
    for record in inherited_primary:
        original_path, _ = retained_original(root, record)
        original_lock = json.loads((original_path.parents[3] / "group.lock.json").read_text())
        tid = record["actual_task_id"]
        preparation = original_lock["preparations"][tid]
        if tid in frozen and frozen[tid] != preparation:
            raise ValueError("partial continuation has conflicting frozen preparations")
        frozen[tid] = preparation

    # Only a Dockerfile build waits for another build. A cached official image
    # never waits behind an unrelated long build.
    def prepare(source, *args):
        from .images import prepare_task

        definition = tomllib.loads((source / "task.toml").read_text())["environment"]
        if source.name in frozen:
            return prepare_task(source, *args, frozen=frozen[source.name])
        if definition.get("docker_image"):
            return prepare_task(source, *args)
        with build_lock:
            return prepare_task(source, *args)

    admitted, preparations = admit_group(
        [slot],
        catalog=catalog,
        spec=pair_spec,
        upstream=upstream,
        group=group,
        state=state,
        execute=execute,
        env=env,
        deadline=deadline,
        prior_blocks=blocks,
        used_reserves=used_reserves,
        service=service,
        docker=capacity,
        state_lock=state_lock,
        reserve_bindings=bindings,
        prepare=prepare,
    )
    if not admitted:
        mark("blocked")
        return
    actual = admitted[0]
    paths = [group / preparations[actual["task_id"]]["runtime_path"]]
    docker = docker_preflight(pair_spec, [infos[actual["task_id"]]], preparations)
    images = image_snapshot(paths)
    old_originals = {}
    for record in inherited_primary:
        if record["actual_task_id"] != actual["task_id"]:
            raise ValueError("partial continuation changed the actual task/reserve")
        path, raw = retained_original(root, record)
        if {k: (v["id"], v["platform"]) for k, v in record["images"].items()} != {
                k: (v["id"], v["platform"]) for k, v in images.items()}:
            raise ValueError("partial continuation changed the original task image")
        old_originals[(actual["task_id"], record["variant_id"])] = (path, raw)
    scored_variants = {r["variant_id"] for r in inherited_primary if r.get("success") is not None}
    new_variants = [v for v in VARIANTS if (actual["task_id"], v) not in old_originals]
    mark("software_preflight")

    def check_preparation():
        if time.monotonic() >= deadline or service.check() >= budget:
            raise TimeoutError("shared time/cost stop during software preparation")

    runtime = prepare_pair_runtimes(
        pair_spec, group, paths, images, cold_lock, check_preparation, execute, deadline
    )
    frozen = {
        "tasks": admitted,
        "preparations": preparations,
        "images": images,
        "runtime_assets": runtime,
        "inherited_primary": inherited_primary,
        "docker": docker,
        "actual_plan": {
            "revision": gid,
            "scope": "pair_before_inference",
            "plan": [
                {
                    "slot_task_id": slot["task_id"],
                    "task_id": actual["task_id"],
                    "variant_id": v,
                    "repetition": 1,
                }
                for v in new_variants
            ],
        },
        "tooling_sha256": {
            p.relative_to(upstream).as_posix(): file_digest(p)
            for p in sorted((upstream / "v2/tooling").rglob("*.py"))
        },
    }
    atomic_json(group / "group.lock.json", frozen, immutable=True)

    def verify():
        for record in inherited_primary:
            retained_original(root, record)
        if any(file_digest(REPOSITORY / p) != digest for p, digest in code.items()):
            raise ValueError("implementation changed during frozen run")
        verify_package(spec.subject.package, spec.subject.sha256)
        if image_snapshot(paths) != images:
            raise ValueError("task image changed")
        if snapshot(json.loads((group / "runtime-assets.json").read_text())) != runtime["objects"]:
            raise ValueError("frozen software cache changed")
        verify_prepared_task(group, preparations[actual["task_id"]])
        if (
            task_digest(upstream / catalog["sources"][suite_id]["tasks_dir"] / actual["task_id"])
            != actual["task_sha256"]
        ):
            raise ValueError("official task changed")

    verify()
    env = tool_environment(spec, upstream, inference=True)
    mark("solving" if new_variants else "regrading")
    stopped = None
    try:
        if new_variants:
            cfg = mixed_job(
                pair_spec,
                group,
                paths,
                protocol=protocol,
                runtime_plan=group / "runtime-assets.json",
            )
            cfg["agents"] = [a for a in cfg["agents"] if a["kwargs"]["variant"] in new_variants]
            execute(cfg, required=False)
    except TimeoutError as exc:
        stopped = exc
    originals = variant_results(group / "harbor/solve") | old_originals
    pre_pi_failed = []
    if stopped is None:
        for variant in new_variants:
            original = originals.get((actual["task_id"], variant))
            if original is None:
                raise ValueError("missing original Pi attempt; no implicit empty answer")
            sessions = list((original[0].parent / "agent/pi/sessions").glob("*.jsonl"))
            diagnostics = session_diagnostics(sessions)
            if not diagnostics or not diagnostics["model_responses_with_usage"]:
                if spec.completion_mode == "all_tasks" and pre_pi_failure(root, {
                    "solve_source": str(original[0]), "session_diagnostics": diagnostics,
                    "peak_estimated_cost_usd": None,
                }, file_digest(REPOSITORY / "experiments/src/memweave_eval/pi_agent.py")):
                    pre_pi_failed.append(variant)
                    continue
                raise ValueError("Pi produced no model evidence; check shared setup/authentication")
            if (
                protocol == "swe-pro-v2"
                and not (original[0].parent / "agent/network-probe.json").is_file()
            ):
                raise ValueError("Pro network-policy evidence missing")
    if protocol == "swe-pro-v2" and time.monotonic() < deadline:
        mark("regrading")
        replays = []
        for variant in VARIANTS:
            if variant in scored_variants or variant in pre_pi_failed:
                continue
            original = originals.get((actual["task_id"], variant))
            if original is None:
                continue
            source, manifest = replay_handoff(
                original[0].parents[1], group / "replay-sources" / variant, variant
            )
            if manifest["patches"]:
                replays.append(
                    build_job_config(
                        pair_spec,
                        group,
                        "regrade-" + variant,
                        paths,
                        source_job=source,
                        protocol=protocol,
                    )
                )
        if len(replays) == 2:
            cfg = replays[0]
            cfg["job_name"] = "regrade"
            cfg["agents"] = [job["agents"][0] for job in replays]
            execute(cfg, required=False)
        elif replays:
            execute(replays[0], required=False)
    verify()
    mark("incomplete" if pre_pi_failed else "finished")
    if stopped:
        raise stopped
