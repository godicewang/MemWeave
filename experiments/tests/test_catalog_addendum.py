"""Approved append-only reserve lineage; no model, Docker, or reward changes."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_campaign import spec

import memweave_eval.campaign_report as reports
from memweave_eval import campaign
from memweave_eval.paired import completed_info
from memweave_eval.spec import REPOSITORY
from memweave_eval.storage import atomic_json, file_digest

V1 = "b32b5593058c21b74888fde3fe4d6a2447cd45242ce86ee12936cf2ad018ebad"
V2 = "749a781520017c0864d33ed720f879f4f60799cdfa9475eefb19b4981f28c865"
DIRECTORY = Path(__file__).parents[1] / "subsets/catalogs"


def frozen(tmp_path):
    s = spec(tmp_path)
    s.catalog = DIRECTORY / "long-horizon-49-v2.yaml"
    s.catalog_sha256 = V2
    return s, yaml.safe_load(s.catalog.read_text())


def test_exact_v2_preserves_original_selected_and_old_reserve_order(tmp_path):
    s, data = frozen(tmp_path)
    old = yaml.safe_load((DIRECTORY / "long-horizon-49-v1.yaml").read_text())
    assert campaign.load_catalog(s) == data
    assert data["selected"] == old["selected"]
    assert data["reserves"][:5] == old["reserves"]
    assert [r["display_id"] for r in data["reserves"][5:]] == ["RS05", "RS06", "RS07"]
    transition = campaign.catalog_transition(V1, V2, data)
    assert transition == {
        "from_sha256": V1,
        "to_sha256": V2,
        "added_reserve_ids": ["RS05", "RS06", "RS07"],
    }
    assert campaign.catalog_transition(V2, V2, data) is None


@pytest.mark.parametrize(
    "change",
    [
        "selected",
        "source",
        "quota",
        "old_reserve",
        "new_task",
        "new_tier",
        "order",
        "extra",
        "addendum",
        "parent_digest",
        "unknown_version",
    ],
)
def test_v2_rejects_any_unapproved_edit_even_with_updated_config_digest(tmp_path, change):
    s, data = frozen(tmp_path)
    if change == "selected":
        data["selected"][0]["task_id"] += "-other"
    elif change == "source":
        data["sources"]["swe-bench-pro-v2"]["revision"] = "a" * 40
    elif change == "quota":
        data["quota_by_suite"]["swe-bench-pro-v2"]["simple"] += 1
    elif change == "old_reserve":
        data["reserves"][0]["title"] += "-other"
    elif change == "new_task":
        data["reserves"][5]["task_id"] += "-other"
    elif change == "new_tier":
        data["reserves"][5]["tier"] = "hard"
    elif change == "order":
        data["reserves"][5:7] = reversed(data["reserves"][5:7])
    elif change == "extra":
        data["reserves"].append(deepcopy(data["reserves"][-1]))
    elif change == "addendum":
        data.pop("reserve_addendum")
    elif change == "parent_digest":
        data["reserve_addendum"]["parent_catalog_sha256"] = "a" * 64
    elif change == "unknown_version":
        data["catalog_id"] += "-other"
    s.catalog = tmp_path / "mutated.yaml"
    s.catalog.write_text(yaml.safe_dump(data, allow_unicode=True))
    s.catalog_sha256 = file_digest(s.catalog)
    with pytest.raises(ValueError, match="catalog|addendum"):
        campaign.load_catalog(s)


@pytest.mark.parametrize(("old", "new"), [("a" * 64, V2), (V2, V1), (V1, "a" * 64)])
def test_unknown_or_reverse_transition_is_rejected(tmp_path, old, new):
    _, data = frozen(tmp_path)
    with pytest.raises(ValueError, match="catalog"):
        campaign.catalog_transition(old, new, data)


def test_valid_transition_keeps_first_zero_score_cost_and_origin(tmp_path, monkeypatch):
    s, data = frozen(tmp_path)
    parent = s.root / "runs/parent"
    previous = s.model_dump(mode="json") | {"catalog_sha256": V1}
    atomic_json(
        parent / "experiment.lock.json",
        {
            "phase": "full",
            "config": previous,
            "implementation_files": {
                "experiments/src/memweave_eval/" + n: file_digest(
                    REPOSITORY / "experiments/src/memweave_eval" / n
                )
                for n in (
                    "pi_agent.py",
                    "runtime_cache.py",
                    "runner.py",
                    "images.py",
                    "network_probe.py",
                    "public_archive.py",
                    "private_runtime.py",
                    "artifact_replay.py",
                )
            },
        },
    )
    atomic_json(
        parent / "run.json",
        {
            "finished_at": "2026-10-29T04:00:00+00:00",
            "window_started_at": "2026-10-28T10:48:39+00:00",
            "window_deadline_at": None,
            "estimated_known_cost_usd": 0.4,
            "jobs": {},
            "tasks": {},
            "admission_failures": [],
        },
    )
    for name in ("live.json", "evidence-index.json"):
        atomic_json(parent / name, {})
    rows = [
        {
            "task_id": data["selected"][0]["task_id"],
            "variant_id": v,
            "solve_source": "original-" + v,
            "success": i == 1,
            "solve_status": "completed_patch",
            "peak_estimated_cost_usd": 0.2,
            "origin_run_id": "original-first-attempt",
            "session_diagnostics": {"model_responses_with_usage": 1},
        }
        for i, v in enumerate(campaign.VARIANTS)
    ]
    monkeypatch.setattr(
        reports,
        "generate_campaign_report",
        lambda _: {"rows": rows, "invalid_evidence": [], "estimated_known_cost_usd": 0.4},
    )
    s.completed_parent = parent
    info, inherited = completed_info(s, data)
    assert inherited == rows and inherited[0]["success"] is False
    assert info["known_cost_usd"] == 0.4
    assert info["window_started_at"] == "2026-10-28T10:48:39+00:00"
    assert info["window_deadline_at"] is None
    assert info["catalog_transition"]["added_reserve_ids"] == ["RS05", "RS06", "RS07"]
    lock = json.loads((parent / "experiment.lock.json").read_text())
    lock["config"]["model"]["thinking"] = "high"
    atomic_json(parent / "experiment.lock.json", lock)
    with pytest.raises(ValueError, match="identity mismatch: model"):
        completed_info(s, data)
