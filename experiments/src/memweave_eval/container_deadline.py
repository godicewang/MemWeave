"""Linux child watchdog: stop exactly the owning Pi PID even if its JS loop blocks."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


def identity(pid):
    try:
        value = Path(f"/proc/{pid}/stat").read_text()
        return value[value.rfind(")") + 2 :].split()[19]
    except (OSError, IndexError):
        return None


def stop_at(pid: int, deadline: float, trace: Path):
    original = identity(pid)
    if pid <= 1 or original is None:
        raise ValueError("owner PID cannot be verified")
    while identity(pid) == original and time.time() < deadline:
        time.sleep(min(0.25, max(0.001, deadline - time.time())))
    if identity(pid) != original:
        return
    try:
        with trace.open("a") as stream:
            stream.write(
                json.dumps({"event": "local_deadline_stop", "pid": pid, "timestamp": time.time()})
                + "\n"
            )
    except OSError:
        pass
    os.kill(pid, signal.SIGTERM)
    time.sleep(2)
    if identity(pid) == original:
        os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    stop_at(int(sys.argv[1]), float(sys.argv[2]), Path(sys.argv[3]))
