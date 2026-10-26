"""Frozen experiment orchestration; Harbor owns every Trial and its environment."""

from __future__ import annotations

import fcntl
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml

from .report import generate_report
from .spec import REPOSITORY, Experiment, Subset, Suite
from .storage import atomic_json, check_private_evidence, evidence_index, file_digest
from .suites import resolve_suite, select_tasks, task_digest


def effective_concurrency(
    requested: int, selected: list[dict], *, cpus: int, memory_mb: int
) -> int:
    # Reserve room for Docker and Harbor's official network sidecar.
    largest_cpu = max(t["resources"]["cpus"] for t in selected)
    largest_memory = max(t["resources"]["memory_mb"] for t in selected)
    result = min(requested, cpus // largest_cpu, max(0, memory_mb - 512) // largest_memory)
    if result < 1:
        raise ValueError("official task resource envelope exceeds Docker capacity")
    return result


def image_snapshot(paths: list[Path]) -> dict:
    """Record actual local image identities after controls, without editing task definitions."""
    import tomllib

    from harbor.environments.definition import environment_content_hash

    result = {}
    for path in paths:
        environment = tomllib.loads((path / "task.toml").read_text())["environment"]
        name = environment.get("docker_image") or "hb__" + environment_content_hash(
            path / "environment"
        )
        info = json.loads(
            subprocess.check_output(["docker", "image", "inspect", name], text=True, timeout=30)
        )[0]
        result[path.name] = {
            "reference": name,
            "id": info["Id"],
            "repo_digests": info.get("RepoDigests", []),
            "platform": info["Os"] + "/" + info["Architecture"],
        }
    return result


def verify_package(path: Path, expected: str, commit: str | None = None) -> dict:
    if file_digest(path) != expected:
        raise ValueError("MemWeave archive checksum mismatch")
    with tarfile.open(path, "r:gz") as archive:
        files = {}
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or name.parts[0] != "package"
            ):
                raise ValueError("unsafe package path")
            if member.isdir():
                continue
            if not member.isfile() or member.name in files:
                raise ValueError("unsupported or duplicate archive member")
            relative = name.relative_to("package").as_posix()
            if any(
                part in {"auth.json", ".env", "AGENTS.md", "node_modules", ".git", "docs", "tests"}
                for part in name.parts
            ):
                raise ValueError("private or development file in package")
            content = archive.extractfile(member).read()
            if commit:
                original = subprocess.run(
                    ["git", "-C", str(REPOSITORY), "show", f"{commit}:{relative}"],
                    capture_output=True,
                    check=True,
                ).stdout
                if content != original:
                    raise ValueError(f"archive differs from frozen Git source: {relative}")
            files[member.name] = content
    for required in (
        "package/package.json",
        "package/src/extension/index.ts",
        "package/resources/rule.md",
    ):
        if required not in files:
            raise ValueError(f"package is missing {required}")
    metadata = json.loads(files["package/package.json"])
    if metadata.get("name") != "@godice/memweave" or metadata.get("pi", {}).get("extensions") != [
        "./src/extension/index.ts"
    ]:
        raise ValueError("not the normal MemWeave production package")
    return {"name": metadata["name"], "version": metadata["version"], "sha256": expected}


def build_job_config(
    spec: Experiment,
    run_root: Path,
    name: str,
    tasks: list[Path],
    *,
    variant: str | None = None,
    auth_path: Path | None = None,
    protocol="tb4",
    control: str | None = None,
    source_job: Path | None = None,
) -> dict:
    if control:
        agent = {"name": control}
    elif source_job:
        agent = {
            "import_path": "patch_replay:PatchReplayAgent",
            "model_name": "replay",
            "kwargs": {"source_job": str(source_job)},
        }
    else:
        agent = {
            "import_path": "memweave_eval.pi_agent:ExperimentPi",
            "model_name": f"{spec.model.provider}/{spec.model.id}",
            "extra_allowed_hosts": ["api.deepseek.com"],
            "kwargs": {
                "version": spec.runtime.pi_version,
                "node_version": spec.runtime.node_version,
                "variant": variant,
                "package_path": str(spec.subject.package),
                "package_sha256": spec.subject.sha256,
                "auth_path": str(auth_path),
                "protocol": protocol,
                "thinking": spec.model.thinking,
            },
        }
    cfg = {
        "job_name": name,
        "jobs_dir": str(run_root / "harbor"),
        "n_attempts": 1,
        "n_concurrent_trials": spec.execution.concurrency,
        "quiet": True,
        "retry": {"max_retries": 0},
        "environment": {"type": "docker", "delete": True},
        "agents": [agent],
        "tasks": [{"path": str(t)} for t in tasks],
    }
    if protocol == "swe-pro-v2" and not control and source_job is None:
        cfg["verifier"] = {"disable": True}
    return cfg


