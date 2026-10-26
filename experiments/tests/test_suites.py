import hashlib

import pytest

from memweave_eval.suites import select_tasks, task_digest


def make_task(root, name, category="coding", cpus=1, gpus=0):
    p = root / name
    (p / "environment").mkdir(parents=True)
    (p / "tests").mkdir()
    (p / "solution").mkdir()
    (p / "instruction.md").write_text("Fix this repository.")
    (p / "environment/Dockerfile").write_text("FROM example@sha256:" + "a" * 64)
    (p / "tests/test.sh").write_text("exit 0\n")
    (p / "solution/solve.sh").write_text("exit 0\n")
    (p / "task.toml").write_text(
        f'[metadata]\ncategory="{category}"\n[agent]\ntimeout_sec=3000\n'
        f"[environment]\ncpus={cpus}\nmemory_mb=4096\nstorage_mb=10240\ngpus={gpus}\n"
    )
    return p


def test_hash_content_and_symlink_boundaries(tmp_path):
    p = make_task(tmp_path, "one")
    first = task_digest(p)
    assert len(first) == len(hashlib.sha256().hexdigest())
    (p / "instruction.md").write_text("Different instructions")
    assert task_digest(p) != first
    (p / "outside").symlink_to(tmp_path / "unavailable")
    with pytest.raises(ValueError):
        task_digest(p)


def test_deterministic_stratified_selection_never_changes_official_tasks(tmp_path):
    for name, category in [("a", "coding"), ("b", "coding"), ("c", "data")]:
        make_task(tmp_path, name, category)
    make_task(tmp_path, "gpu", gpus=1)
    make_task(tmp_path, "large", cpus=64)
    before = {p.name: task_digest(p) for p in tmp_path.iterdir()}
    options = {
        "count": 2,
        "seed": "fixed",
        "max_cpus": 8,
        "max_memory_mb": 16384,
        "max_storage_mb": 65536,
    }
    first = select_tasks(tmp_path, "terminal-bench-4", options)
    second = select_tasks(tmp_path, "terminal-bench-4", options)
    assert first == second
    assert {t["group"] for t in first["selected"]} == {"coding", "data"}
    assert {t["task_id"] for t in first["excluded"]} == {"gpu", "large"}
    assert before == {p.name: task_digest(p) for p in tmp_path.iterdir()}


def test_unknown_resources_are_not_assumed_compatible(tmp_path):
    p = make_task(tmp_path, "unknown")
    (p / "task.toml").write_text('[environment]\ndocker_image="example"\n')
    result = select_tasks(
        tmp_path,
        "terminal-bench-4",
        {"count": 1, "seed": "s", "max_cpus": 8, "max_memory_mb": 16000, "max_storage_mb": 65000},
    )
    assert not result["selected"]
    assert result["excluded"][0]["reason"]
