from pathlib import Path

import pytest
import yaml

from memweave_eval.spec import Experiment, load_yaml


def configuration(tmp_path):
    return {
        "schema_version": 1,
        "experiment_id": "test-eval",
        "suite": "suite.yaml",
        "subset": "subset.yaml",
        "subject": {"commit": "a" * 40, "package": "/tmp/subject.tgz", "sha256": "b" * 64},
        "runtime": {"harbor_version": "0.24.0", "pi_version": "1.4.0", "node_version": "24.22.0"},
        "model": {
            "provider": "deepseek",
            "id": "deepseek-chat",
            "api": "openai-completions",
            "auth_profile": "memweave-dev",
            "thinking": "off",
        },
        "variants": [
            {"id": "pi-native", "memweave": False},
            {"id": "pi-memweave", "memweave": True},
        ],
        "execution": {
            "environment": "docker",
            "platform": "linux/amd64",
            "concurrency": 2,
            "repetitions": 1,
            "automatic_trial_retries": 0,
        },
        "limits": {"max_cost_usd": 20, "max_elapsed_seconds": 28800},
        "root": str(tmp_path / "outside"),
    }


def test_strict_config_and_finite_budget(tmp_path):
    data = configuration(tmp_path)
    assert Experiment.model_validate(data).limits.max_cost_usd == 20
    for patch in [
        {"surprise": True},
        {"limits": {"max_cost_usd": float("nan"), "max_elapsed_seconds": 5}},
        {"execution": {"environment": "docker", "platform": "linux/amd64", "concurrency": True}},
        {"variants": [{"id": "pi-native", "memweave": True}]},
    ]:
        with pytest.raises(ValueError):
            Experiment.model_validate(data | patch)


def test_no_implicit_retry_or_unbounded_version(tmp_path):
    data = configuration(tmp_path)
    with pytest.raises(ValueError):
        Experiment.model_validate(data | {"runtime": data["runtime"] | {"pi_version": "latest"}})
    with pytest.raises(ValueError):
        Experiment.model_validate(
            data | {"execution": data["execution"] | {"automatic_trial_retries": 1}}
        )


def test_yaml_rejects_duplicate_keys_and_objects(tmp_path):
    p = tmp_path / "config.yaml"
    for content in ["schema_version: 1\nschema_version: 2\n", "!!python/object:os.system {}"]:
        p.write_text(content)
        with pytest.raises(ValueError):
            load_yaml(p)
    p.write_text(yaml.safe_dump({"ok": 1}))
    assert load_yaml(p) == {"ok": 1}


def test_private_roots_and_path_resolution(tmp_path):
    data = configuration(tmp_path)
    repository = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError):
        Experiment.model_validate(data | {"root": str(repository / "results")})