def tool_environment(spec: Experiment, upstream: Path, *, inference=False) -> dict:
    # Do not offer unrelated host credentials to public tasks or Harbor's env resolver.
    names = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "TMPDIR",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    )
    env = {k: os.environ[k] for k in names if k in os.environ}
    # Only the main task service gets the explicit platform overlay. Harbor builds
    # its egress helper for the daemon ISA; a global platform would break that helper.
    env.update(HARBOR_TELEMETRY="0", DO_NOT_TRACK="1")
    own_source = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join([own_source, str(upstream / "v2/tooling")])
    if inference:
        auth = json.loads(auth_file().read_text())
        entry = auth.get("deepseek", {})
        if (
            entry.get("type") != "api_key"
            or not isinstance(entry.get("key"), str)
            or not entry["key"]
        ):
            raise ValueError("DeepSeek API-key auth profile unavailable")
        # Pi reads its private auth.json. Never put a key in Docker exec env/argv.
    return env


def auth_file() -> Path:
    return Path.home() / ".local/share/memweave-dev/pi-agent/auth.json"


def observed_cost(root: Path) -> float:
    """Read completed native usage only, without copying history or double-counting ATIF."""
    total = 0.0
    for path in root.glob("harbor/*/*/agent/pi/sessions/*.jsonl"):
        with path.open() as stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                    usage = (entry.get("message") or {}).get("usage") or entry.get("usage") or {}
                    value = (usage.get("cost") or {}).get("total")
                    if type(value) in (int, float) and 0 <= value < float("inf"):
                        total += value
                except (ValueError, TypeError, AttributeError):
                    continue  # An unfinished trailing append is not a completed usage record.
    return total


def execute_harbor(config: dict, root: Path, env: dict, deadline: float, budget: float) -> int:
    from harbor.models.job.config import JobConfig

    JobConfig.model_validate(config)  # Verify against the installed fixed Harbor API.
    if time.monotonic() >= deadline or observed_cost(root) >= budget:
        raise TimeoutError("experiment stop before starting the next Job")
    config_path = root / "configs" / f"{config['job_name']}.json"
    atomic_json(config_path, config, immutable=True)
    log = root / "harbor-console" / f"{config['job_name']}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        process = subprocess.Popen(
            [sys.executable, "-m", "harbor.cli.main", "run", "-c", str(config_path), "--yes"],
            stdout=stream,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("experiment elapsed-time stop")
                if observed_cost(root) >= budget:
                    raise TimeoutError("experiment estimated-cost stop")
                time.sleep(0.5)
            return process.returncode
        except BaseException:
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


def docker_preflight(spec: Experiment, selected: list[dict]) -> dict:
    info = json.loads(
        subprocess.check_output(["docker", "info", "--format", "{{json .}}"], text=True, timeout=30)
    )
    subprocess.run(["docker", "compose", "version"], check=True, capture_output=True, timeout=30)
    available_mb = info["MemTotal"] // (1024 * 1024)
    concurrency = effective_concurrency(
        spec.execution.concurrency, selected, cpus=info["NCPU"], memory_mb=available_mb
    )
    disk = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            spec.execution.platform,
            "alpine:3.23.4",
            "df",
            "-Pm",
            "/",
        ],
        text=True,
        timeout=300,
    )
    available_disk = int(disk.splitlines()[-1].split()[3])
    if concurrency * max(t["resources"]["storage_mb"] for t in selected) > available_disk:
        raise ValueError("official task storage envelope exceeds Docker capacity")
    # Real execution of the requested ISA; never infer amd64 compatibility from a flag.
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            spec.execution.platform,
            "alpine:3.23.4",
            "uname",
            "-m",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    expected = "x86_64" if spec.execution.platform == "linux/amd64" else "aarch64"
    if probe.returncode or probe.stdout.strip() != expected:
        raise ValueError("architecture probe failed; discuss platform before proceeding")
    return {
        "cpus": info["NCPU"],
        "memory_mb": available_mb,
        "server_version": info["ServerVersion"],
        "architecture": info["Architecture"],
        "platform_probe": expected,
        "available_disk_mb": available_disk,
        "effective_concurrency": concurrency,
    }


