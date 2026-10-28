"""Ready task-pair pipelines; Harbor owns all Trials and environments."""

from __future__ import annotations

import fcntl
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
        ticket = object()
        with self.condition:
            self.waiting.append(ticket)
            try:
                while True:
                    if stopped():
                        raise TimeoutError("campaign stopped while waiting for pair resources")
                    if self.waiting[0] is ticket and all(
                        u + w <= cap
                        for u, w, cap in zip(self.used, weight, self.limits, strict=True)
                    ):
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
    """Continue only when every started model pair has complete primary evidence."""
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
    rows = [r for r in candidates if r["task_id"] not in zero]
    selected = {r["task_id"] for r in catalog["selected"]}
    keys = {(r["task_id"], r["variant_id"]) for r in rows}
    tasks = {r["task_id"] for r in rows}
    if not rows or len(keys) != len(rows) or keys != {(t, v) for t in tasks for v in VARIANTS}:
        raise ValueError("completed parent must contain whole unique pairs")
    if not tasks <= selected or any(
        r.get("solve_status") not in ("completed_patch", "cancelled")
        or not r.get("session_diagnostics", {}).get("model_responses_with_usage")
        for r in rows
    ):
        raise ValueError("completed pair has incomplete solve/primary score/model evidence")
    interrupted = sorted({r["task_id"] for r in rows if r.get("success") is None
                          or r.get("solve_status") == "cancelled"
                          or r.get("retained_interrupted")})
    for row in rows:
        if row["task_id"] in interrupted:
            path = Path(row["solve_source"])
            path = path if path.is_absolute() else parent / path
            if not (path.parent / "agent/model.patch").is_file():
                raise ValueError("interrupted model pair has no captured patch")
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
    for session in parent.glob("groups/*/harbor/solve/*/agent/pi/sessions/*.jsonl"):
        if session.relative_to(parent).parts[1] not in groups:
            raise ValueError("unregistered started model Session")
    cost = summary["estimated_known_cost_usd"]
    amounts = [r.get("peak_estimated_cost_usd") for r in rows]
    if (
        type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0
        or any(type(c) not in (int, float) or not math.isfinite(c) or c < 0 for c in amounts)
        or not math.isclose(sum(amounts), cost, abs_tol=1e-9)
        or not math.isclose(state["estimated_known_cost_usd"], cost, abs_tol=1e-9)
    ):
        raise ValueError("completed parent cost is unknown or unaccounted")
    if spec.limits.max_cost_usd > lock["config"]["limits"]["max_cost_usd"]:
        raise ValueError("cannot enlarge original campaign allowance")
    if cost >= spec.limits.max_cost_usd:
        raise TimeoutError("completed parent has exhausted the shared budget")
    blocks = {
        f["task_id"]: dict(f, inherited_from=str(parent))
        for f in state.get("admission_failures", [])
        if f["phase"] in ("official_image", "official_controls")
    }
    return {
        "kind": "completed_pairs", "parent": str(parent), "known_cost_usd": cost,
        "adapter_equivalence": equivalence,
        "included_keys": [list(k) for k in sorted(keys)], "blocked_admissions": blocks,
        "retained_interrupted_tasks": interrupted,
        "pre_pi_failures": [r for r in candidates if r["task_id"] in zero],
        "window_started_at": state["window_started_at"],
        "window_deadline_at": state["window_deadline_at"],
        "hashes": {
            name: file_digest(parent / name)
            for name in ("experiment.lock.json", "run.json", "live.json", "evidence-index.json")
        },
    }, rows


