"""Frozen task-pair batches. Harbor remains the only Trial/environment scheduler."""

from __future__ import annotations

# Synchronous per-group closures never escape the current loop iteration.
# ruff: noqa: B023
import fcntl
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, model_validator

from .images import TaskPreparationError, prepare_task, verify_prepared_task
from .live import LiveObserver
from .runner import (
    auth_file,
    build_job_config,
    control_ok,
    docker_preflight,
    effective_concurrency,
    image_snapshot,
    prepare_runtimes,
    tool_environment,
    verify_package,
)
from .runtime_cache import snapshot
from .spec import (
    REPOSITORY,
    Digest,
    Execution,
    Identifier,
    Limits,
    Model,
    Runtime,
    StrictModel,
    Subject,
    Suite,
    Variant,
    load_yaml,
    outside_repository,
)
from .storage import atomic_json, check_private_evidence, file_digest
from .suites import resolve_suite, task_digest, task_info

VARIANTS = ("pi-native", "pi-memweave")


class CampaignExecution(Execution):
    platform: Literal["linux/amd64"] = "linux/amd64"
    concurrency: Annotated[int, Field(strict=True, ge=2, le=10)] = 10
    repetitions: Literal[1] = 1


class Campaign(StrictModel):
    schema_version: Literal[2]
    experiment_id: Identifier
    catalog: Path
    catalog_sha256: Digest
    subject: Subject
    runtime: Runtime
    model: Model
    variants: list[Variant]
    execution: CampaignExecution
    limits: Limits
    root: Path

    @model_validator(mode="after")
    def consistent(self):
        if sorted(v.id for v in self.variants) != sorted(VARIANTS):
            raise ValueError("exactly both variants required")
        if self.model.id != "deepseek-flash" or self.model.thinking != "off":
            raise ValueError("this campaign fixes DeepSeek Flash, thinking off and its peak rates")
        self.root = outside_repository(self.root)
        return self


def load_campaign(path: Path) -> Campaign:
    path = path.resolve()
    spec = Campaign.model_validate(load_yaml(path))
    spec.catalog = (path.parent / spec.catalog).resolve()
    spec.subject.package = (path.parent / spec.subject.package.expanduser()).resolve()
    load_catalog(spec)
    return spec


def load_catalog(spec: Campaign) -> dict:
    if file_digest(spec.catalog) != spec.catalog_sha256:
        raise ValueError("frozen catalog checksum mismatch")
    catalog = load_yaml(spec.catalog)
    if catalog.get("catalog_id") != "memweave-long-horizon-49-v1":
        raise ValueError("unknown reviewed catalog")
    selected = catalog["selected"]
    if len(selected) != 49 or len({r["task_id"] for r in selected}) != 49:
        raise ValueError("catalog must contain 49 unique selected tasks")
    counts = {}
    for row in selected:
        if Path(row["task_id"]).name != row["task_id"] or row["task_id"] in (".", ".."):
            raise ValueError("unsafe catalog task ID")
        key = (row["suite"], row["tier"])
        counts[key] = counts.get(key, 0) + 1
        if not row["static_filter_pass"]:
            raise ValueError("unreviewed catalog task")
    expected = {
        (s, t): n for s, tiers in catalog["quota_by_suite"].items() for t, n in tiers.items()
    }
    if counts != expected or sum(counts.values()) != 49:
        raise ValueError("catalog tier quota mismatch")
    for suite_id, source in catalog["sources"].items():
        Suite(
            id=suite_id,
            protocol="tb4" if suite_id == "terminal-bench-4" else "swe-pro-v2",
            **source,
        )
    return catalog


def campaign_plan(catalog):
    return [
        {
            "task_id": row["task_id"],
            "variant_id": variant,
            "repetition": 1,
            "suite_id": row["suite"],
            "tier": row["tier"],
            "display_id": row["display_id"],
            "title": row["title"],
            "memory_relevance": row["memory_relevance"],
            "prior_exposure": row["prior_exposure"],
        }
        for row in catalog["selected"]
        for variant in VARIANTS
    ]