def trial_results(path: Path) -> dict[str, tuple[Path, dict]]:
    result = {}
    for p in path.glob("*/result.json"):
        data = json.loads(p.read_text())
        name = data["task_name"].split("/")[-1]
        if name in result:
            raise ValueError("ambiguous source attempt; repetitions require separate Jobs")
        result[name] = (p, data)
    return result


def control_ok(job: Path, task_id: str, expected: int) -> bool:
    item = trial_results(job).get(task_id)
    if not item:
        return False
    raw = item[1]
    return (
        not raw.get("exception_info")
        and (raw.get("verifier_result") or {}).get("rewards", {}).get("reward") == expected
    )


def run_experiment(spec: Experiment, suite: Suite, subset: Subset) -> Path:
    if importlib.metadata.version("harbor") != spec.runtime.harbor_version:
        raise ValueError("installed Harbor version does not match experiment")
    package = verify_package(spec.subject.package, spec.subject.sha256, spec.subject.commit)
    dirty = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "status", "--porcelain", "--", "experiments"], text=True
    )
    if dirty:
        raise ValueError("commit the experiment implementation before a frozen run")
    code_commit = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    code_files = {
        p.relative_to(REPOSITORY).as_posix(): file_digest(p)
        for p in sorted((REPOSITORY / "experiments/src").rglob("*.py"))
    }
    spec.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (spec.root / ".run.lock").open("a") as lease:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another experiment is active under this root") from exc
        started = time.monotonic()
        deadline = started + spec.limits.max_elapsed_seconds
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
        root = spec.root / "runs" / run_id
        root.mkdir(parents=True, mode=0o700)
        print(f"Experiment evidence: {root}", file=sys.stderr, flush=True)
        state = {
            "schema_version": 1,
            "run_id": run_id,
            "jobs": {},
            "stop_reason": None,
            "started_at": datetime.now(UTC).isoformat(),
            "complete": False,
        }
        atomic_json(root / "run.json", state)
        lock_written = False
        credential = None
        try:
            upstream = resolve_suite(suite, spec.root / "cache")
            selection = select_tasks(upstream / suite.tasks_dir, suite.id, subset.model_dump())
            atomic_json(root / "selection.json", selection, immutable=True)
            if len(selection["selected"]) < subset.count:
                raise ValueError("insufficient eligible tasks; review the recorded exclusions")
            selected = selection["selected"]
            docker = docker_preflight(spec, selected)
            spec = spec.model_copy(
                update={
                    "execution": spec.execution.model_copy(
                        update={"concurrency": docker["effective_concurrency"]}
                    )
                }
            )
            paths = [upstream / suite.tasks_dir / t["task_id"] for t in selected]
            env = tool_environment(spec, upstream)
            # Explicit platform on the single main service, without task/resource changes.
            platform_overlay = root / "platform.yaml"
            platform_overlay.write_text(
                yaml.safe_dump({"services": {"main": {"platform": spec.execution.platform}}})
            )

            def execute(cfg):
                cfg["environment"]["extra_docker_compose"] = [str(platform_overlay)]
                code = execute_harbor(cfg, root, env, deadline, spec.limits.max_cost_usd)
                if code:
                    raise RuntimeError(
                        f"Harbor Job {cfg['job_name']} exited {code}; see private console log"
                    )

            for control in ("oracle", "nop"):
                state["jobs"]["control-" + control] = {
                    "path": "harbor/control-" + control,
                    "purpose": "official_" + control,
                }
                atomic_json(root / "run.json", state)
                cfg = build_job_config(spec, root, f"control-{control}", paths, control=control)
                execute(cfg)
            for task in selected:
                task_id = task["task_id"]
                if not control_ok(root / "harbor/control-oracle", task_id, 1):
                    raise ValueError(
                        f"official oracle control failed: {task_id}; do not modify tests"
                    )
                if not control_ok(root / "harbor/control-nop", task_id, 0):
                    raise ValueError(
                        f"official empty control failed: {task_id}; review before admitting"
                    )
            images = image_snapshot(paths)
            if any(file_digest(REPOSITORY / path) != digest for path, digest in code_files.items()):
                raise ValueError(
                    "experiment implementation changed during preflight; start a new run"
                )
            plan = [
                {"task_id": task["task_id"], "variant_id": variant.id, "repetition": rep}
                for rep in range(1, spec.execution.repetitions + 1)
                for variant in spec.variants
                for task in selected
            ]
            lock = {
                "schema_version": 1,
                "experiment_id": spec.experiment_id,
                "run_id": run_id,
                "config": spec.model_dump(mode="json"),
                "suite": suite.model_dump(),
                "subset": subset.model_dump(),
                "selection": selected,
                "package": package,
                "experiment_commit": code_commit,
                "implementation_files": code_files,
                "pricing": {
                    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
                    "checked_at": "2026-10-27T00:33:05+08:00",
                    "currency": "USD",
                    "basis": "Pi 1.4.0 native usage; peak reference rates, estimated not billed",
                    "per_million_tokens": {
                        "deepseek-flash": {"input": 0.3, "cache_read": 0.006, "output": 1.2},
                        "deepseek-v4-pro": {"input": 1.32, "cache_read": 0.044, "output": 3.96},
                    }.get(spec.model.id),
                },
                "docker": docker,
                "images": images,
                "tooling_sha256": {
                    p.relative_to(upstream).as_posix(): file_digest(p)
                    for p in sorted((upstream / "v2/tooling").rglob("*.py"))
                }
                if suite.protocol == "swe-pro-v2"
                else {},
                "plan": plan,
            }
            atomic_json(root / "experiment.lock.json", lock, immutable=True)
            lock_written = True
            env = tool_environment(spec, upstream, inference=True)
            credential = json.loads(auth_file().read_text())["deepseek"]["key"].encode()
            for rep in range(1, spec.execution.repetitions + 1):
                order = spec.variants if rep % 2 else list(reversed(spec.variants))
                for variant in order:
                    if any(
                        file_digest(REPOSITORY / path) != digest
                        for path, digest in code_files.items()
                    ):
                        raise ValueError("experiment implementation changed after freezing")
                    if image_snapshot(paths) != images:
                        raise ValueError("task image changed after freezing; start a new run")
                    for task in selected:
                        if (
                            task_digest(upstream / suite.tasks_dir / task["task_id"])
                            != task["sha256"]
                        ):
                            raise ValueError("official task changed after freezing")
                    name = f"{variant.id}-r{rep}"
                    state["jobs"][name] = {"path": f"harbor/{name}", "purpose": "solve"}
                    atomic_json(root / "run.json", state)
                    cfg = build_job_config(
                        spec,
                        root,
                        name,
                        paths,
                        variant=variant.id,
                        auth_path=auth_file(),
                        protocol=suite.protocol,
                    )
                    execute(cfg)
                    if suite.protocol == "swe-pro-v2":
                        original_job = root / "harbor" / name
                        sources = trial_results(original_job)
                        for task in selected:
                            source = sources.get(task["task_id"])
                            if not source or not (source[0].parent / "agent/model.patch").is_file():
                                raise ValueError(
                                    "missing original Pro patch; not an implicit empty answer"
                                )
                        state["jobs"][name]["patches"] = {
                            task_id: {
                                "path": (item[0].parent / "agent/model.patch")
                                .relative_to(root)
                                .as_posix(),
                                "sha256": file_digest(item[0].parent / "agent/model.patch"),
                            }
                            for task_id, item in sources.items()
                        }
                        regrade = name + "-regrade"
                        state["jobs"][name]["regrade"] = "harbor/" + regrade
                        atomic_json(root / "run.json", state)
                        replay = build_job_config(
                            spec,
                            root,
                            regrade,
                            paths,
                            source_job=original_job,
                            protocol=suite.protocol,
                        )
                        execute(replay)
                    if image_snapshot(paths) != images:
                        raise ValueError(
                            "task image changed during execution; results are incomplete"
                        )
            state["complete"] = True
        except BaseException as exc:
            # Arbitrary provider exception bodies can contain credentials.
            state["stop_reason"] = type(exc).__name__ + (
                ": " + str(exc) if isinstance(exc, (ValueError, TimeoutError)) else ""
            )
            raise
        finally:
            state["finished_at"] = datetime.now(UTC).isoformat()
            state["estimated_known_cost_usd"] = observed_cost(root)
            atomic_json(root / "run.json", state)
            if credential is not None:
                try:
                    check_private_evidence(root, credential)
                except ValueError:
                    state.update(
                        complete=False,
                        stop_reason="Evidence privacy validation failed; indexing stopped",
                    )
                    atomic_json(root / "run.json", state)
                    raise
            atomic_json(
                root / "evidence-index.json", {"schema_version": 1, "files": evidence_index(root)}
            )
            if lock_written:
                summary = generate_report(root)
                state["complete"] = state["complete"] and summary["complete"]
                atomic_json(root / "run.json", state)
        return root
