import hashlib
import json
import time
import tomllib
from unittest.mock import patch

import pytest
from harbor.models.task.config import TaskConfig
from harbor.models.task.paths import TaskPaths
from harbor.models.task.verifier_mode import resolve_verifier_environment_definition
from test_spec import configuration
from test_suites import make_task

from memweave_eval import images
from memweave_eval.runner import admit_tb_tasks
from memweave_eval.spec import Experiment, Subset
from memweave_eval.storage import evidence_index
from memweave_eval.suites import task_digest

LIMITS = {"count": 1, "seed": "s", "max_cpus": 4, "max_memory_mb": 8192, "max_storage_mb": 32768}


@pytest.fixture
def builder(monkeypatch):
    calls = []

    def build(directory, config, reference, log, platform, deadline, env):
        calls.append(directory)
        log.write_text("unit substitute, no Docker or model\n")
        return {
            "reference": reference,
            "id": "sha256:" + hashlib.sha256(reference.encode()).hexdigest(),
            "repo_digests": [],
            "platform": platform,
        }

    monkeypatch.setattr(images, "_build_image", build)
    return calls


def prepare(source, root):
    return images.prepare_task(source, root, "linux/amd64", time.monotonic() + 60, {}, LIMITS)


@pytest.mark.parametrize("mode", ["shared", "bundled", "fallback", "explicit"])
def test_original_context_and_resolved_verifier_semantics_preserved(tmp_path, builder, mode):
    source = make_task(tmp_path / "original", "one")
    with (source / "task.toml").open("a") as f:
        if mode != "shared":
            f.write('\n[verifier]\nenvironment_mode="separate"\ntimeout_sec=791\n')
        if mode == "explicit":
            f.write("[verifier.environment]\ncpus=2\nmemory_mb=2048\nstorage_mb=4096\n")
    if mode in {"bundled", "explicit"}:
        (source / "tests/Dockerfile").write_text("FROM official-grader\nCOPY . /tests\n")
    before = task_digest(source)
    root = tmp_path / "run"
    record = prepare(source, root)
    runtime = root / record["runtime_path"]
    assert task_digest(source) == before
    for p in source.rglob("*"):
        if p.is_file() and p.name != "task.toml":
            assert p.read_bytes() == (runtime / p.relative_to(source)).read_bytes()
    assert images.protocol_view(source) == images.protocol_view(runtime)
    assert builder == [source / "environment"] + (
        [source / "tests"] if mode in {"bundled", "explicit"} else []
    )
    cfg = TaskConfig.model_validate_toml((runtime / "task.toml").read_text())
    v = resolve_verifier_environment_definition(cfg, TaskPaths(runtime))
    if mode == "shared":
        assert v is None
    elif mode == "fallback":
        assert not v.bundled_tests
        assert cfg.verifier.environment is None  # Do not suppress Harbor's test upload.
        assert v.config.docker_image == cfg.environment.docker_image
    else:
        assert v.bundled_tests
        assert v.config.cpus == (2 if mode == "explicit" else 1)
        assert v.config.memory_mb == (2048 if mode == "explicit" else 4096)
    images.verify_prepared_task(root, record)
    (runtime / "instruction.md").write_text("tampered")
    with pytest.raises(ValueError, match="runtime task"):
        images.verify_prepared_task(root, record)


def test_build_failure_has_evidence_without_changing_upstream(tmp_path, monkeypatch):
    source = make_task(tmp_path / "original", "one")
    before = task_digest(source)

    def fail(*args):
        args[3].write_text("official build failed\n")
        raise images.TaskPreparationError("official build failed")

    monkeypatch.setattr(images, "_build_image", fail)
    with pytest.raises(images.TaskPreparationError):
        prepare(source, tmp_path / "run")
    assert task_digest(source) == before
    assert not (tmp_path / "run/runtime-tasks/one").exists()
    assert (tmp_path / "run/preparation/one/main.log").exists()