def paired_capacity(requested, tasks, *, cpus, memory_mb):
    trials = effective_concurrency(requested, tasks, cpus=cpus, memory_mb=memory_mb)
    if trials < 2:
        raise ValueError("resources cannot fit an isolated native/plugin task pair")
    return trials // 2


def mixed_job(spec, root, tasks, *, protocol, runtime_plan):
    configs = [
        build_job_config(
            spec,
            root,
            "solve",
            tasks,
            variant=variant,
            auth_path=auth_file(),
            protocol=protocol,
            runtime_plan=runtime_plan,
        )
        for variant in VARIANTS
    ]
    result = configs[0]
    result["agents"] = [cfg["agents"][0] for cfg in configs]
    return result


def variant_results(job: Path):
    result = {}
    for path in sorted(job.glob("*/result.json")):
        raw = json.loads(path.read_text())
        variant = raw.get("config", {}).get("agent", {}).get("kwargs", {}).get("variant")
        if variant not in VARIANTS:
            raise ValueError("source result lacks an unambiguous variant")
        key = (raw["task_name"].split("/")[-1], variant)
        if key in result:
            raise ValueError("ambiguous duplicate task/variant attempt")
        result[key] = (path, raw)
    return result


def replay_handoff(job: Path, destination: Path, variant):
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"variant": variant, "patches": [], "missing": []}
    for (task, v), (path, raw) in variant_results(job).items():
        if v != variant:
            continue
        patch = path.parent / "agent/model.patch"
        if not patch.is_file():
            manifest["missing"].append(task)
            continue
        # Official PatchReplayAgent glob is instance_*/result.json, matching task only.
        target = destination / ("instance_" + path.parent.name.removeprefix("instance_"))
        (target / "agent").mkdir(parents=True)
        shutil.copyfile(path, target / "result.json")
        shutil.copyfile(patch, target / "agent/model.patch")
        manifest["patches"].append(
            {
                "task_id": task,
                "trial_name": raw["trial_name"],
                "source": str(patch),
                "sha256": file_digest(patch),
                "result_sha256": file_digest(path),
                "destination": target.name,
            }
        )
    atomic_json(destination / "handoff.json", manifest, immutable=True)
    return destination, manifest


class ObservationService:
    def __init__(self, root):
        self.root = root
        self.observer = LiveObserver(root)
        self.status = {}
        self.error = None
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self.run, name="campaign-observer", daemon=True)

    def run(self):
        try:
            last_docker = 0
            while not self.halt.is_set():
                self.status = self.observer.tick()
                if time.monotonic() - last_docker >= 15:
                    out = subprocess.check_output(
                        ["docker", "ps", "--format", "{{json .}}"], text=True, timeout=10
                    )
                    atomic_json(
                        self.root / "containers.json",
                        {
                            "observed_at": datetime.now(UTC).isoformat(),
                            "containers": [json.loads(line) for line in out.splitlines()],
                        },
                    )
                    last_docker = time.monotonic()
                self.halt.wait(1)
        except BaseException as exc:  # noqa: BLE001 -- observer must fail closed.
            self.error = type(exc).__name__ + ": " + str(exc)

    def check(self):
        if self.error or not self.thread.is_alive():
            raise ValueError("continuous observation failed: " + str(self.error))
        return self.status.get("estimated_cost_usd", 0)

    def close(self):
        self.halt.set()
        self.thread.join(timeout=12)
        self.status = self.observer.tick(force=True)


def execute_job(config, group_root, env, deadline, budget, service, *, purpose, inference=False):
    from harbor.models.job.config import JobConfig

    JobConfig.model_validate(config)
    if time.monotonic() >= deadline or (inference and service.check() >= budget):
        raise TimeoutError("campaign shared time/cost stop before Job")
    service.check()
    path = group_root / "configs" / (config["job_name"] + ".json")
    atomic_json(path, config, immutable=True)
    console = group_root / "harbor-console" / (config["job_name"] + ".log")
    console.parent.mkdir(parents=True, exist_ok=True)
    with console.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "memweave_eval.harbor_job", str(path), purpose],
            stdout=output,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                cost = service.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError("campaign elapsed-time stop")
                if inference and cost >= budget:
                    raise TimeoutError("campaign estimated-cost stop")
                time.sleep(1)
            return process.returncode
        except BaseException:
            # Harbor cancellation invokes ExperimentPi.finally, preserving the original patch.
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
            raise


