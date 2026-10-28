"""Reuse only equivalent official oracle/nop evidence; never reuse model scores."""

from __future__ import annotations

import json
import shutil

from .storage import atomic_json, file_digest


def reuse_controls(spec, catalog, row, preparation, group, docker):
    parent = spec.control_parent
    if parent is None:
        return False
    lock = json.loads((parent / "experiment.lock.json").read_text())
    suite = lock.get("suite", {})
    if (
        suite.get("id") != row["suite"]
        or suite.get("revision") != catalog["sources"][row["suite"]]["revision"]
        or lock["config"]["runtime"]["harbor_version"] != spec.runtime.harbor_version
        or lock["docker"]["server_version"] != docker["server_version"]
        or lock["docker"]["platform_probe"] != docker["platform_probe"]
    ):
        return False
    selected = [r for r in lock["selection"] if r["task_id"] == row["task_id"]]
    image = lock["images"].get(row["task_id"])
    current = preparation["images"]["main"]
    if (
        len(selected) != 1
        or selected[0]["sha256"] != row["task_sha256"]
        or not image
        or (image["id"], image["platform"]) != (current["id"], current["platform"])
    ):
        return False
    index = {
        e["path"]: e["sha256"]
        for e in json.loads((parent / "evidence-index.json").read_text())["files"]
    }
    found = {}
    for control, expected in [("oracle", 1), ("nop", 0)]:
        matches = []
        for path in (parent / "harbor" / ("control-" + control)).glob("*/result.json"):
            raw = json.loads(path.read_text())
            if raw.get("task_name", "").split("/")[-1] == row["task_id"]:
                matches.append((path, raw))
        if len(matches) != 1:
            return False
        path, raw = matches[0]
        cfg = raw["config"]
        if (
            raw.get("exception_info")
            or (raw.get("verifier_result") or {}).get("rewards", {}).get("reward") != expected
            or cfg["agent"].get("name") != control
            or cfg.get("timeout_multiplier", 1) != 1
            or cfg.get("verifier_timeout_multiplier") not in (None, 1)
            or cfg.get("verifier", {}).get("disable", False)
            or cfg.get("verifier", {}).get("override_timeout_sec") is not None
            or any(
                cfg.get("environment", {}).get(k) is not None
                for k in ("override_cpus", "override_memory_mb", "override_storage_mb")
            )
        ):
            return False
        if file_digest(path) != index.get(path.relative_to(parent).as_posix()):
            raise ValueError("official control evidence checksum mismatch")
        found[control] = path
    output = group / "control-reuse" / row["task_id"]
    output.mkdir(parents=True, exist_ok=False)
    records = {}
    for control, path in found.items():
        shutil.copyfile(path, output / (control + ".json"))
        records[control] = {"source": str(path), "sha256": file_digest(path)}
    atomic_json(
        output / "receipt.json",
        {
            "task_id": row["task_id"],
            "task_sha256": row["task_sha256"],
            "image": current,
            "source_run": str(parent),
            "source_lock_sha256": file_digest(parent / "experiment.lock.json"),
            "harbor_version": spec.runtime.harbor_version,
            "docker": docker,
            "controls": records,
            "model_scores_reused": False,
        },
        immutable=True,
    )
    return True
