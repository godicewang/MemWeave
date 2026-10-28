"""Public Harbor Job API with read-only, redacted lifecycle hooks."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from harbor.job import Job
from harbor.models.job.config import JobConfig
from harbor.trial.hooks import TrialEvent


async def run(config_path: Path, purpose: str):
    config = JobConfig.model_validate_json(config_path.read_text())
    lifecycle = config_path.parent.parent / "lifecycle" / (config.job_name + ".jsonl")
    lifecycle.parent.mkdir(parents=True, exist_ok=True)
    job = await Job.create(config)

    async def record(event):
        value = {
            "event": event.event.value,
            "trial": event.trial_name,
            "task_id": event.task_name,
            "timestamp": event.timestamp.isoformat(),
            "purpose": purpose,
            "variant": event.config.agent.kwargs.get("variant"),
            "error_type": (
                event.result.exception_info.exception_type if event.result.exception_info else None
            ),
        }
        with lifecycle.open("a") as stream:
            stream.write(json.dumps(value) + "\n")

    for event in TrialEvent:
        job.add_hook(event, record)
    result = await job.run()
    return 2 if result.stats.n_errored_trials or result.stats.n_cancelled_trials else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(Path(sys.argv[1]), sys.argv[2])))
