import json
from pathlib import Path
from unittest.mock import patch

import yaml
from test_runner import package
from test_spec import configuration

from memweave_eval.cli import main
from memweave_eval.report import generate_report
from memweave_eval.storage import atomic_json, evidence_index, file_digest


def test_validate_is_offline_and_does_not_create_runtime_data(tmp_path, capsys):
    archive = tmp_path / "package.tgz"
    package(archive)
    spec = configuration(tmp_path)
    spec["subject"].update(package=str(archive), sha256=file_digest(archive))
    suite = {
        "id": "terminal-bench-4",
        "repository": "https://github.com/harbor-framework/terminal-bench.git",
        "revision": "a" * 40,
        "tasks_dir": "tasks",
        "protocol": "tb4",
    }
    (tmp_path / "suite.yaml").write_text(yaml.safe_dump(suite))
    (tmp_path / "subset.yaml").write_text(
        yaml.safe_dump(
            {"count": 2, "seed": "s", "max_cpus": 4, "max_memory_mb": 8192, "max_storage_mb": 65536}
        )
    )
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(spec))
    with patch(
        "subprocess.Popen", side_effect=AssertionError("offline validation must not execute")
    ):
        assert main(["validate", str(p)]) == 0
    assert not Path(spec["root"]).exists()
    assert json.loads(capsys.readouterr().out)["model_trials"] == 4


def test_regrade_uses_original_usage_and_hashes_detect_later_changes(tmp_path):
    lock = {
        "schema_version": 1,
        "run_id": "test",
        "suite": {"id": "swe-bench-pro-v2", "protocol": "swe-pro-v2"},
        "plan": [
            {"task_id": "a", "variant_id": variant, "repetition": 1}
            for variant in ["pi-native", "pi-memweave"]
        ],
    }
    jobs = {}
    for variant in ["pi-native", "pi-memweave"]:
        name = variant + "-r1"
        jobs[name] = {"path": "harbor/" + name, "regrade": "harbor/" + name + "-regrade"}
        original = {
            "task_name": "a",
            "trial_name": "a__original",
            "agent_result": {"n_input_tokens": 10, "n_output_tokens": 5, "cost_usd": 0.2},
        }
        regrade = {
            "task_name": "a",
            "trial_name": "a__grade",
            "verifier_result": {"rewards": {"reward": 1}},
            "agent_result": {"n_input_tokens": 0, "cost_usd": 0},
        }
        atomic_json(tmp_path / jobs[name]["path"] / "a__original/result.json", original)
        atomic_json(tmp_path / jobs[name]["regrade"] / "a__grade/result.json", regrade)
        p = tmp_path / jobs[name]["path"] / "a__original/agent/model.patch"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("a frozen patch")
        jobs[name]["patches"] = {
            "a": {"path": p.relative_to(tmp_path).as_posix(), "sha256": file_digest(p)}
        }
    atomic_json(tmp_path / "experiment.lock.json", lock)
    atomic_json(tmp_path / "run.json", {"jobs": jobs})
    atomic_json(tmp_path / "evidence-index.json", {"files": evidence_index(tmp_path)})
    first = generate_report(tmp_path)
    assert first["complete"]
    assert first["variants"]["pi-native"]["cost_usd"] == 0.2
    report = (tmp_path / "reports/report.md").read_bytes()
    assert generate_report(tmp_path) == first
    assert (tmp_path / "reports/report.md").read_bytes() == report
    (tmp_path / jobs["pi-native-r1"]["regrade"] / "a__grade/result.json").write_text("{}")
    assert not generate_report(tmp_path)["complete"]


def test_missing_cost_and_cancelled_run_cannot_become_complete(tmp_path):
    atomic_json(
        tmp_path / "experiment.lock.json",
        {
            "run_id": "cancelled",
            "suite": {"id": "terminal-bench-4", "protocol": "tb4"},
            "plan": [{"task_id": "a", "variant_id": "pi-native", "repetition": 1}],
        },
    )
    atomic_json(tmp_path / "run.json", {"stop_reason": "budget", "jobs": {}})
    atomic_json(tmp_path / "evidence-index.json", {"files": []})
    summary = generate_report(tmp_path)
    assert summary["variants"]["pi-native"]["planned"] == 1
    assert summary["variants"]["pi-native"]["scored"] == 0
    assert not summary["complete"]
    assert main(["report", str(tmp_path)]) == 2
