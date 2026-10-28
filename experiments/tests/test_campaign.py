import json
from pathlib import Path

import pytest
from test_spec import configuration

from memweave_eval.campaign import (
    Campaign,
    campaign_plan,
    load_catalog,
    mixed_job,
    paired_capacity,
    replay_handoff,
    variant_results,
)
from memweave_eval.live import LiveObserver
from memweave_eval.storage import atomic_json, file_digest


def spec(tmp_path):
    data = configuration(tmp_path)
    data.pop("suite")
    data.pop("subset")
    data.update(schema_version=2, catalog="catalog.yaml", catalog_sha256="a" * 64)
    data["execution"]["concurrency"] = 10
    data["model"]["id"] = "deepseek-flash"
    return Campaign.model_validate(data)


def test_strict_campaign_and_pair_capacity(tmp_path):
    s = spec(tmp_path)
    assert s.execution.concurrency == 10
    for patch in ({"concurrency": 11}, {"repetitions": 2}, {"platform": "linux/arm64"}):
        with pytest.raises(ValueError):
            Campaign.model_validate(
                s.model_dump() | {"execution": s.execution.model_dump() | patch}
            )
    assert (
        paired_capacity(
            10, [{"resources": {"cpus": 1, "memory_mb": 4096}}], cpus=12, memory_mb=42000
        )
        == 5
    )
    assert (
        paired_capacity(
            10, [{"resources": {"cpus": 4, "memory_mb": 8192}}], cpus=12, memory_mb=42000
        )
        == 1
    )
    with pytest.raises(ValueError):
        paired_capacity(
            10, [{"resources": {"cpus": 4, "memory_mb": 8192}}], cpus=4, memory_mb=12000
        )


def test_frozen_catalog_and_full_plan(tmp_path):
    s = spec(tmp_path)
    s.catalog = Path(__file__).parents[1] / "subsets/catalogs/long-horizon-49-v1.yaml"
    s.catalog_sha256 = file_digest(s.catalog)
    catalog = load_catalog(s)
    plan = campaign_plan(catalog)
    assert len(plan) == 98
    assert len({(r["task_id"], r["variant_id"]) for r in plan}) == 98
    assert sum(r["suite_id"] == "swe-bench-pro-v2" for r in plan) == 70
    s.catalog_sha256 = "b" * 64
    with pytest.raises(ValueError, match="catalog"):
        load_catalog(s)


def test_mixed_harbor_job_and_official_limits(tmp_path):
    from harbor.models.job.config import JobConfig

    s = spec(tmp_path)
    runtime = tmp_path / "runtime-assets.json"
    atomic_json(runtime, {})
    atomic_json(runtime.with_name("runtime-assets.lock.json"), {"objects": {}})
    cfg = mixed_job(
        s,
        tmp_path,
        [tmp_path / f"task{i}" for i in range(5)],
        protocol="swe-pro-v2",
        runtime_plan=runtime,
    )
    parsed = JobConfig.model_validate(cfg)
    assert len(parsed.agents) == 2
    assert parsed.n_concurrent_trials == 10
    assert parsed.verifier.disable
    assert parsed.retry.max_retries == 0
    assert {a.kwargs["variant"] for a in parsed.agents} == {"pi-native", "pi-memweave"}
    assert all(a.override_timeout_sec is None for a in parsed.agents)
    assert "override_memory_mb" not in cfg["environment"]


def trial(job, variant, *, patch=True):
    directory = job / ("instance_x__" + variant)
    directory.mkdir(parents=True)
    atomic_json(
        directory / "result.json",
        {
            "task_name": "instance_x",
            "trial_name": directory.name,
            "config": {"agent": {"kwargs": {"variant": variant}}},
        },
    )
    if patch:
        (directory / "agent").mkdir()
        (directory / "agent/model.patch").write_text("diff " + variant)
    return directory


def test_replay_handoff_keeps_variants_and_missing_patch_distinct(tmp_path):
    job = tmp_path / "solve"
    native = trial(job, "pi-native")
    plugin = trial(job, "pi-memweave")
    assert len(variant_results(job)) == 2
    for variant, source in [("pi-native", native), ("pi-memweave", plugin)]:
        handoff, manifest = replay_handoff(job, tmp_path / variant, variant)
        assert len(manifest["patches"]) == 1
        patch = next(handoff.glob("instance_*/agent/model.patch"))
        assert patch.read_bytes() == (source / "agent/model.patch").read_bytes()
        assert manifest["patches"][0]["sha256"] == file_digest(patch)
    (native / "agent/model.patch").unlink()
    _, manifest = replay_handoff(job, tmp_path / "missing", "pi-native")
    assert manifest["patches"] == []
    assert manifest["missing"] == ["instance_x"]


def test_duplicate_variant_is_never_accepted(tmp_path):
    trial(tmp_path, "pi-native")
    d = tmp_path / "duplicate"
    d.mkdir()
    (d / "result.json").write_bytes(next(tmp_path.glob("instance_*/result.json")).read_bytes())
    with pytest.raises(ValueError, match="ambiguous"):
        variant_results(tmp_path)


