"""Independent run-labelled Docker cleanup; failures retry and never imply success."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from .owned_verifiers import running_containers


def monitor(root: Path, run_id: str, model_deadline: float, hard_stop: float,
            stop_filename: str = '.watchdog-stop', log_filename: str = 'deadline-watchdog.jsonl'):
    if any(Path(name).name!=name for name in [stop_filename,log_filename]):
        raise ValueError('local observer filenames required')
    output = root / 'harbor' / log_filename
    output.parent.mkdir(parents=True, exist_ok=True)
    warned = False
    while not (root / stop_filename).exists():
        now = time.time()

        def command(args):
            try:
                return subprocess.run(
                    ["docker", *args], capture_output=True, text=True, check=False, timeout=10
                )
            except (OSError, subprocess.TimeoutExpired):
                return SimpleNamespace(returncode=124, stdout="")

        selected = running_containers(root,run_id,command)
        identities = selected['identities']
        actors = selected['actor_identities']
        record = {
            "timestamp": now,
            "containers": identities,
            "docker_query_status": 0 if selected['complete'] else 1,
            "ownership": selected,
        }
        confirmed = False
        if now >= hard_stop:
            safe = identities if identities is not None else actors
            if safe is not None:
                record["hard_stop"] = {
                    identity: command(["kill", identity]).returncode for identity in safe
                }
                check = running_containers(root,run_id,command)
                confirmed = check['complete'] and check['identities']==[]
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
        elif now >= model_deadline and actors is not None:
            record["model_stop"] = {
                identity: command(
                    ["exec", identity, "sh", "-c", "pkill -TERM -x pi || true; pkill -TERM -x node || true"]
                ).returncode
                for identity in actors
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
