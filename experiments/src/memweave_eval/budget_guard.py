"""Shared request admission. Unknown requests retain their entire worst-case charge.

This file is also copied verbatim into containers and uses the standard library only.
No credentials or model content enter the ledger.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

INPUT_LIMIT = 1_000_000
OUTPUT_LIMIT = 384_000
INPUT_USD = 0.3 / 1_000_000
OUTPUT_USD = 1.2 / 1_000_000
CACHE_USD = 0.006 / 1_000_000


def _write(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".quota-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(path: Path, maximum: float, deadline: float, *, arm_limits=None):
    if (path.parent/'STOP_REQUESTED').exists():raise ValueError('quota stop is durable')
    if path.exists() or not (0 < maximum <= 29) or not math.isfinite(deadline):
        raise ValueError("invalid or existing quota")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(
        path,
        {
            "schema_version": 1,
            "maximum_usd": maximum,
            "deadline": deadline,
            "exposure_usd": 0.0,
            "requests": {},
            "arm_limits": arm_limits or {},
        },
    )


def change(path: Path, operation: dict, *, now=None) -> dict:
    owner=path.parent/'WRITER_PLATFORM'
    if owner.exists()and owner.read_text().strip()!=sys.platform:
        raise ValueError('quota writer platform mismatch')
    with path.with_suffix(".lock").open("a") as lock:
        lock_deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= lock_deadline:
                    raise TimeoutError("quota lock timeout") from None
                time.sleep(0.01)
        now = time.time() if now is None else now
        ledger = json.loads(path.read_text())
        identity = operation["id"]
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("invalid request ID")
        requests = ledger["requests"]
        if operation["action"] == "reserve":
            if (path.parent/'STOP_REQUESTED').exists():raise ValueError('quota stop is durable')
            output = operation["max_output"]
            if type(output) is not int or not 0 < output <= OUTPUT_LIMIT:
                raise ValueError("unbounded output")
            if identity in requests or now >= ledger["deadline"]:
                raise ValueError("duplicate request or deadline reached")
            reserve = INPUT_LIMIT * INPUT_USD + output * OUTPUT_USD
            exposure = sum(v["charge_usd"] for v in requests.values())
            if exposure + reserve > ledger["maximum_usd"]:
                raise ValueError("global budget admission denied")
            arm = operation.get("arm")
            episode = operation.get("episode")
            episode_limit = operation.get("episode_budget")
            if episode_limit is not None and (
                type(episode_limit) not in (int, float)
                or episode_limit <= 0
                or sum(
                    r["charge_usd"]
                    for r in requests.values()
                    if r.get("episode") == episode and r.get("arm") == arm
                )
                + reserve
                > episode_limit
            ):
                raise ValueError("equal episode budget reached")
            request_limit = operation.get("max_requests")
            if request_limit is not None and (
                type(request_limit) is not int
                or request_limit < 1
                or sum(
                    r.get("episode") == episode and r.get("arm") == arm for r in requests.values()
                )
                >= request_limit
            ):
                raise ValueError("episode request limit reached")
            limits = ledger.get("arm_limits", {})
            if limits and (
                arm not in limits
                or sum(r["charge_usd"] for r in requests.values() if r.get("arm") == arm) + reserve
                > limits[arm]
            ):
                raise ValueError("arm budget admission denied")
            requests[identity] = {
                "status": "reserved",
                "max_output": output,
                "charge_usd": reserve,
                "admitted_at": now,
                "arm": arm,
                "episode": episode,
            }
        elif operation["action"] == "settle":
            record = requests[identity]
            prompt, output = operation["input"], operation["output"]
            cached = operation.get("cache_input", 0)
            if (
                type(prompt) is not int
                or type(output) is not int
                or not 0 <= prompt <= INPUT_LIMIT
                or not 0 <= output <= record["max_output"]
            ):
                raise ValueError("usage outside reserved bounds; reservation retained")
            if type(cached) is not int or not 0 <= cached <= prompt:
                raise ValueError("invalid confirmed cache usage")
            if record["status"] == "settled":
                if (prompt, output, cached) != (
                    record["input"],
                    record["output"],
                    record.get("cache_input", 0),
                ):
                    raise ValueError("conflicting usage")
                return record
            record.update(
                status="settled",
                input=prompt,
                output=output,
                cache_input=cached,
                charge_usd=(prompt - cached) * INPUT_USD + cached * CACHE_USD + output * OUTPUT_USD,
                settled_at=now,
            )
        else:
            raise ValueError("unknown quota action")
        ledger["exposure_usd"] = sum(v["charge_usd"] for v in requests.values())
        _write(path, ledger)
        return requests[identity]


if __name__ == "__main__":
    try:
        result = change(Path(sys.argv[1]), json.loads(sys.stdin.read()))
        print(json.dumps(result))
    except Exception as exc:  # noqa: BLE001 -- CLI must not disclose request bodies.
        # Never interpolate request bodies/credentials into errors.
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
