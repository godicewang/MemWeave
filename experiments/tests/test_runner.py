import io
import json
import tarfile

import pytest
from test_spec import configuration

from memweave_eval.runner import (
    build_job_config,
    effective_concurrency,
    tool_environment,
    verify_package,
)
from memweave_eval.spec import Experiment
from memweave_eval.storage import atomic_json, contained, file_digest


def test_immutable_and_contained_evidence(tmp_path):
    p = tmp_path / "lock.json"
    atomic_json(p, {"ok": 1}, immutable=True)
    with pytest.raises(FileExistsError):
        atomic_json(p, {"ok": 2}, immutable=True)
    assert json.loads(p.read_text()) == {"ok": 1}
    for name in ("../escape", "/absolute"):
        with pytest.raises(ValueError):
            contained(tmp_path, name)
    (tmp_path / "link").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        contained(tmp_path, "link/other")


def package(path, extra=()):
    files = {
        "package/package.json": json.dumps(
            {
                "name": "@godice/memweave",
                "version": "0.1.0",
                "pi": {"extensions": ["./src/extension/index.ts"]},
            }
        ),
        "package/src/extension/index.ts": "export default function() {}",
        "package/resources/rule.md": "Full rule",
    }
    files.update(dict(extra))
    with tarfile.open(path, "w:gz") as t:
        for name, text in files.items():
            data = text.encode()
            item = tarfile.TarInfo(name)
            item.size = len(data)
            t.addfile(item, io.BytesIO(data))


def test_package_hash_and_resource_boundary(tmp_path):
    p = tmp_path / "subject.tgz"
    package(p)
    assert verify_package(p, file_digest(p))["name"] == "@godice/memweave"
    with pytest.raises(ValueError):
        verify_package(p, "f" * 64)
    for extra in [
        ("package/../escape", "x"),
        ("package/.pi/auth.json", "secret"),
        ("package/AGENTS.md", "developer instructions"),
    ]:
        package(p, [extra])
        with pytest.raises(ValueError):
            verify_package(p, file_digest(p))


def test_real_harbor_config_preserves_task_resource_and_retry_contract(tmp_path):
    from harbor.models.job.config import JobConfig

    spec = Experiment.model_validate(configuration(tmp_path))
    task = tmp_path / "task"
    config = build_job_config(
        spec,
        tmp_path / "run",
        "pi-native-r1",
        [task],
        variant="pi-native",
        auth_path=tmp_path / "auth.json",
    )
    JobConfig.model_validate(config)
    assert config["retry"]["max_retries"] == 0
    assert config["n_attempts"] == 1
    assert config["n_concurrent_trials"] == 2
    assert "override_cpus" not in config["environment"]
    assert "override_timeout_sec" not in config["agents"][0]
    assert not config.get("extra_instructions")
    assert config["agents"][0]["kwargs"]["variant"] == "pi-native"


def test_pro_solve_never_runs_verifier_and_replay_does(tmp_path):
    from harbor.models.job.config import JobConfig

    spec = Experiment.model_validate(configuration(tmp_path))
    solve = build_job_config(
        spec, tmp_path, "solve", [], variant="pi-native", protocol="swe-pro-v2"
    )
    assert JobConfig.model_validate(solve).verifier.disable
    replay = build_job_config(
        spec, tmp_path, "replay", [], source_job=tmp_path / "solve", protocol="swe-pro-v2"
    )
    assert not JobConfig.model_validate(replay).verifier.disable
    assert replay["agents"][0]["import_path"] == "patch_replay:PatchReplayAgent"


def test_reduce_concurrency_without_reducing_official_resources():
    selected = [{"resources": {"cpus": 4, "memory_mb": 8192}}]
    assert effective_concurrency(2, selected, cpus=8, memory_mb=15957) == 1
    assert effective_concurrency(2, selected, cpus=8, memory_mb=20000) == 2
    with pytest.raises(ValueError):
        effective_concurrency(2, selected, cpus=2, memory_mb=20000)


def test_host_credentials_never_enter_harbor_environment(tmp_path, monkeypatch):
    from unittest.mock import patch

    spec = Experiment.model_validate(configuration(tmp_path))
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"deepseek": {"type": "api_key", "key": "test-private-key"}}))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "host-private-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    with patch("memweave_eval.runner.auth_file", return_value=auth):
        env = tool_environment(spec, tmp_path, inference=True)
    assert "DEEPSEEK_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["HARBOR_TELEMETRY"] == "0"
    assert "DOCKER_DEFAULT_PLATFORM" not in env  # Harbor sidecar is built for the daemon ISA.


def test_stopped_experiment_never_starts_another_job(tmp_path):
    import time
    from unittest.mock import patch

    from memweave_eval.runner import execute_harbor

    spec = Experiment.model_validate(configuration(tmp_path))
    cfg = build_job_config(spec, tmp_path, "nop", [], control="nop")
    with (
        patch("subprocess.Popen", side_effect=AssertionError("must not start")),
        pytest.raises(TimeoutError),
    ):
        execute_harbor(cfg, tmp_path, {}, time.monotonic() - 1, 20)


def test_image_lock_includes_official_separate_verifier(tmp_path):
    from unittest.mock import patch

    from test_suites import make_task

    from memweave_eval.runner import image_snapshot

    task = make_task(tmp_path, "one")
    with (task / "task.toml").open("a") as stream:
        stream.write(
            '\n[verifier]\nenvironment_mode="separate"\n[verifier.environment]\ndocker_image="grader:fixed"\n'
        )
    p = task / "task.toml"
    p.write_text(
        p.read_text().replace("[environment]", '[environment]\ndocker_image="subject:fixed"')
    )
    (task / "tests/Dockerfile").write_text("FROM verifier-base")

    def inspect(args, **kwargs):
        return json.dumps([{"Id": "sha256:" + args[-1], "Os": "linux", "Architecture": "arm64"}])

    with patch("subprocess.check_output", inspect):
        images = image_snapshot([task])
    assert set(images) == {"one", "one:verifier"}
    assert images["one"]["reference"] != images["one:verifier"]["reference"]


def test_dockerfile_task_cannot_be_falsely_declared_frozen(tmp_path):
    from test_suites import make_task

    from memweave_eval.runner import image_snapshot

    with pytest.raises(ValueError, match="pending runtime-copy"):
        image_snapshot([make_task(tmp_path, "one")])