def session(tmp_path):
    p = tmp_path / "groups/g01/harbor/solve/instance_x/agent/pi/sessions/s.jsonl"
    p.parent.mkdir(parents=True)
    return p


def usage(identifier="a"):
    return {
        "id": identifier,
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "toolCall", "name": "read"}],
            "usage": {
                "input": 1000,
                "cacheRead": 2000,
                "cacheWrite": 0,
                "output": 100,
                "cost": {"total": 0.0001},
            },
        },
    }


def test_live_incremental_partial_dedup_and_peak_pricing(tmp_path):
    p = session(tmp_path)
    line = json.dumps(usage()) + "\n"
    p.write_text(line + "{")
    observer = LiveObserver(tmp_path)
    first = observer.scan()
    assert first["model_responses"] == 1
    assert first["estimated_cost_usd"] == pytest.approx(0.000432)
    assert observer.scan()["estimated_cost_usd"] == first["estimated_cost_usd"]
    with p.open("a") as out:
        out.write('"type":"session"}\n' + line + json.dumps(usage("b")) + "\n")
    assert observer.scan()["model_responses"] == 2
    assert "content" not in json.dumps(observer.scan())
    p.write_text("")
    with pytest.raises(ValueError, match="replaced|truncated"):
        observer.scan()


@pytest.mark.parametrize("bad", [{"input": -1}, {"input": "unknown"}, {"cacheWrite": 10}])
def test_unknown_usage_blocks_cost_confidence(tmp_path, bad):
    p = session(tmp_path)
    item = usage()
    item["message"]["usage"].update(bad)
    p.write_text(json.dumps(item) + "\n")
    with pytest.raises(ValueError, match="usage"):
        LiveObserver(tmp_path).scan()


def test_lifecycle_counts_real_solves_only(tmp_path):
    p = tmp_path / "groups/g01/lifecycle/solve.jsonl"
    p.parent.mkdir(parents=True)
    events = [
        {
            "event": "agent-start",
            "trial": str(i),
            "variant": "pi-native" if i < 5 else "pi-memweave",
            "purpose": "solve",
        }
        for i in range(10)
    ]
    events += [
        {
            "event": "agent-start",
            "trial": "prep",
            "variant": "pi-native",
            "purpose": "software_preflight",
        }
    ]
    p.write_text("".join(json.dumps(e) + "\n" for e in events))
    observer = LiveObserver(tmp_path)
    assert observer.scan()["active_solves"] == {"pi-native": 5, "pi-memweave": 5}
    with p.open("a") as out:
        out.write(json.dumps(events[0] | {"event": "agent-end"}) + "\n")
    assert observer.scan()["active_solves"]["pi-native"] == 4
    assert observer.peak_solves == 10


def test_offline_report_retains_blocked_and_unrun_rows(tmp_path):
    from memweave_eval.campaign_report import generate_campaign_report

    s = spec(tmp_path)
    s.catalog = Path(__file__).parents[1] / "subsets/catalogs/long-horizon-49-v1.yaml"
    s.catalog_sha256 = file_digest(s.catalog)
    plan = campaign_plan(load_catalog(s))
    atomic_json(
        tmp_path / "experiment.lock.json", {"schema_version": 2, "run_id": "test", "plan": plan}
    )
    atomic_json(
        tmp_path / "run.json",
        {
            "complete": False,
            "tasks": {
                plan[0]["task_id"]: {"status": "blocked", "reason": "official oracle failed"}
            },
        },
    )
    atomic_json(tmp_path / "evidence-index.json", {"files": []})
    report = generate_campaign_report(tmp_path)
    assert len(report["rows"]) == 98
    assert [r["execution_status"] for r in report["rows"][:2]] == ["blocked", "blocked"]
    assert all(r["success"] is None for r in report["rows"])
    assert report["variants"]["pi-native"]["planned"] == 49
    assert report["variants"]["pi-native"]["scored"] == 0
    assert report["pairs"]["missing"] == 49
    assert report["complete"] is False


def test_campaign_deadline_and_shared_budget_prevent_new_job(tmp_path):
    import time

    from memweave_eval.campaign import execute_job

    class Observer:
        def check(self):
            return 20.01

    cfg = mixed_job(spec(tmp_path), tmp_path, [], protocol="tb4", runtime_plan=None)
    with pytest.raises(TimeoutError, match="shared time/cost"):
        execute_job(
            cfg,
            tmp_path,
            {},
            time.monotonic() + 60,
            20,
            Observer(),
            purpose="solve",
            inference=True,
        )
    assert not (tmp_path / "configs").exists()
    with pytest.raises(TimeoutError, match="shared time/cost"):
        execute_job(
            cfg,
            tmp_path,
            {},
            time.monotonic() - 1,
            20,
            Observer(),
            purpose="regrade",
            inference=False,
        )


def test_corrupt_completed_live_line_is_not_ignored(tmp_path):
    p = session(tmp_path)
    p.write_text("{bad json}\n")
    with pytest.raises(ValueError, match="invalid completed"):
        LiveObserver(tmp_path).scan()
