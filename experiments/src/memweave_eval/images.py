"""Build official contexts unchanged and freeze transparent Harbor runtime copies."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import tomllib
from pathlib import Path

import toml
from harbor.models.task.config import TaskConfig
from harbor.models.task.paths import TaskPaths
from harbor.models.task.verifier_mode import (
    resolve_task_verifier_mode,
    resolve_verifier_environment_definition,
)

from .storage import atomic_json, contained, file_digest
from .suites import task_digest


class TaskPreparationError(ValueError):
    """An official task cannot be admitted; the ordered reserve may be considered."""


def inspect_image(reference: str, env: dict | None = None) -> dict:
    info = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", reference], text=True, timeout=30, env=env
        )
    )[0]
    return {
        "reference": reference,
        "id": info["Id"],
        "repo_digests": info.get("RepoDigests", []),
        "platform": info["Os"] + "/" + info["Architecture"],
    }


def _run_docker(args: list[str], log: Path, timeout: float, env: dict) -> None:
    with log.open("ab") as stream:
        stream.write((json.dumps(args) + "\n").encode())
        stream.flush()
        process = subprocess.Popen(
            args,
            stdout=stream,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                except ProcessLookupError:
                    process.wait()
            raise
        if code:
            raise TaskPreparationError(f"Docker command exited {code}; see {log.name}")


def _build_image(directory, config, reference, log, platform, deadline, env) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("experiment stop before official image preparation")
    timeout = min(config.build_timeout_sec, remaining)
    try:
        if config.docker_image:
            cached = None
            try:
                found = inspect_image(config.docker_image, env)
                repository = config.docker_image.split("@", 1)[0].rsplit(":", 1)[0]
                if (found["platform"] == platform and
                        any(d.startswith(repository + "@") for d in found["repo_digests"])):
                    cached = found
            except subprocess.CalledProcessError:
                pass
            if cached:
                log.write_text(json.dumps({"reuse_official_digest": cached}) + "\n")
            else:
                _run_docker(
                    ["docker", "pull", "--platform", platform, config.docker_image], log, timeout, env
                )
            _run_docker(
                ["docker", "tag", config.docker_image, reference],
                log,
                min(30, max(0.01, deadline - time.monotonic())),
                env,
            )
        else:
            if not (directory / "Dockerfile").is_file():
                raise TaskPreparationError("no official Dockerfile or prebuilt image")
            _run_docker(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--load",
                    "--platform",
                    platform,
                    "--progress",
                    "plain",
                    "--file",
                    str(directory / "Dockerfile"),
                    "--tag",
                    reference,
                    "--iidfile",
                    str(log.with_suffix(".iid")),
                    str(directory),
                ],
                log,
                timeout,
                env,
            )
    except subprocess.TimeoutExpired as exc:
        if time.monotonic() >= deadline:
            raise TimeoutError("experiment elapsed-time stop during image preparation") from exc
        raise TaskPreparationError("official image build/pull timeout") from exc
    if time.monotonic() >= deadline:
        raise TimeoutError("experiment elapsed-time stop after image preparation")
    try:
        return inspect_image(reference, env)
    except subprocess.CalledProcessError as exc:
        raise TaskPreparationError("prepared image identity unavailable") from exc


def protocol_view(path: Path) -> dict:
    """Compare the public resolver's effective protocol, excluding image references only."""
    path = path.resolve()
    cfg = TaskConfig.model_validate_toml((path / "task.toml").read_text())
    result = cfg.model_dump(mode="json")
    result["environment"].pop("docker_image", None)
    result["verifier"]["environment_mode"] = resolve_task_verifier_mode(cfg).value
    verifier = resolve_verifier_environment_definition(cfg, TaskPaths(path))
    if verifier is not None:
        result["verifier"]["environment"] = verifier.config.model_dump(
            mode="json", exclude={"docker_image"}
        )
        result["resolved_verifier"] = {
            "directory": verifier.directory.relative_to(path).as_posix(),
            "bundled_tests": verifier.bundled_tests,
        }
    return result