def test_platform_and_expired_deadline_block_preparation(tmp_path, builder, monkeypatch):
    source = make_task(tmp_path / "original", "one")
    with pytest.raises(TimeoutError):
        images.prepare_task(source, tmp_path / "expired", "linux/amd64", 0, {}, LIMITS)
    assert not builder
    original = images._build_image

    def wrong(*args):
        return dict(original(*args), platform="linux/arm64")

    monkeypatch.setattr(images, "_build_image", wrong)
    with pytest.raises(images.TaskPreparationError, match="platform"):
        prepare(source, tmp_path / "wrong")


def test_preparation_files_are_indexed(tmp_path, builder):
    source = make_task(tmp_path / "upstream", "one")
    root = tmp_path / "run"
    record = prepare(source, root)
    paths = {x["path"] for x in evidence_index(root)}
    assert record["manifest_path"] in paths
    assert record["runtime_path"] + "/task.toml" in paths
    assert "preparation/one/main.log" in paths


@pytest.mark.parametrize("failure", ["build", "oracle", "nop"])
def test_admission_uses_ordered_reserve_before_any_model(tmp_path, builder, monkeypatch, failure):
    root = tmp_path / "run"
    root.mkdir()
    upstream = tmp_path / "upstream"
    tasks = [make_task(upstream, n) for n in ["first", "second"]]
    candidates = [
        {
            "task_id": p.name,
            "sha256": task_digest(p),
            "resources": tomllib.loads((p / "task.toml").read_text())["environment"],
        }
        for p in tasks
    ]
    spec = Experiment.model_validate(configuration(tmp_path))
    seen = []
    if failure == "build":
        original = images._build_image

        def fail_first(*args):
            if args[0].parent.name == "first":
                raise images.TaskPreparationError("official build failed")
            return original(*args)

        monkeypatch.setattr(images, "_build_image", fail_first)

    def execute(cfg, *, required=True):
        agent = cfg["agents"][0]["name"]
        assert agent in {"oracle", "nop"}
        names = [x["path"].split("/")[-1] for x in cfg["tasks"]]
        seen.extend(names)
        for name in names:
            reward = int(agent == "oracle")
            if name == "first" and agent == failure:
                reward = 1 - reward
            path = root / "harbor" / cfg["job_name"] / (name + "__trial")
            path.mkdir(parents=True)
            (path / "result.json").write_text(
                json.dumps({"task_name": name, "verifier_result": {"rewards": {"reward": reward}}})
            )
        return 0

    # Image identity is checked without actually starting Docker in this unit test.
    with (
        patch("memweave_eval.runner.image_snapshot", return_value={"stable": True}),
        patch("memweave_eval.runner.docker_preflight", return_value={"effective_concurrency": 2}),
    ):
        selected, paths, records = admit_tb_tasks(
            spec,
            Subset.model_validate(LIMITS),
            candidates,
            upstream,
            root,
            {"jobs": {}},
            {},
            time.monotonic() + 60,
            execute,
        )
    assert [t["task_id"] for t in selected] == ["second"]
    assert [p.name for p in paths] == ["second"]
    assert set(records) == {"second"}
    evidence = json.loads((root / "admission.json").read_text())
    assert [t["task_id"] for t in evidence["attempts"]] == ["first", "second"]
    assert evidence["attempts"][0]["status"] != "admitted"
    assert evidence["attempts"][1]["status"] == "admitted"
    assert seen[-2:] == ["second", "second"]