def pre_pi_failure(parent, row, adapter_sha):
    """Only the audited legacy probe exception proves Pi never launched."""
    if adapter_sha != "67b9481b7e7b9cc08e00b91dfd1855e10ca6825df3ed60c131f85996d79f0192":
        return False
    path = Path(row["solve_source"])
    path = path if path.is_absolute() else parent / path
    if not path.is_file():
        return False
    raw = json.loads(path.read_text())
    error = raw.get("exception_info") or {}
    patch = path.parent / "agent/model.patch"
    return bool(
        error.get("exception_type") == "RuntimeError"
        and error.get("exception_message") == "Pro offline/model-endpoint network probes failed"
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
    legacy = "67b9481b7e7b9cc08e00b91dfd1855e10ca6825df3ed60c131f85996d79f0192"
    replacement = "2599b4fb16c93592eab936942c0ddd7e177ed13eb047d69fe40e745dd0954eed"
    helper = "57a62831b10be9fc29ac7683a225b82f8c92e3585513355769fddc66a2b8aa4b"
    migration = (
        old.get(base + "pi_agent.py") == legacy
        and file_digest(REPOSITORY / (base + "pi_agent.py")) == replacement
        and old.get(base + "network_probe.py") is None
        and file_digest(REPOSITORY / (base + "network_probe.py")) == helper
    )
    for name in ("pi_agent.py", "runtime_cache.py", "runner.py", "images.py", "network_probe.py"):
        if migration and name in ("pi_agent.py", "network_probe.py"):
            continue
        if old.get(base + name) != file_digest(REPOSITORY / (base + name)):
            raise ValueError("Pi/protocol adapter changed since completed phase: " + name)
    return {"reason": "approved Node probe only", "old_pi_sha256": legacy,
            "new_pi_sha256": replacement, "probe_sha256": helper} if migration else None


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


def prepare_pair_runtimes(spec, group, paths, images, cold_lock, check, execute, deadline):
    check()
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


def readiness(spec, row, source):
    """Advisory rank only; actual admission always verifies the complete inputs."""
    env = tomllib.loads((source / "task.toml").read_text()).get("environment", {})
    ref = env.get("docker_image")
    if not ref:
        return 3
    query = subprocess.run(
        ["docker", "image", "inspect", ref], check=False, capture_output=True, text=True, timeout=15
    )
    if query.returncode:
        return 3
    data = json.loads(query.stdout)[0]
    image = {
        "reference": ref,
        "id": data["Id"],
        "platform": data["Os"] + "/" + data["Architecture"],
    }
    ready = software_cached(spec, {row["task_id"]: image})
    return 0 if ready else 1


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
    completed = {r["task_id"] for r in old_rows}
    slots = [r for r in catalog["selected"] if r["task_id"] not in completed]
    inherited_cost = (inherited or {}).get("known_cost_usd", 0)
    budget = spec.limits.max_cost_usd - inherited_cost
    spec.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (spec.root / ".run.lock").open("a") as lease:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another experiment is active") from exc
        now = datetime.now(UTC)
        start = (inherited or preflight or {}).get("window_started_at", now.isoformat())
        window_end = (inherited or preflight or {}).get(
            "window_deadline_at",
            (now + timedelta(seconds=spec.limits.max_elapsed_seconds)).isoformat(),
        )
        remaining = min(
            spec.limits.max_elapsed_seconds,
            (datetime.fromisoformat(window_end) - now).total_seconds(),
        )
        if remaining <= 0:
            raise TimeoutError("original window has ended")
        deadline = time.monotonic() + remaining
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
            "remaining_model_budget_usd": budget,
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
                "plan": campaign_plan(dict(catalog, selected=slots)),
                "pricing": {
                    "currency": "USD",
                    "input_miss": 0.3,
                    "cache_hit": 0.006,
                    "output": 1.2,
                    "unit": "USD/million tokens",
                    "basis": "conservative peak estimate, not billed",
                    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
                    "checked_on": "2026-10-28",
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
        for slot in slots:
            if slot["task_id"] in blocks:
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
                rank[slot["task_id"]] = readiness(spec, actual, source)
            queues = {
                suite: sorted(
                    [r for r in slots if r["suite"] == suite], key=lambda r: rank[r["task_id"]]
                )
                for suite in catalog["sources"]
            }
            ordered = interleave(queues["swe-bench-pro-v2"], queues["terminal-bench-4"])
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
                    )
                finally:
                    pool.release(weight)

            executor = ThreadPoolExecutor(max_workers=spec.execution.concurrency // 2)
            futures = [executor.submit(worker, row) for row in ordered]
            try:
                for future in as_completed(futures):
                    try:
                        future.result()
                    except TimeoutError as exc:
                        with lock:
                            state["stop_reason"] = state["stop_reason"] or str(exc)
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
                and all(t["status"] != "blocked" for t in state["tasks"].values())
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

    # Only a Dockerfile build waits for another build. A cached official image
    # never waits behind an unrelated long build.
    def prepare(source, *args):
        from .images import prepare_task

        definition = tomllib.loads((source / "task.toml").read_text())["environment"]
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
                for v in VARIANTS
            ],
        },
        "tooling_sha256": {
            p.relative_to(upstream).as_posix(): file_digest(p)
            for p in sorted((upstream / "v2/tooling").rglob("*.py"))
        },
    }
    atomic_json(group / "group.lock.json", frozen, immutable=True)

    def verify():
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
    mark("solving")
    stopped = None
    try:
        execute(
            mixed_job(
                pair_spec,
                group,
                paths,
                protocol=protocol,
                runtime_plan=group / "runtime-assets.json",
            ),
            required=False,
        )
    except TimeoutError as exc:
        stopped = exc
    if stopped is None:
        originals = variant_results(group / "harbor/solve")
        for variant in VARIANTS:
            original = originals.get((actual["task_id"], variant))
            if original is None:
                raise ValueError("missing original Pi attempt; no implicit empty answer")
            sessions = list((original[0].parent / "agent/pi/sessions").glob("*.jsonl"))
            diagnostics = session_diagnostics(sessions)
            if not diagnostics or not diagnostics["model_responses_with_usage"]:
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
            source, manifest = replay_handoff(
                group / "harbor/solve", group / "replay-sources" / variant, variant
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
    mark("finished")
    if stopped:
        raise stopped
