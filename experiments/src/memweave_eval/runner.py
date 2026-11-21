"""Frozen experiment orchestration; Harbor owns every Trial and its environment."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tarfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .images import TaskPreparationError, prepare_task, verify_prepared_task
from .runtime_cache import create_plan, snapshot
from .spec import (
    REPOSITORY,
    Experiment,
)
from .storage import atomic_json, file_digest


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
    from harbor.models.task.config import TaskConfig
    from harbor.models.task.paths import TaskPaths
    from harbor.models.task.verifier_mode import resolve_verifier_environment_definition

    from .images import inspect_image
    from .private_runtime import image_libc

    result = {}
    for path in paths:
        config = TaskConfig.model_validate_toml((path / "task.toml").read_text())
        definitions = [(path.name, path / "environment", config.environment)]
        verifier = resolve_verifier_environment_definition(config, TaskPaths(path))
        if verifier is not None:
            definitions.append((path.name + ":verifier", verifier.directory, verifier.config))
        for key, _directory, environment in definitions:
            if not environment.docker_image:
                raise ValueError(
                    "Dockerfile task must be prepared before image freezing"
                )
            result[key] = inspect_image(environment.docker_image)
            if not key.endswith(":verifier"):
                result[key]["libc"] = image_libc(result[key]["id"], result[key]["platform"])
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
    runtime_plan: Path | None = None,
    prepare_only: bool = False,
    broker_client: Path | None = None,
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
                "auth_path": "" if prepare_only else str(auth_path),
                "protocol": protocol,
                **({"thinking": spec.model.thinking}if spec.model.thinking is not None else{}),
                "runtime_plan": str(runtime_plan) if runtime_plan else None,
                "runtime_plan_sha256": file_digest(runtime_plan) if runtime_plan else None,
                "prepare_only": prepare_only,
                **({'evaluation_broker_client':str(broker_client),'evaluation_broker_client_sha256':file_digest(broker_client)}if broker_client else{}),
                **({'evaluation_primary_default':spec.evaluation.primary_default}if getattr(spec,'evaluation',None)else{}),
                **({'evaluation_deadline': datetime.fromisoformat(
                    spec.evaluation.deadline_utc).timestamp()-spec.evaluation.finalization_reserve_seconds,
                    'evaluation_output_tokens':spec.evaluation.output_tokens}
                   if getattr(spec, 'evaluation', None) else {}),
                **({'evaluation_episode_budget':spec.evaluation.episode_budget_usd}
                   if getattr(spec,'evaluation',None) else {}),
                **({'evaluation_run_id':run_root.name} if getattr(spec,'evaluation',None) else {}),
                **({'evaluation_quota_backend':spec.evaluation.quota_backend,
                    'evaluation_per_task_arms':spec.evaluation.per_task_arm_caps,
                    'evaluation_task_ids':[p.name for p in tasks]}
                   if getattr(spec,'evaluation',None) else {}),
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
    if prepare_only:
        cfg["verifier"] = {"disable": True}
        cfg["n_concurrent_trials"] = 1
        cfg["agents"][0].update(override_setup_timeout_sec=3600, override_timeout_sec=240)
    elif runtime_plan and not control and not source_job:
        frozen = runtime_plan.with_name("runtime-assets.lock.json")
        agent["kwargs"]["runtime_objects"] = json.loads(frozen.read_text())["objects"]
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


def execute_harbor(config: dict, root: Path, env: dict, deadline: float, budget: float, *, budget_stop_file: Path | None = None, stop_event=None, spawned_event=None) -> int:
    def close_admission():
        if budget_stop_file is not None:
            budget_stop_file.parent.mkdir(parents=True,exist_ok=True)
            budget_stop_file.touch()
    def local_stop():
        return (root/'STOP_REQUESTED').exists() or (stop_event is not None and stop_event.is_set())
    if local_stop():close_admission()
    from harbor.models.job.config import JobConfig

    JobConfig.model_validate(config)  # Verify against the installed fixed Harbor API.
    if local_stop() or time.monotonic() >= deadline or observed_cost(root) >= budget:
        raise TimeoutError("experiment stop before starting the next Job")
    config_path = root / "configs" / f"{config['job_name']}.json"
    atomic_json(config_path, config, immutable=True)
    log = root / "harbor-console" / f"{config['job_name']}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    lifecycle = root/"lifecycle"
    from .rsi_elapsed import observation
    record = {"monotonic": observation(), "identity": identity, "job_name": config['job_name'],
              "config_sha256": file_digest(config_path), "controller_pid": os.getpid(),
              "started_at": datetime.now(UTC).isoformat(), "stop_file": str(root/"STOP_REQUESTED")}
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
            if spawned_event is not None:
                spawned_event.set()
            record.update(child_pid=process.pid, child_process_group=process.pid)
            from .rsi_recovery import capture_process_identity

            record['process_identity'] = capture_process_identity(process.pid)
            atomic_json(lifecycle/(config['job_name']+".start.json"),record,immutable=True)
            while process.poll() is None:
                atomic_json(lifecycle/(config['job_name']+".lease.json"),dict(record,heartbeat_at=datetime.now(UTC).isoformat()))
                if local_stop():
                    close_admission()
                    raise TimeoutError("explicit user stop requested")
                if time.monotonic() >= deadline:
                    raise TimeoutError("experiment elapsed-time stop")
                if observed_cost(root) >= budget:
                    raise TimeoutError("experiment estimated-cost stop")
                time.sleep(0.5)
            return process.returncode
        except BaseException:
            close_admission()
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
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
        finally:
            atomic_json(lifecycle/(config['job_name']+".end.json"),{
                "identity":identity,"job_name":config['job_name'],
                "config_sha256":record['config_sha256'],
                "process_identity":record.get('process_identity'),
                "status":"terminal"if process.returncode is not None else"stop_unconfirmed","return_code":process.returncode,
                "finished_at":datetime.now(UTC).isoformat(), "monotonic": observation(),
                "explicit_stop":local_stop()},immutable=True)


def docker_preflight(spec: Experiment, selected: list[dict], preparations=None) -> dict:
    requirements = list(selected)
    if spec.evaluation and spec.evaluation.resources:
        requirements=[dict(t,resources=dict(t['resources'],**spec.evaluation.resources))for t in requirements]
    for record in (preparations or {}).values():
        if record.get("verifier_resources"):
            requirements.append({"resources": record["verifier_resources"]})
    info = json.loads(
        subprocess.check_output(["docker", "info", "--format", "{{json .}}"], text=True, timeout=30)
    )
    subprocess.run(["docker", "compose", "version"], check=True, capture_output=True, timeout=30)
    available_mb = info["MemTotal"] // (1024 * 1024)
    concurrency = effective_concurrency(
        spec.execution.concurrency, requirements, cpus=info["NCPU"], memory_mb=available_mb
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
    if concurrency * max(t["resources"]["storage_mb"] for t in requirements) > available_disk:
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
    wanted=expected.get('reward') if isinstance(expected,dict) else expected
    matched=not raw.get('exception_info') and (raw.get('verifier_result')or{}).get('rewards',{}).get('reward')==wanted
    if isinstance(expected,dict) and expected.get('metrics'):
        path=item[0].parent/'verifier/metrics.json'
        if not path.is_file():return False
        metrics=json.loads(path.read_text())
        matched &= all(metrics.get(k)==v for k,v in expected['metrics'].items())
    if isinstance(expected,dict) and 'stdout_fail_lines' in expected:
        path=item[0].parent/'verifier/test-stdout.txt'
        if not path.is_file():return False
        matched &= [line for line in path.read_text().splitlines()if line.startswith('FAIL ')]==expected['stdout_fail_lines']
    return bool(matched)


def admit_tb_tasks(spec, subset, candidates, task_root, root, state, env, deadline, execute):
    """Prepare and control ordered candidates, exclusively before the model plan freezes."""
    admission = {"schema_version": 1, "attempts": [], "admitted": []}
    admitted, paths, preparations = [], [], {}
    queue = iter(candidates)
    batch_number = 0
    while len(admitted) < subset.count:
        batch = []
        while len(batch) < subset.count - len(admitted):
            if time.monotonic() >= deadline:
                raise TimeoutError("experiment stop during task admission")
            candidate = next(queue, None)
            if candidate is None:
                break
            task_id = candidate["task_id"]
            attempt = {"task_id": task_id, "source_sha256": candidate["sha256"],
                       "status": "preparing"}
            admission["attempts"].append(attempt)
            atomic_json(root / "admission.json", admission)
            try:
                frozen=None
                if getattr(spec,'evaluation',None) and spec.evaluation.frozen_preparation:
                    previous=json.loads(spec.evaluation.frozen_preparation.read_text())
                    frozen=(previous.get('preparations',{}).get(task_id) if 'preparations' in previous
                            else previous.get(task_id,previous))
                    if not frozen:
                        raise ValueError('frozen original image preparation missing')
                record = prepare_task(task_root / task_id, root, spec.execution.platform,
                                      deadline, env, subset.model_dump(),frozen=frozen,
                                      resources=spec.evaluation.resources if spec.evaluation else None)
            except TaskPreparationError as exc:
                attempt.update(status="preparation_failed", reason=str(exc))
                atomic_json(root / "admission.json", admission)
                continue
            attempt.update(status="prepared", preparation=record["manifest_path"])
            atomic_json(root / "admission.json", admission)
            batch.append((candidate, record, attempt))
        if not batch:
            raise ValueError("insufficient tasks passed official preparation and controls")
        batch_number += 1
        batch_paths = [root / record["runtime_path"] for _, record, _ in batch]
        batch_records = {task["task_id"]: record for task, record, _ in batch}
        capacity = docker_preflight(spec, [t for t, _, _ in batch], batch_records)
        frozen_images = image_snapshot(batch_paths)
        controls, control_codes = {}, {}
        def expectation(task_id, control):
            return int(control == 'oracle')
        for control in ("oracle", "nop"):
            name = f"control-{control}-a{batch_number:03d}"
            controls[control] = name
            state["jobs"][name] = {"path": "harbor/" + name, "purpose": "official_" + control}
            atomic_json(root / "run.json", state)
            cfg = build_job_config(spec, root, name, batch_paths, control=control)
            cfg["n_concurrent_trials"] = capacity["effective_concurrency"]
            code = execute(cfg, required=False)
            control_codes[control] = code
            if code < 0 or (code and all(control_ok(root / "harbor" / name,
                           t["task_id"], expectation(t["task_id"], control)) for t, _, _ in batch)):
                raise RuntimeError("official control Job failed outside its task results")
        if image_snapshot(batch_paths) != frozen_images:
            raise ValueError("task image changed during official controls")
        for task, record, attempt in batch:
            task_id = task["task_id"]
            verify_prepared_task(root, record)
            attempt["controls"] = {k: "harbor/" + v for k, v in controls.items()}
            attempt["control_exit_codes"] = control_codes
            failed = [control for control, expected in ((c,expectation(task_id,c)) for c in ("oracle","nop"))
                      if not control_ok(root / "harbor" / controls[control], task_id, expected)]
            if failed:
                attempt.update(status="control_failed", reason="official " + ", ".join(failed))
            else:
                attempt["status"] = "admitted"
                admitted.append(task)
                paths.append(root / record["runtime_path"])
                preparations[task_id] = record
                admission["admitted"].append(task_id)
            atomic_json(root / "admission.json", admission)
    return admitted, paths, preparations


def prepare_runtimes(spec, root, paths, images, state, execute, deadline, *, broker_clients=None) -> dict:
    """All task/variant software checks precede any credential access or inference."""
    plan = create_plan(spec, images)
    plan_path = root / "runtime-assets.json"
    atomic_json(plan_path, plan, immutable=True)
    for variant in spec.variants:
        name = "runtime-preflight-" + variant.id
        state["jobs"][name] = {"path": "harbor/" + name, "purpose": "software_preflight"}
        atomic_json(root / "run.json", state)
        cfg = build_job_config(spec, root, name, paths, variant=variant.id,
                               runtime_plan=plan_path, prepare_only=True,broker_client=(broker_clients or{}).get(variant.id))
        cfg["agents"][0]["override_setup_timeout_sec"] = min(
            3600, max(1, deadline - time.monotonic()))
        execute(cfg)
        results = trial_results(root / "harbor" / name)
        for task in paths:
            item = results.get(task.name)
            if not item or item[1].get("exception_info"):
                raise ValueError(f"runtime preflight failed: {variant.id}/{task.name}; no model started")
            output = item[0].parent / "agent/runtime-preflight.json"
            if not output.is_file() or json.loads(output.read_text()).get("model_requests") != 0:
                raise ValueError("runtime preflight evidence missing; no model started")
    if spec.evaluation and spec.execution.paired_concurrent and spec.execution.concurrency>=2:
        configs=[]
        for variant in spec.variants:
            name='runtime-concurrent-'+variant.id
            state['jobs'][name]={'path':'harbor/'+name,'purpose':'software_preflight'}
            cfg=build_job_config(spec,root,name,paths,variant=variant.id,runtime_plan=plan_path,prepare_only=True,broker_client=(broker_clients or{}).get(variant.id))
            cfg['n_concurrent_trials']=min(len(paths),spec.execution.concurrency//2)
            configs.append(cfg)
        atomic_json(root/'run.json',state)
        with ThreadPoolExecutor(max_workers=2)as pool:list(pool.map(execute,configs))
        for cfg in configs:
            results=trial_results(root/'harbor'/cfg['job_name'])
            for task in paths:
                item=results.get(task.name)
                if not item or item[1].get('exception_info'):
                    raise ValueError('concurrent real CLI preflight failed')
    record = {"plan_sha256": file_digest(plan_path), "objects": snapshot(plan)}
    atomic_json(root / "runtime-assets.lock.json", record, immutable=True)
    return record


def require_primary_time(paths,model_deadline,global_deadline,*,now=None):
    """Refuse a paid launch that would silently shorten the original task budget."""
    import tomllib

    now=time.time()if now is None else now
    configs=[tomllib.loads((p/'task.toml').read_text())for p in paths]
    actor=max(c['agent']['timeout_sec']for c in configs)
    verifier=max(c['verifier']['timeout_sec']for c in configs)
    # Setup/canary precede the full actor timeout; these are admission margins.
    if now+600+actor>model_deadline or model_deadline+verifier+180>global_deadline:
        raise ValueError('insufficient authorized time for original primary actor, verifier and finalization budgets')
