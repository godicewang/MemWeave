"""Read official tasks without altering instructions, environments or graders."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import tomllib
from collections import defaultdict
from pathlib import Path

from .spec import Suite
from .storage import file_digest


def task_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError(f"task contains a symlink: {p.relative_to(root)}")
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode() + b"\0")
            h.update(bytes.fromhex(file_digest(p)))
    return h.hexdigest()


def task_info(path: Path, suite_id: str, limits: dict) -> dict:
    cfg = tomllib.loads((path / "task.toml").read_text())
    env = cfg.get("environment", {})
    reason = None
    for field in ("cpus", "memory_mb", "storage_mb"):
        value = env.get(field)
        if type(value) is not int or value <= 0:
            reason = f"unknown official {field}"
            break
        if value > limits["max_" + field]:
            reason = f"official {field} exceeds subset resource envelope"
            break
    if env.get("gpus", 0) or env.get("tpu"):
        reason = "requires an accelerator"
    if env.get("os", "linux") != "linux":
        reason = "non-Linux task"
    # Compose service permissions need an explicit audit before admission.
    if any(
        (path / name).exists()
        for name in (
            "environment/docker-compose.yaml",
            "environment/docker-compose.yml",
            "environment/compose.yaml",
            "environment/compose.yml",
        )
    ):
        reason = "multi-container permissions require review"
    if cfg.get("steps"):
        reason = "multi-step session policy requires explicit suite admission"
    for needed in ("instruction.md", "tests/test.sh", "solution/solve.sh"):
        if not (path / needed).is_file():
            reason = f"missing official {needed}"
    if suite_id == "swe-bench-pro-v2":
        if cfg.get("agent", {}).get("network_mode") != "no-network":
            reason = "Pro V2 offline policy is absent"
        group = path.name.removeprefix("instance_").split("-")[0]
    else:
        group = cfg.get("metadata", {}).get("category", "uncategorized")
    return {
        "task_id": path.name,
        "group": group,
        "reason": reason,
        "sha256": task_digest(path),
        "resources": env,
        "agent_timeout_sec": cfg.get("agent", {}).get("timeout_sec"),
        "verifier_timeout_sec": cfg.get("verifier", {}).get("timeout_sec"),
    }


def select_tasks(root: Path, suite_id: str, options: dict) -> dict:
    candidates, excluded = [], []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or not (p / "task.toml").is_file():
            continue
        if p.is_symlink():
            raise ValueError("symlink task root")
        info = task_info(p, suite_id, options)
        (excluded if info["reason"] else candidates).append(info)
    groups = defaultdict(list)
    for info in candidates:
        key = f"{suite_id}\0{options['seed']}\0{info['task_id']}"
        info["selection_key"] = hashlib.sha256(key.encode()).hexdigest()
        groups[info["group"]].append(info)
    for items in groups.values():
        items.sort(key=lambda item: item["selection_key"])
    ordered = []
    while any(groups.values()):
        for group in sorted(groups):
            if groups[group]:
                ordered.append(groups[group].pop(0))
    return {
        "selected": ordered[: options["count"]],
        "reserves": ordered[options["count"] :],
        "excluded": excluded,
        "algorithm": "sha256-nul-utf8-round-robin-v1",
        "seed": options["seed"],
        "candidate_count": len(candidates),
    }


def resolve_suite(suite: Suite, cache: Path) -> Path:
    """Immutable git checkout. Only the two schema-validated official remotes are accepted."""
    destination = cache / f"{suite.id}-{suite.revision}"
    if not (destination / ".git").is_dir():
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".fetch-", dir=cache) as temporary:
            checkout = Path(temporary) / "checkout"
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "fetch",
                    "--depth=1",
                    suite.repository,
                    suite.revision,
                ],
                check=True,
                timeout=900,
            )
            subprocess.run(
                ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
                check=True,
            )
            checkout.rename(destination)
    commit = subprocess.check_output(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(destination), "status", "--porcelain"], text=True
    )
    if commit != suite.revision or dirty:
        raise ValueError("cached upstream checkout is modified or not at its locked commit")
    return destination
