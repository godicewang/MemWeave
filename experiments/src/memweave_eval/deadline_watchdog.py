"""Independent run-labelled Docker cleanup; failures retry and never imply success."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def monitor(root: Path, run_id: str, model_deadline: float, hard_stop: float):
    output = root / "harbor/deadline-watchdog.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    warned = False
    while not (root / ".watchdog-stop").exists():
        now = time.time()

        def command(args):
            try:
                return subprocess.run(
                    ["docker", *args], capture_output=True, text=True, check=False, timeout=10
                )
            except (OSError, subprocess.TimeoutExpired):
                return SimpleNamespace(returncode=124, stdout="")

        query = ["ps", "--filter", "label=org.memweave.eval.run=" + run_id, "--format", "{{.ID}}"]
        selected = command(query)
        identities = selected.stdout.split() if selected.returncode == 0 else None
        record = {
            "timestamp": now,
            "containers": identities,
            "docker_query_status": selected.returncode,
        }
        confirmed = False
        if now >= hard_stop:
            if identities is not None:
                record["hard_stop"] = {
                    identity: command(["kill", identity]).returncode for identity in identities
                }
                check = command(query)
                confirmed = check.returncode == 0 and not check.stdout.split()
                record["confirmed_stopped"] = confirmed
            if not confirmed:
                record["stop_status"] = "unconfirmed_retrying"
            if now >= hard_stop + 120 and not confirmed and not warned:
                warned = True
                (root / "stop-unconfirmed.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "status": "ALERT",
                            "reason": "container stop could not be confirmed by hard deadline",
                        }
                    )
                )
        elif now >= model_deadline and identities is not None:
            record["model_stop"] = {
                identity: command(
                    ["exec", identity, "sh", "-c", "pkill -TERM -x pi || true; pkill -TERM -x node || true"]
                ).returncode
                for identity in identities
            }
            # Keep checking: a failed exec or a newly starting instance is never skipped.
        elif identities:
            stats = command(["stats", "--no-stream", "--format", "{{json .}}", *identities])
            try:
                record["stats"] = [
                    json.loads(line) for line in stats.stdout.splitlines() if line.startswith("{")
                ]
            except ValueError:
                record["stats_status"] = "invalid"
        with output.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        if confirmed:
            return
        time.sleep(
            max(
                0.01,
                min(
                    5,
                    hard_stop - time.time() if now < hard_stop else 5,
                    model_deadline - time.time() if now < model_deadline else 5,
                ),
            )
        )


if __name__ == "__main__":
    monitor(Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