def _index(root):
    excluded = {
        "evidence-index.json",
        "summary.json",
        "comparison.csv",
        "report.md",
        "run.json",
        "live.json",
        "containers.json",
        "events.jsonl",
        "observations.md",
    }
    return [
        {"path": p.relative_to(root).as_posix(), "sha256": file_digest(p), "size": p.stat().st_size}
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in excluded
    ]


def run_campaign(spec: Campaign) -> Path:
    if importlib.metadata.version("harbor") != spec.runtime.harbor_version:
        raise ValueError("installed Harbor version mismatch")
    catalog = load_catalog(spec)
    package = verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    dirty = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain", "--", "experiments"], text=True
    )
    if dirty:
        raise ValueError("commit experiment implementation before frozen campaign")
    commit = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    code = {
        p.relative_to(REPOSITORY).as_posix(): file_digest(p)
        for p in sorted((REPOSITORY / "experiments/src").rglob("*.py"))
    }
    spec.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (spec.root / ".run.lock").open("a") as lease:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another experiment is active") from exc
        deadline = time.monotonic() + spec.limits.max_elapsed_seconds
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
        root = spec.root / "runs" / run_id
        root.mkdir(parents=True, mode=0o700)
        print("Campaign evidence: " + str(root), file=sys.stderr, flush=True)
        state = {
            "schema_version": 2,
            "run_id": run_id,
            "jobs": {},
            "groups": [],
            "tasks": {},
            "complete": False,
            "stop_reason": None,
            "started_at": datetime.now(UTC).isoformat(),
        }
        atomic_json(root / "run.json", state)
        atomic_json(
            root / "experiment.lock.json",
            {
                "schema_version": 2,
                "run_id": run_id,
                "config": spec.model_dump(mode="json"),
                "catalog": catalog,
                "experiment_commit": commit,
                "implementation_files": code,
                "package": package,
                "plan": campaign_plan(catalog),
                "pricing": {
                    "currency": "USD",
                    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
                    "checked_on": "2026-10-28",
                    "input_miss": 0.3,
                    "cache_hit": 0.006,
                    "output": 1.2,
                    "unit": "USD/million tokens",
                    "type": "conservative estimate, not billed",
                },
            },
            immutable=True,
        )
        service = ObservationService(root)
        service.thread.start()
        credential = None
        try:
            # Validate every selected official source/hash before the first inference.
            sources, infos = {}, {}
            for suite_id, source in catalog["sources"].items():
                suite = Suite(
                    id=suite_id,
                    protocol="tb4" if suite_id == "terminal-bench-4" else "swe-pro-v2",
                    **source,
                )
                sources[suite_id] = resolve_suite(suite, spec.root / "cache")
            for row in catalog["selected"]:
                path = (
                    sources[row["suite"]]
                    / catalog["sources"][row["suite"]]["tasks_dir"]
                    / row["task_id"]
                )
                info = task_info(path, row["suite"], catalog["resource_filter"])
                if info["sha256"] != row["task_sha256"] or info["reason"]:
                    raise ValueError("catalog task hash/admission changed: " + row["task_id"])
                if file_digest(path / "instruction.md") != row["instruction_sha256"]:
                    raise ValueError("instruction changed")
                infos[row["task_id"]] = info
            atomic_json(root / "selection.json", infos, immutable=True)
            for suite_id in catalog["sources"]:
                upstream = sources[suite_id]
                protocol = "tb4" if suite_id == "terminal-bench-4" else "swe-pro-v2"
                queue = [r for r in catalog["selected"] if r["suite"] == suite_id]
                env = tool_environment(spec, upstream)
                while queue:
                    if time.monotonic() >= deadline or service.check() >= spec.limits.max_cost_usd:
                        raise TimeoutError("campaign shared time/cost stop")
                    # Fit entire pairs; never alter per-task official quotas.
                    candidate = queue[: min(5, len(queue))]
                    capacity = docker_preflight(spec, [infos[r["task_id"]] for r in candidate])
                    pair_count = paired_capacity(
                        spec.execution.concurrency,
                        [infos[r["task_id"]] for r in candidate],
                        cpus=capacity["cpus"],
                        memory_mb=capacity["memory_mb"],
                    )
                    rows, queue = queue[:pair_count], queue[pair_count:]
                    number = len(state["groups"]) + 1
                    gid = f"g{number:02d}"
                    group = root / "groups" / gid
                    group.mkdir(parents=True)
                    group_state = {"jobs": {}, "complete": False}
                    meta = {
                        "id": gid,
                        "suite_id": suite_id,
                        "tasks": [r["task_id"] for r in rows],
                        "status": "preparing",
                    }
                    state["groups"].append(meta)
                    atomic_json(root / "run.json", state)
                    overlay = group / "platform.yaml"
                    overlay.write_text(
                        yaml.safe_dump(
                            {"services": {"main": {"platform": spec.execution.platform}}}
                        )
                    )
                    current_purpose = "official_control"

                    def execute(cfg, *, required=True):
                        cfg["environment"]["extra_docker_compose"] = [str(overlay)]
                        purpose = (
                            "software_preflight"
                            if cfg["job_name"].startswith("runtime-preflight")
                            else current_purpose
                        )
                        state["jobs"][gid + "/" + cfg["job_name"]] = {
                            "path": f"groups/{gid}/harbor/" + cfg["job_name"],
                            "purpose": purpose,
                            "suite_id": suite_id,
                        }
                        atomic_json(root / "run.json", state)
                        result = execute_job(
                            cfg,
                            group,
                            env,
                            deadline,
                            spec.limits.max_cost_usd,
                            service,
                            purpose=purpose,
                            inference=purpose == "solve",
                        )
                        if result and required:
                            raise ValueError("Harbor Job failed: " + gid + "/" + cfg["job_name"])
                        return result

                    preparations, admitted = {}, []
                    for row in rows:
                        service.check()
                        task_id = row["task_id"]
                        source = upstream / catalog["sources"][suite_id]["tasks_dir"] / task_id
                        try:
                            record = prepare_task(
                                source,
                                group,
                                spec.execution.platform,
                                deadline,
                                env,
                                catalog["resource_filter"],
                            )
                        except TaskPreparationError as exc:
                            state["tasks"][task_id] = {
                                "status": "blocked",
                                "phase": "official_image",
                                "reason": str(exc),
                                "group": gid,
                            }
                            atomic_json(root / "run.json", state)
                            continue
                        preparations[task_id] = record
                        admitted.append(row)
                    paths = [group / preparations[r["task_id"]]["runtime_path"] for r in admitted]
                    if paths:
                        group_spec = spec.model_copy(
                            update={
                                "execution": spec.execution.model_copy(
                                    update={
                                        "concurrency": min(
                                            spec.execution.concurrency, len(paths) * 2
                                        )
                                    }
                                )
                            }
                        )
                        for control in ("oracle", "nop"):
                            cfg = build_job_config(
                                group_spec,
                                group,
                                "control-" + control,
                                paths,
                                control=control,
                                protocol=protocol,
                            )
                            execute(cfg, required=False)
                        good = []
                        for row in admitted:
                            tid = row["task_id"]
                            if all(
                                control_ok(group / "harbor" / ("control-" + c), tid, score)
                                for c, score in [("oracle", 1), ("nop", 0)]
                            ):
                                good.append(row)
                                state["tasks"][tid] = {"status": "admitted", "group": gid}
                            else:
                                state["tasks"][tid] = {
                                    "status": "blocked",
                                    "group": gid,
                                    "phase": "official_controls",
                                    "reason": "oracle/nop did not validate",
                                }
                        admitted = good
                    atomic_json(
                        group / "admission.json",
                        {"tasks": {r["task_id"]: state["tasks"][r["task_id"]] for r in rows}},
                        immutable=True,
                    )
                    atomic_json(root / "run.json", state)
                    if not admitted:
                        meta["status"] = "blocked"
                        continue
                    paths = [group / preparations[r["task_id"]]["runtime_path"] for r in admitted]
                    images = image_snapshot(paths)
                    runtimes = prepare_runtimes(
                        group_spec, group, paths, images, group_state, execute, deadline
                    )
                    frozen = {
                        "tasks": admitted,
                        "preparations": preparations,
                        "images": images,
                        "docker": capacity,
                        "runtime_assets": runtimes,
                        "tooling_sha256": {
                            p.relative_to(upstream).as_posix(): file_digest(p)
                            for p in sorted((upstream / "v2/tooling").rglob("*.py"))
                        },
                    }
                    atomic_json(group / "group.lock.json", frozen, immutable=True)

                    def verify():
                        if any(file_digest(REPOSITORY / p) != digest for p, digest in code.items()):
                            raise ValueError("implementation changed during frozen campaign")
                        verify_package(spec.subject.package, spec.subject.sha256)
                        if image_snapshot(paths) != images:
                            raise ValueError("task image changed")
                        if (
                            snapshot(json.loads((group / "runtime-assets.json").read_text()))
                            != runtimes["objects"]
                        ):
                            raise ValueError("frozen runtime objects changed")
                        for r in admitted:
                            tid = r["task_id"]
                            verify_prepared_task(group, preparations[tid])
                            if (
                                task_digest(
                                    upstream / catalog["sources"][suite_id]["tasks_dir"] / tid
                                )
                                != r["task_sha256"]
                            ):
                                raise ValueError("official source changed")

                    verify()
                    env = tool_environment(spec, upstream, inference=True)
                    credential = json.loads(auth_file().read_text())["deepseek"]["key"].encode()
                    current_purpose = "solve"
                    meta["status"] = "solving"
                    atomic_json(root / "run.json", state)
                    stop = None
                    try:
                        execute(
                            mixed_job(
                                group_spec,
                                group,
                                paths,
                                protocol=protocol,
                                runtime_plan=group / "runtime-assets.json",
                            ),
                            required=False,
                        )
                    except TimeoutError as exc:
                        stop = exc
                    if protocol == "swe-pro-v2" and time.monotonic() < deadline:
                        current_purpose = "regrade"
                        meta["status"] = "regrading"
                        for variant in VARIANTS:
                            handoff, manifest = replay_handoff(
                                group / "harbor/solve", group / "replay-sources" / variant, variant
                            )
                            ready = {r["task_id"] for r in manifest["patches"]}
                            grade_paths = [p for p in paths if p.name in ready]
                            if grade_paths:
                                cfg = build_job_config(
                                    group_spec,
                                    group,
                                    "regrade-" + variant,
                                    grade_paths,
                                    source_job=handoff,
                                    protocol=protocol,
                                )
                                execute(cfg, required=False)
                    verify()
                    meta["status"] = "finished"
                    atomic_json(root / "run.json", state)
                    if stop:
                        raise stop
            state["complete"] = all(t.get("status") != "blocked" for t in state["tasks"].values())
        except BaseException as exc:  # noqa: BLE001 -- retain cancelled campaign evidence.
            state["stop_reason"] = type(exc).__name__ + (
                ": " + str(exc) if isinstance(exc, (ValueError, TimeoutError)) else ""
            )
            # Persist partial results and return an incomplete report, without an implicit retry.
        finally:
            try:
                service.close()
            except (ValueError, OSError):
                state["complete"] = False
                state["stop_reason"] = state.get("stop_reason") or "Final observation incomplete"
            state["finished_at"] = datetime.now(UTC).isoformat()
            state["estimated_known_cost_usd"] = service.status.get("estimated_cost_usd")
            atomic_json(root / "run.json", state)
            if credential:
                check_private_evidence(root, credential)
            atomic_json(root / "evidence-index.json", {"files": _index(root)})
            from .campaign_report import generate_campaign_report

            generate_campaign_report(root)
        return root
