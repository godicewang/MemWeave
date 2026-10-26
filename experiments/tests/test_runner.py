import io
import json
import tarfile

import pytest
from test_spec import configuration

from memweave_eval.runner import build_job_config, effective_concurrency, verify_package
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