def test_build_command_uses_original_dockerfile_and_no_extra_context(tmp_path):
    source = make_task(tmp_path, "one")
    from harbor.models.task.config import EnvironmentConfig

    from memweave_eval.images import _build_image

    calls = []

    def command(args, log, timeout, env):
        calls.append(args)
        log.write_text("unit substitute")

    with (
        patch("memweave_eval.images._run_docker", command),
        patch(
            "memweave_eval.images.inspect_image",
            return_value={"reference": "frozen:x", "platform": "linux/amd64", "id": "sha256:x"},
        ),
    ):
        _build_image(
            source / "environment",
            EnvironmentConfig(build_timeout_sec=10),
            "frozen:x",
            tmp_path / "build.log",
            "linux/amd64",
            time.monotonic() + 60,
            {},
        )
    args = calls[0]
    assert args[:3] == ["docker", "buildx", "build"]
    assert args[args.index("--file") + 1] == str(source / "environment/Dockerfile")
    assert args[-1] == str(source / "environment")
    assert args[args.index("--platform") + 1] == "linux/amd64"
    assert "--build-arg" not in args


def test_global_stop_does_not_try_a_reserve(tmp_path, builder, monkeypatch):
    root = tmp_path / "run"
    root.mkdir()
    upstream = tmp_path / "upstream"
    task = make_task(upstream, "one")
    candidate = {"task_id": "one", "sha256": task_digest(task)}
    calls = []

    def stop(*args):
        calls.append(args[0])
        raise TimeoutError("overall stop")

    monkeypatch.setattr(images, "_build_image", stop)
    with (
        pytest.raises(TimeoutError),
        patch("subprocess.Popen", side_effect=AssertionError("no Job may start")),
    ):
        admit_tb_tasks(
            Experiment.model_validate(configuration(tmp_path)),
            Subset.model_validate(LIMITS),
            [candidate, candidate],
            upstream,
            root,
            {"jobs": {}},
            {},
            time.monotonic() + 60,
            None,
        )
    assert calls == [task / "environment"]


def test_missing_frozen_image_never_rebuilds(tmp_path, builder):
    import subprocess

    from memweave_eval.runner import image_snapshot

    task = make_task(tmp_path / "upstream", "one")
    root = tmp_path / "run"
    record = prepare(task, root)
    with (
        patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "inspect")),
        pytest.raises(subprocess.CalledProcessError),
    ):
        image_snapshot([root / record["runtime_path"]])
    assert builder == [task / "environment"]


def test_verifier_resource_envelope_reduces_concurrency(tmp_path):
    from types import SimpleNamespace

    from memweave_eval.runner import docker_preflight

    def output(args, **kwargs):
        if args[1] == "info":
            return json.dumps(
                {
                    "MemTotal": 16384 * 1024**2,
                    "NCPU": 8,
                    "ServerVersion": "test",
                    "Architecture": "aarch64",
                }
            )
        if args[1] == "compose":
            return "test"
        return "Filesystem 1024-blocks Used Available Capacity Mounted\nroot 200000 1 199999 1% /\n"

    task = {"resources": {"cpus": 1, "memory_mb": 4096, "storage_mb": 10240}}
    preparations = {"one": {"verifier_resources": dict(task["resources"], memory_mb=8192)}}
    with (
        patch("subprocess.check_output", output),
        patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="x86_64\n")),
    ):
        info = docker_preflight(
            Experiment.model_validate(configuration(tmp_path)), [task], preparations
        )
    assert info["effective_concurrency"] == 1
    assert task["resources"]["memory_mb"] == 4096


def test_preparation_timeout_terminates_the_real_client_process(tmp_path):
    import subprocess
    import sys

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        images._run_docker(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path / "timeout.log",
            0.05,
            {},
        )
    assert time.monotonic() - started < 5


def test_os_path_alias_does_not_change_verifier_resolution(tmp_path, builder):
    source = make_task(tmp_path / "real", "one")
    with (source / "task.toml").open("a") as stream:
        stream.write('\n[verifier]\nenvironment_mode="separate"\n')
    (source / "tests/Dockerfile").write_text("FROM grader\n")
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    alias = tmp_path / "alias/one"
    assert images.protocol_view(alias) == images.protocol_view(source)
    record = prepare(alias, tmp_path / "run")
    images.verify_prepared_task(tmp_path / "run", record)