def prepare_task(
    source: Path, root: Path, platform: str, deadline: float, env: dict, limits: dict,
    *, frozen: dict | None = None,
) -> dict:
    source, root = source.resolve(), root.resolve()
    if time.monotonic() >= deadline:
        raise TimeoutError("experiment stop before preparing the next task")
    original_hash = task_digest(source)  # Also rejects links anywhere in the input tree.
    text = (source / "task.toml").read_text()
    raw = tomllib.loads(text)
    cfg = TaskConfig.model_validate_toml(text)
    if cfg.steps:
        raise TaskPreparationError("multi-step task is outside current admission")
    verifier = resolve_verifier_environment_definition(cfg, TaskPaths(source))
    definitions = [("main", source / "environment", cfg.environment)]
    if verifier is not None:
        for field in ("cpus", "memory_mb", "storage_mb"):
            value = getattr(verifier.config, field)
            if type(value) is not int or value <= 0 or value > limits["max_" + field]:
                raise TaskPreparationError(f"official verifier {field} outside subset envelope")
        if verifier.config.gpus or verifier.config.tpu or verifier.config.os.value != "linux":
            raise TaskPreparationError("official verifier requires an unsupported platform")
        if verifier.bundled_tests:
            definitions.append(("verifier", verifier.directory, verifier.config))
    if frozen is not None:
        if (frozen.get("task_id") != source.name
                or frozen.get("source_sha256") != original_hash
                or frozen.get("platform") != platform
                or set(frozen.get("images", {})) != {role for role, _, _ in definitions}):
            raise ValueError("frozen preparation task/platform/roles changed")
        # Validate every role before changing any experiment alias.
        for role, directory, config in definitions:
            old = frozen["images"][role]
            dockerfile = directory / "Dockerfile"
            if (old.get("context_sha256") != task_digest(directory)
                    or old.get("dockerfile_sha256") != (
                        file_digest(dockerfile) if dockerfile.is_file() else None)
                    or old.get("source_image") != config.docker_image
                    or old.get("platform") != platform):
                raise ValueError("frozen preparation context/source changed")
            actual = inspect_image(old["id"], env)
            if actual["id"] != old["id"] or actual["platform"] != platform:
                raise ValueError("frozen preparation image identity changed")
    evidence_dir = root / "preparation" / source.name
    evidence_dir.mkdir(parents=True, exist_ok=False)
    built = {}
    changed = copy.deepcopy(raw)
    for role, directory, config in definitions:
        if any(
            (directory / name).exists()
            for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
        ):
            raise TaskPreparationError("official Compose environment requires separate review")
        context_hash = task_digest(directory)
        name = hashlib.sha256(
            f"{root.name}\0{source.name}\0{role}\0{platform}\0{context_hash}".encode()
        ).hexdigest()
        reference = "memweave-eval:" + name
        log = evidence_dir / f"{role}.log"
        if frozen is None:
            identity = _build_image(directory, config, reference, log, platform, deadline, env)
        else:
            original = frozen["images"][role]
            log.write_text(json.dumps({"reuse_frozen_preparation": original}) + "\n")
            _run_docker(["docker", "tag", original["id"], reference], log,
                        min(30, max(0.01, deadline - time.monotonic())), env)
            identity = inspect_image(reference, env)
            if identity["id"] != original["id"]:
                raise ValueError("frozen preparation alias changed identity")
        if identity["platform"] != platform:
            raise TaskPreparationError("prepared image platform differs from the frozen platform")
        if task_digest(directory) != context_hash:
            raise ValueError("official Docker build context changed during preparation")
        built[role] = dict(
            identity,
            context_sha256=context_hash,
            dockerfile_sha256=file_digest(directory / "Dockerfile")
            if (directory / "Dockerfile").is_file()
            else None,
            source_image=config.docker_image,
            build_log=log.relative_to(root).as_posix(),
        )
        if role == "main":
            changed.setdefault("environment", {})["docker_image"] = reference
        else:
            # Explicit grader config must retain the original effective resources.
            section = changed.setdefault("verifier", {})
            if section.get("environment") is None:
                section["environment"] = copy.deepcopy(raw.get("environment", {}))
            section["environment"]["docker_image"] = reference
    runtime = root / "runtime-tasks" / source.name
    shutil.copytree(source, runtime)
    rewritten = toml.dumps(changed)
    if tomllib.loads(rewritten) != changed:
        raise ValueError("TOML serialization changed official task values")
    (runtime / "task.toml").write_text(rewritten)
    if protocol_view(source) != protocol_view(runtime):
        raise ValueError("runtime task changed the official resolved protocol")
    for p in source.rglob("*"):
        if (
            p.is_file()
            and p.relative_to(source).as_posix() != "task.toml"
            and p.read_bytes() != (runtime / p.relative_to(source)).read_bytes()
        ):
            raise ValueError("runtime copy changed a non-configuration file")
    if task_digest(source) != original_hash:
        raise ValueError("official task changed during preparation")
    diff = evidence_dir / "task.toml.diff"
    diff.write_text(
        "".join(
            difflib.unified_diff(
                text.splitlines(keepends=True),
                rewritten.splitlines(keepends=True),
                fromfile="official/task.toml",
                tofile="runtime/task.toml",
            )
        )
    )
    record = {
        "schema_version": 1,
        "task_id": source.name,
        "source_sha256": original_hash,
        "runtime_path": runtime.relative_to(root).as_posix(),
        "runtime_sha256": task_digest(runtime),
        "platform": platform,
        "images": built,
        "config_diff": diff.relative_to(root).as_posix(),
        "protocol_equivalent": True,
        "verifier_resources": {
            k: getattr(verifier.config, k) for k in ("cpus", "memory_mb", "storage_mb")
        }
        if verifier
        else None,
        "verifier_bundled_tests": verifier.bundled_tests if verifier else None,
    }
    manifest = evidence_dir / "manifest.json"
    atomic_json(manifest, record, immutable=True)
    return dict(
        record,
        manifest_path=manifest.relative_to(root).as_posix(),
        manifest_sha256=file_digest(manifest),
    )


def verify_prepared_task(root: Path, record: dict) -> None:
    if file_digest(contained(root, record["manifest_path"])) != record["manifest_sha256"]:
        raise ValueError("task preparation manifest changed after freezing")
    if task_digest(contained(root, record["runtime_path"])) != record["runtime_sha256"]:
        raise ValueError("runtime task changed after freezing")
